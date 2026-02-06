import json
import time
import logging
import os
from datetime import datetime
import socket
import redis

from worker.dispatcher import dispatch

# =========================================================
# LOGGING SETUP
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(levelname)s %(message)s",
)
logger = logging.getLogger("worker")

# =========================================================
# CONFIG
# =========================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL not set")

QUEUE_NAME = "doc_jobs"
DLQ_NAME = "doc_jobs_dead"

BRPOP_TIMEOUT = 10              # seconds
MAX_IDLE_BEFORE_RECONNECT = 60  # seconds (use 3600 in prod)

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
        socket_timeout=15,              # ← ADD THIS
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

def log_queue_depth(r):
    try:
        depth = r.llen(QUEUE_NAME)
        logger.info(f"Queue depth {QUEUE_NAME}={depth}")
    except Exception as e:
        logger.error(f"Failed to read queue depth: {e}")

# =========================================================
# STARTUP
# =========================================================
logger.info("Starting worker")
logger.info(f"REDIS_URL={REDIS_URL}")

r = connect_redis()

logger.info(f"Listening on Redis queue: {QUEUE_NAME}")

last_job_ts = time.time()

# =========================================================
# MAIN LOOP
# =========================================================
while True:
    try:
        idle_for = int(time.time() - last_job_ts)

        # -------------------------------------------------
        # IDLE SAFETY RECONNECT (THE FIX)
        # -------------------------------------------------
        if idle_for > MAX_IDLE_BEFORE_RECONNECT:
            logger.warning(
                f"Worker idle for {idle_for}s — reconnecting Redis"
            )
            try:
                r.close()
            except Exception:
                pass
            r = connect_redis()
            last_job_ts = time.time()

        logger.info("Entering BRPOP wait")

        start_wait = time.time()
        try:
            result = r.brpop(QUEUE_NAME, timeout=BRPOP_TIMEOUT)
        except (socket.timeout, redis.exceptions.TimeoutError,redis.exceptions.ConnectionError,) as e:
            waited = round(time.time() - start_wait, 2)
            logger.warning(
                f"Redis socket timeout after {waited}s — reconnecting ({e})"
            )
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
        last_job_ts = time.time()

        logger.info(f"BRPOP returned after {waited}s from queue={queue}")
        log_queue_depth(r)
        log_redis_health(r, prefix="[job-received] ")

        job = json.loads(job_raw)
        job_id = job.get("job_id", "UNKNOWN")
        key = f"job_status:{job_id}"

        logger.info(f"Parsed job_id={job_id}")
        logger.info(f"Job payload keys={list(job.keys())}")

        # -------------------------------------------------
        # MARK PROCESSING
        # -------------------------------------------------
        r.hset(
            key,
            mapping={
                "status": "PROCESSING",
                "progress": 1,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        # -------------------------------------------------
        # DISPATCH
        # -------------------------------------------------
        logger.info(f"Dispatch START job_id={job_id}")
        dispatch_start = time.time()

        output = dispatch(job)

        duration = round(time.time() - dispatch_start, 2)
        logger.info(
            f"Dispatch END job_id={job_id} duration={duration}s output={output}"
        )

        # -------------------------------------------------
        # FINALIZE
        # -------------------------------------------------
        current = r.hgetall(key)
        current_status = current.get("status")

        if current_status not in ("WAITING_APPROVAL", "APPROVED"):
            r.hset(
                key,
                mapping={
                    "status": "COMPLETED",
                    "progress": 100,
                    "updated_at": datetime.utcnow().isoformat(),
                    "duration_sec": duration,
                },
            )
        logger.info(f"Worker finished job {job_id}")
        time.sleep(0.1)

    except Exception as e:
        logger.exception("Worker error")

        try:
            if "job_id" in locals():
                r.hset(
                    key,
                    mapping={
                        "status": "FAILED",
                        "error": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                r.lpush(DLQ_NAME, job_raw)
                logger.error(f"Job {job_id} moved to DLQ")
        except Exception:
            logger.exception("Failure during error handling")

        time.sleep(2)
