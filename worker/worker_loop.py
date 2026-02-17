# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
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
from worker.status_machine import guarded_hset
from worker.error_catalog import classify_error
from worker.dead_letter import build_dead_letter_entry
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


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
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
OCR_QUEUE_NAME = os.getenv("OCR_QUEUE_NAME", "doc_jobs_ocr")
OCR_DLQ_NAME = os.getenv("OCR_DLQ_NAME", "doc_jobs_ocr_dead")
TRANSCRIPTION_QUEUE_NAME = os.getenv("TRANSCRIPTION_QUEUE_NAME", "doc_jobs_transcription")
TRANSCRIPTION_DLQ_NAME = os.getenv("TRANSCRIPTION_DLQ_NAME", "doc_jobs_transcription_dead")

WORKER_MAX_INFLIGHT_OCR = int(os.getenv("WORKER_MAX_INFLIGHT_OCR", "1"))
WORKER_MAX_INFLIGHT_TRANSCRIPTION = int(os.getenv("WORKER_MAX_INFLIGHT_TRANSCRIPTION", "1"))
RETRY_BUDGET_TRANSIENT = int(os.getenv("RETRY_BUDGET_TRANSIENT", "2"))
RETRY_BUDGET_MEDIA = int(os.getenv("RETRY_BUDGET_MEDIA", "0"))
RETRY_BUDGET_DEFAULT = int(os.getenv("RETRY_BUDGET_DEFAULT", "0"))

BRPOP_TIMEOUT = 10              # seconds
MAX_IDLE_BEFORE_RECONNECT = 60  # seconds (use 3600 in prod)


# =========================================================
# QUEUE RESOLUTION
# =========================================================
# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def queue_targets() -> list[str]:
    if QUEUE_MODE == "both":
        targets = [LOCAL_QUEUE_NAME, CLOUD_QUEUE_NAME]
    elif QUEUE_MODE == "partitioned":
        targets = [OCR_QUEUE_NAME, TRANSCRIPTION_QUEUE_NAME]
    else:
        targets = [QUEUE_NAME]

    # Keep order stable while deduplicating
    seen = set()
    ordered = []
    for q in targets:
        if q and q not in seen:
            seen.add(q)
            ordered.append(q)
    return ordered


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def dlq_for_queue(queue: str) -> str:
    if QUEUE_MODE == "both":
        if queue == CLOUD_QUEUE_NAME:
            return CLOUD_DLQ_NAME
        if queue == LOCAL_QUEUE_NAME:
            return LOCAL_DLQ_NAME
    if QUEUE_MODE == "partitioned":
        if queue == OCR_QUEUE_NAME:
            return OCR_DLQ_NAME
        if queue == TRANSCRIPTION_QUEUE_NAME:
            return TRANSCRIPTION_DLQ_NAME
    return DLQ_NAME


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def queue_source_label(queue: str) -> str:
    if QUEUE_MODE == "both":
        if queue == CLOUD_QUEUE_NAME:
            return "CLOUD"
        if queue == LOCAL_QUEUE_NAME:
            return "LOCAL"
        return "UNKNOWN"
    if QUEUE_MODE == "partitioned":
        if queue == OCR_QUEUE_NAME:
            return "OCR"
        if queue == TRANSCRIPTION_QUEUE_NAME:
            return "TRANSCRIPTION"
        return "UNKNOWN"
    return "SINGLE"


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _job_type(job: dict) -> str:
    return str(job.get("job_type") or job.get("type") or "").upper()


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def inflight_limit_for(job_type: str) -> int:
    if job_type == "OCR":
        return max(0, WORKER_MAX_INFLIGHT_OCR)
    if job_type == "TRANSCRIPTION":
        return max(0, WORKER_MAX_INFLIGHT_TRANSCRIPTION)
    return 1


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def inflight_set_key(job_type: str) -> str:
    jt = job_type if job_type in {"OCR", "TRANSCRIPTION"} else "OTHER"
    return f"worker:inflight:{jt}"


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def should_retry(error_code: str, attempts: int) -> tuple[bool, int]:
    if error_code in {"INFRA_REDIS", "INFRA_GCS", "RATE_LIMIT_EXCEEDED"}:
        budget = RETRY_BUDGET_TRANSIENT
    elif error_code in {"MEDIA_DECODE_FAILED", "INPUT_NOT_FOUND"}:
        budget = RETRY_BUDGET_MEDIA
    else:
        budget = RETRY_BUDGET_DEFAULT
    return attempts < budget, budget


# =========================================================
# REDIS CONNECT
# =========================================================
# User value: This step keeps the user OCR/transcription flow accurate and dependable.
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
# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def log_redis_health(r, prefix=""):
    try:
        t0 = time.time()
        pong = r.ping()
        latency = int((time.time() - t0) * 1000)
        logger.info(f"{prefix}Redis PING ok={pong} latency={latency}ms")
    except Exception as e:
        logger.error(f"{prefix}Redis PING FAILED: {e}")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
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
logger.info(
    "WORKER_CONCURRENCY_LIMITS ocr=%s transcription=%s retry_budget_transient=%s retry_budget_media=%s retry_budget_default=%s",
    WORKER_MAX_INFLIGHT_OCR,
    WORKER_MAX_INFLIGHT_TRANSCRIPTION,
    RETRY_BUDGET_TRANSIENT,
    RETRY_BUDGET_MEDIA,
    RETRY_BUDGET_DEFAULT,
)
worker_identity = f"{socket.gethostname()}:{os.getpid()}"
logger.info("WORKER_ID=%s", worker_identity)

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
        job_type = _job_type(job)
        current_attempt = int(job.get("attempts", 0) or 0)
        max_allowed = inflight_limit_for(job_type)
        inflight_key = inflight_set_key(job_type)
        if max_allowed <= 0:
            logger.warning(
                "Job %s blocked by zero inflight limit for type=%s queue=%s; requeueing",
                job_id,
                job_type,
                queue,
            )
            r.rpush(queue, job_raw)
            time.sleep(0.25)
            continue
        try:
            inflight_now = int(r.scard(inflight_key) or 0)
        except Exception:
            inflight_now = 0
        if inflight_now >= max_allowed:
            logger.info(
                "inflight_limit_hit type=%s limit=%s current=%s queue=%s job_id=%s requeue=true",
                job_type,
                max_allowed,
                inflight_now,
                queue,
                job_id,
            )
            r.rpush(queue, job_raw)
            time.sleep(0.25)
            continue
        r.sadd(inflight_key, job_id)
        r.expire(inflight_key, 86400)
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
            ok, prev_status, _ = guarded_hset(
                r,
                key=key,
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
                context="WORKER_SKIP_CANCELLED",
                request_id=request_id,
            )
            if not ok:
                logger.warning("Skip-cancel update blocked job_id=%s from=%s", job_id, prev_status)
            continue
        ok, prev_status, _ = guarded_hset(
            r,
            key=key,
            mapping={
                "contract_version": CONTRACT_VERSION,
                "request_id": request_id,
                "status": "PROCESSING",
                "stage": "Processing started",
                "progress": 1,
                "updated_at": datetime.utcnow().isoformat(),
            },
            context="WORKER_PROCESSING_START",
            request_id=request_id,
        )
        if not ok:
            raise RuntimeError(f"Invalid status transition to PROCESSING from {prev_status or 'NONE'}")

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
            ok, prev_status, _ = guarded_hset(
                r,
                key=key,
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
                context="WORKER_COMPLETE",
                request_id=request_id,
            )
            if not ok:
                logger.warning("Completion status update blocked job_id=%s from=%s", job_id, prev_status)
        logger.info(f"Worker finished job {job_id} request_id={request_id}")
        try:
            r.srem(inflight_set_key(job_type), job_id)
        except Exception:
            logger.warning("Failed to clear inflight marker job_id=%s job_type=%s", job_id, job_type)
        incr("worker_jobs_completed_total", queue=queue, source=source_label, job_type=job.get("job_type", "UNKNOWN"))
        log_stage_event(job_id=job_id, request_id=request_id, stage="JOB_EXECUTION", event="COMPLETED")
        time.sleep(0.1)

    except JobCancelledError:
        logger.info(f"Job {job_id} cancelled during processing")
        try:
            jt = _job_type(job) if "job" in locals() and isinstance(job, dict) else "OTHER"
            r.srem(inflight_set_key(jt), job_id)
        except Exception:
            logger.warning("Failed to clear inflight marker for cancelled job_id=%s", job_id if "job_id" in locals() else "UNKNOWN")
        incr("worker_jobs_cancelled_total", queue=queue if "queue" in locals() else "UNKNOWN")
        log_stage_event(job_id=job_id, request_id=request_id if "request_id" in locals() else "", stage="JOB_EXECUTION", event="CANCELLED")
        try:
            ok, prev_status, _ = guarded_hset(
                r,
                key=key,
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
                context="WORKER_CANCELLED_EXCEPTION",
                request_id=request_id,
            )
            if not ok:
                logger.warning("Cancelled status update blocked job_id=%s from=%s", job_id, prev_status)
        except Exception:
            logger.exception("Failed to mark job cancelled")
        time.sleep(0.2)

    except Exception as e:
        logger.exception("Worker error")
        try:
            if "job_id" in locals():
                jt = _job_type(job) if "job" in locals() and isinstance(job, dict) else "OTHER"
                r.srem(inflight_set_key(jt), job_id)
        except Exception:
            logger.warning("Failed to clear inflight marker for failed job_id=%s", job_id if "job_id" in locals() else "UNKNOWN")
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
                    ok, prev_status, _ = guarded_hset(
                        r,
                        key=key,
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
                        context="WORKER_ERROR_CANCELLED",
                        request_id=request_id,
                    )
                    if not ok:
                        logger.warning("Post-error cancelled update blocked job_id=%s from=%s", job_id, prev_status)
                    logger.info(f"Job {job_id} cancelled (post-error path)")
                else:
                    error_code, error_message = classify_error(e)
                    error_detail = f"{e.__class__.__name__}: {e}"
                    latest = r.hgetall(key) if key else {}
                    failed_stage = (latest.get("stage") or "Processing failed").strip()
                    retry_allowed, retry_budget = should_retry(error_code, current_attempt if "current_attempt" in locals() else 0)
                    if retry_allowed:
                        next_attempt = (current_attempt if "current_attempt" in locals() else 0) + 1
                        backoff = min(5.0, 0.5 * (2 ** max(0, next_attempt - 1)))
                        ok, prev_status, _ = guarded_hset(
                            r,
                            key=key,
                            mapping={
                                "contract_version": CONTRACT_VERSION,
                                "request_id": request_id,
                                "status": "QUEUED",
                                "stage": f"Retry scheduled ({next_attempt}/{retry_budget})",
                                "updated_at": datetime.utcnow().isoformat(),
                                "error_code": error_code,
                                "error_message": error_message,
                                "error_detail": error_detail,
                                "error": error_message,
                            },
                            context="WORKER_RETRY_REQUEUE",
                            request_id=request_id,
                        )
                        if not ok:
                            logger.warning("Retry status update blocked job_id=%s from=%s", job_id, prev_status)
                        retry_payload = dict(job)
                        retry_payload["attempts"] = next_attempt
                        retry_payload["max_attempts"] = retry_budget
                        logger.warning(
                            "Retrying job_id=%s request_id=%s error_code=%s attempt=%s/%s backoff_sec=%.2f",
                            job_id,
                            request_id,
                            error_code,
                            next_attempt,
                            retry_budget,
                            backoff,
                        )
                        time.sleep(backoff)
                        r.rpush(queue if "queue" in locals() else QUEUE_NAME, json.dumps(retry_payload, ensure_ascii=False))
                        continue
                    ok, prev_status, _ = guarded_hset(
                        r,
                        key=key,
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
                        context="WORKER_ERROR_FAILED",
                        request_id=request_id,
                    )
                    if not ok:
                        logger.warning("Failed status update blocked job_id=%s from=%s", job_id, prev_status)
                    target_dlq = active_dlq if "active_dlq" in locals() else DLQ_NAME
                    dlq_payload = build_dead_letter_entry(
                        job=job,
                        queue_name=queue if "queue" in locals() else "UNKNOWN",
                        dlq_name=target_dlq,
                        source_label=source_label if "source_label" in locals() else "UNKNOWN",
                        error_code=error_code,
                        error_message=error_message,
                        error_detail=error_detail,
                        failed_stage=failed_stage,
                        worker_id=worker_identity,
                    )
                    log_stage_event(
                        job_id=job_id,
                        request_id=request_id,
                        stage="DLQ_ENQUEUE",
                        event="STARTED",
                        dlq_name=target_dlq,
                        error_code=error_code,
                    )
                    r.lpush(target_dlq, json.dumps(dlq_payload, ensure_ascii=False))
                    log_stage_event(
                        job_id=job_id,
                        request_id=request_id,
                        stage="DLQ_ENQUEUE",
                        event="COMPLETED",
                        dlq_name=target_dlq,
                        error_code=error_code,
                        attempts=dlq_payload.get("attempts"),
                        max_attempts=dlq_payload.get("max_attempts"),
                    )
                    logger.error(
                        "Job %s request_id=%s moved to DLQ=%s error_code=%s stage=%s detail=%s attempts=%s/%s",
                        job_id,
                        request_id,
                        target_dlq,
                        error_code,
                        failed_stage,
                        error_detail,
                        dlq_payload.get("attempts"),
                        dlq_payload.get("max_attempts"),
                    )
        except Exception:
            logger.exception("Failure during error handling")

        time.sleep(2)
