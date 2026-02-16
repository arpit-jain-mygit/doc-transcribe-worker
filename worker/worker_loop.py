import json
import time
import logging
import os
from datetime import datetime
import socket
import redis
from dotenv import load_dotenv

from worker.cancel import JobCancelledError, is_cancelled
from worker.contract import CONTRACT_VERSION
from worker.error_catalog import classify_error
from worker.json_logging import configure_json_logging
from worker.metrics import incr, observe_ms
from worker.startup_env import validate_startup_env

# Load .env for local runs
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# =========================================================
# LOGGING SETUP
# =========================================================
level_name = os.getenv("LOG_LEVEL", "INFO").upper()
level = getattr(logging, level_name, logging.INFO)
configure_json_logging(service="doc-transcribe-worker", level=level)
logger = logging.getLogger("worker")
validate_startup_env()
from worker.dispatcher import dispatch


def log_stage_event(*, job_id: str, request_id: str, stage: str, event: str, **extra):
    payload = {
        "job_id": job_id,
        "request_id": request_id,
        "stage": stage,
        "event": event,
    }
    payload.update(extra)
    logger.info("worker_stage_event", extra=payload)

# =========================================================
# CONFIG
# =========================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL not set")

# Backward-compatible single-queue settings
QUEUE_NAME = os.getenv("QUEUE_NAME", "doc_jobs")
DLQ_NAME = os.getenv("DLQ_NAME", "doc_jobs_dead")

# New mode flag: single | both
QUEUE_MODE = os.getenv("QUEUE_MODE", "single").lower()

# Queue aliases for dual-mode consumption
CLOUD_QUEUE_NAME = os.getenv("CLOUD_QUEUE_NAME", "doc_jobs")
CLOUD_DLQ_NAME = os.getenv("CLOUD_DLQ_NAME", "doc_jobs_dead")
LOCAL_QUEUE_NAME = os.getenv("LOCAL_QUEUE_NAME", "doc_jobs_local")
LOCAL_DLQ_NAME = os.getenv("LOCAL_DLQ_NAME", "doc_jobs_local_dead")

BRPOP_TIMEOUT = 10              # seconds
MAX_IDLE_BEFORE_RECONNECT = 60  # seconds (use 3600 in prod)


# =========================================================
# QUEUE RESOLUTION
# =========================================================
def queue_targets() -> list[str]:
    if QUEUE_MODE == "both":
        targets = [LOCAL_QUEUE_NAME, CLOUD_QUEUE_NAME]
        # Keep order stable while deduplicating
        seen = set()
        ordered = []
        for q in targets:
            if q and q not in seen:
                seen.add(q)
                ordered.append(q)
        return ordered

    return [QUEUE_NAME]


def dlq_for_queue(queue: str) -> str:
    if QUEUE_MODE == "both":
        if queue == CLOUD_QUEUE_NAME:
            return CLOUD_DLQ_NAME
        if queue == LOCAL_QUEUE_NAME:
            return LOCAL_DLQ_NAME
    return DLQ_NAME


def queue_source_label(queue: str) -> str:
    if QUEUE_MODE == "both":
        if queue == CLOUD_QUEUE_NAME:
            return "CLOUD"
        if queue == LOCAL_QUEUE_NAME:
            return "LOCAL"
        return "UNKNOWN"
    return "SINGLE"


# =========================================================
# REDIS CONNECT
# =========================================================
def connect_redis():
    logger.info("Connecting to Redis")
    r = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=2,
        socket_timeout=15,
        retry_on_timeout=True,
        health_check_interval=30,
    )

    r.ping()

    try:
        r.client_setname("doc-worker")
        logger.info("Redis client name set to doc-worker")
    except Exception:
        logger.warning("Could not set Redis client name")

    try:
        logger.info(f"Redis client_id={r.client_id()}")
    except Exception:
        logger.warning("Could not fetch Redis client_id")

    logger.info("Redis connection successful")
    return r


# =========================================================
# DIAGNOSTIC HELPERS
# =========================================================
def log_redis_health(r, prefix=""):
    try:
        t0 = time.time()
        pong = r.ping()
        latency = int((time.time() - t0) * 1000)
        logger.info(f"{prefix}Redis PING ok={pong} latency={latency}ms")
    except Exception as e:
        logger.error(f"{prefix}Redis PING FAILED: {e}")


def log_queue_depths(r):
    for q in queue_targets():
        try:
            depth = r.llen(q)
            logger.info(f"Queue depth {q}={depth}")
        except Exception as e:
            logger.error(f"Failed to read queue depth for {q}: {e}")


# =========================================================
# STARTUP
# =========================================================
logger.info("Starting worker")
logger.info(f"REDIS_URL={REDIS_URL}")
logger.info(f"QUEUE_MODE={QUEUE_MODE}")
logger.info(f"QUEUE_TARGETS={queue_targets()}")

r = connect_redis()

last_job_ts = time.time()

# =========================================================
# MAIN LOOP
# =========================================================
while True:
    try:
        idle_for = int(time.time() - last_job_ts)

        if idle_for > MAX_IDLE_BEFORE_RECONNECT:
            logger.warning(f"Worker idle for {idle_for}s — reconnecting Redis")
            try:
                r.close()
            except Exception:
                pass
            r = connect_redis()
            last_job_ts = time.time()

        targets = queue_targets()
        logger.info(f"Entering BRPOP wait targets={targets}")

        start_wait = time.time()
        try:
            result = r.brpop(targets, timeout=BRPOP_TIMEOUT)
        except (socket.timeout, redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as e:
            waited = round(time.time() - start_wait, 2)
            logger.warning(f"Redis socket timeout after {waited}s — reconnecting ({e})")
            try:
                r.close()
            except Exception:
                pass
            r = connect_redis()
            continue

        waited = round(time.time() - start_wait, 2)

        if result is None:
            logger.info(f"BRPOP timeout after {waited}s (idle)")
            log_redis_health(r, prefix="[timeout] ")
            time.sleep(0.1)
            continue

        queue, job_raw = result
        active_dlq = dlq_for_queue(queue)
        source_label = queue_source_label(queue)
        last_job_ts = time.time()

        logger.info(f"BRPOP returned after {waited}s from queue={queue}")
        logger.info(f"Queue source classification={source_label}")
        logger.info(f"DLQ target for this job={active_dlq}")
        log_queue_depths(r)
        log_redis_health(r, prefix="[job-received] ")

        job = json.loads(job_raw)
        job_id = job.get("job_id", "UNKNOWN")
        request_id = str(job.get("request_id") or "").strip()
        key = f"job_status:{job_id}"

        logger.info(f"Parsed job_id={job_id}")
        if request_id:
            logger.info(f"Parsed request_id={request_id}")
        logger.info(f"Job payload keys={list(job.keys())}")
        incr("worker_jobs_received_total", queue=queue, source=source_label, job_type=job.get("job_type", "UNKNOWN"))
        log_stage_event(
            job_id=job_id,
            request_id=request_id,
            stage="JOB_RECEIVED",
            event="STARTED",
            queue=queue,
            source_label=source_label,
        )

        current = r.hgetall(key)
        if current and (current.get("cancel_requested") == "1" or (current.get("status") or "").upper() == "CANCELLED"):
            logger.info(f"Skipping cancelled job_id={job_id}")
            r.hset(
                key,
                mapping={
                    "contract_version": CONTRACT_VERSION,
                    "request_id": request_id,
                    "status": "CANCELLED",
                    "stage": "Cancelled by user",
                    "updated_at": datetime.utcnow().isoformat(),
                    "error_code": "CANCELLED_BY_USER",
                    "error_message": "Job was cancelled by user.",
                    "error_detail": "",
                    "error": "Job was cancelled by user.",
                },
            )
            continue

        r.hset(
            key,
            mapping={
                "contract_version": CONTRACT_VERSION,
                "request_id": request_id,
                "status": "PROCESSING",
                "stage": "Processing started",
                "progress": 1,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        logger.info(f"Dispatch START job_id={job_id} request_id={request_id}")
        log_stage_event(job_id=job_id, request_id=request_id, stage="DISPATCH", event="STARTED")
        dispatch_start = time.time()

        output = dispatch(job)

        duration = round(time.time() - dispatch_start, 2)
        observe_ms(
            "worker_dispatch_latency_ms",
            duration * 1000.0,
            queue=queue,
            source=source_label,
            job_type=job.get("job_type", "UNKNOWN"),
        )
        logger.info(f"Dispatch END job_id={job_id} request_id={request_id} duration={duration}s output={output}")
        log_stage_event(
            job_id=job_id,
            request_id=request_id,
            stage="DISPATCH",
            event="COMPLETED",
            duration_sec=duration,
        )

        current = r.hgetall(key)
        current_status = (current.get("status") or "").upper()

        if current_status not in ("WAITING_APPROVAL", "APPROVED", "CANCELLED"):
            r.hset(
                key,
                mapping={
                    "contract_version": CONTRACT_VERSION,
                    "request_id": request_id,
                    "status": "COMPLETED",
                    "stage": current.get("stage") or "Completed",
                    "progress": 100,
                    "updated_at": datetime.utcnow().isoformat(),
                    "duration_sec": duration,
                    "error_code": "",
                    "error_message": "",
                    "error_detail": "",
                    "error": "",
                },
            )
        logger.info(f"Worker finished job {job_id} request_id={request_id}")
        incr("worker_jobs_completed_total", queue=queue, source=source_label, job_type=job.get("job_type", "UNKNOWN"))
        log_stage_event(job_id=job_id, request_id=request_id, stage="JOB_EXECUTION", event="COMPLETED")
        time.sleep(0.1)

    except JobCancelledError:
        logger.info(f"Job {job_id} cancelled during processing")
        incr("worker_jobs_cancelled_total", queue=queue if "queue" in locals() else "UNKNOWN")
        log_stage_event(job_id=job_id, request_id=request_id if "request_id" in locals() else "", stage="JOB_EXECUTION", event="CANCELLED")
        try:
            r.hset(
                key,
                mapping={
                    "contract_version": CONTRACT_VERSION,
                    "request_id": request_id,
                    "status": "CANCELLED",
                    "stage": "Cancelled by user",
                    "progress": 100,
                    "updated_at": datetime.utcnow().isoformat(),
                    "error_code": "CANCELLED_BY_USER",
                    "error_message": "Job was cancelled by user.",
                    "error_detail": "",
                    "error": "Job was cancelled by user.",
                },
            )
        except Exception:
            logger.exception("Failed to mark job cancelled")
        time.sleep(0.2)

    except Exception as e:
        logger.exception("Worker error")
        incr(
            "worker_jobs_failed_total",
            queue=queue if "queue" in locals() else "UNKNOWN",
            job_type=job.get("job_type", "UNKNOWN") if "job" in locals() and isinstance(job, dict) else "UNKNOWN",
        )
        log_stage_event(
            job_id=job_id if "job_id" in locals() else "UNKNOWN",
            request_id=request_id if "request_id" in locals() else "",
            stage="JOB_EXECUTION",
            event="FAILED",
            error=f"{e.__class__.__name__}: {e}",
        )

        try:
            if "job_id" in locals():
                if is_cancelled(job_id, r=r):
                    r.hset(
                        key,
                        mapping={
                            "contract_version": CONTRACT_VERSION,
                            "request_id": request_id,
                            "status": "CANCELLED",
                            "stage": "Cancelled by user",
                            "updated_at": datetime.utcnow().isoformat(),
                            "error_code": "CANCELLED_BY_USER",
                            "error_message": "Job was cancelled by user.",
                            "error_detail": "",
                            "error": "Job was cancelled by user.",
                        },
                    )
                    logger.info(f"Job {job_id} cancelled (post-error path)")
                else:
                    error_code, error_message = classify_error(e)
                    error_detail = f"{e.__class__.__name__}: {e}"
                    r.hset(
                        key,
                        mapping={
                            "contract_version": CONTRACT_VERSION,
                            "request_id": request_id,
                            "status": "FAILED",
                            "stage": "Processing failed",
                            "error_code": error_code,
                            "error_message": error_message,
                            "error_detail": error_detail,
                            "error": error_message,
                            "updated_at": datetime.utcnow().isoformat(),
                        },
                    )
                    r.lpush(active_dlq if "active_dlq" in locals() else DLQ_NAME, job_raw)
                    logger.error(
                        "Job %s request_id=%s moved to DLQ error_code=%s detail=%s",
                        job_id,
                        request_id,
                        error_code,
                        error_detail,
                    )
        except Exception:
            logger.exception("Failure during error handling")

        time.sleep(2)
