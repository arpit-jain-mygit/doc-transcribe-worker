import redis
import json
import time
import logging
import os
from datetime import datetime

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
# REDIS INIT
# =========================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL not set")

QUEUE_NAME = "doc_jobs"
DLQ_NAME = "doc_jobs_dead"

# =========================================================
# DIAGNOSTIC HELPERS (LOG ONLY — NO LOGIC CHANGE)
# =========================================================
def log_redis_health(r, prefix=""):
    try:
        start = time.time()
        pong = r.ping()
        latency = int((time.time() - start) * 1000)
        logger.info(f"{prefix}Redis PING ok={pong} latency={latency}ms")
    except Exception as e:
        logger.error(f"{prefix}Redis PING FAILED: {e}")

def log_queue_depth(r):
    try:
        depth = r.llen(QUEUE_NAME)
        logger.info(f"Queue depth {QUEUE_NAME} = {depth}")
    except Exception as e:
        logger.error(f"Failed to read queue depth: {e}")

# =========================================================
# STARTUP
# =========================================================
logger.info("Starting worker")
logger.info(f"REDIS_URL={REDIS_URL}")
logger.info("Connecting to Redis")

try:
    r = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=1,
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
        client_id = r.client_id()
        logger.info(f"Redis client_id={client_id}")
    except Exception:
        logger.warning("Could not fetch Redis client_id")

    logger.info("Redis connection successful")

except Exception:
    logger.exception("Redis connection failed")
    raise

logger.info(f"Listening on Redis queue: {QUEUE_NAME}")

# =========================================================
# MAIN LOOP
# =========================================================
while True:
    try:
        # -------------------------------------------------
        # HEARTBEAT — proves loop is alive even when idle
        # -------------------------------------------------
        if int(time.time()) % 60 == 0:
            logger.info("Worker heartbeat — loop alive")

        logger.info("Entering BRPOP wait")

        start_wait = time.time()
        result = r.brpop(QUEUE_NAME, timeout=30)
        wait_time = round(time.time() - start_wait, 2)

        if result is None:
            logger.info(f"BRPOP timeout after {wait_time}s (idle but alive)")
            log_redis_health(r, prefix="[after-timeout] ")
            time.sleep(0.1)
            continue

        logger.info(f"BRPOP returned after {wait_time}s")

        queue, job_raw = result

        log_queue_depth(r)
        log_redis_health(r, prefix="[job-received] ")

        logger.debug(f"Raw job payload={job_raw}")

        job = json.loads(job_raw)
        job_id = job.get("job_id", "UNKNOWN")
        key = f"job_status:{job_id}"

        logger.info(f"Parsed job_id={job_id}")
        logger.info(f"Job payload keys={list(job.keys())}")

        # -------------------------------------------------
        # MARK PROCESSING
        # -------------------------------------------------
        logger.info(f"Marking job {job_id} as PROCESSING")

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

        dispatch_time = round(time.time() - dispatch_start, 2)
        logger.info(f"Dispatch END job_id={job_id} took {dispatch_time}s")
        logger.info(f"Dispatch output={output}")

        # -------------------------------------------------
        # FINALIZE
        # -------------------------------------------------
        log_redis_health(r, prefix="[pre-finalize] ")

        current = r.hgetall(key)
        current_status = current.get("status")

        logger.info(
            f"Post-dispatch Redis status job_id={job_id} status={current_status}"
        )

        if current_status in ("WAITING_APPROVAL", "APPROVED"):
            logger.info(
                f"Skipping overwrite for job {job_id} (status={current_status})"
            )
        else:
            logger.info(f"Finalizing job {job_id} as COMPLETED")

            r.hset(
                key,
                mapping={
                    "status": "COMPLETED",
                    "progress": 100,
                    "updated_at": datetime.utcnow().isoformat(),
                    "duration_sec": dispatch_time,
                },
            )

            r.hsetnx(key, "output_path", current.get("output_path"))

        logger.info(f"Worker finished job {job_id}")

        time.sleep(0.1)

    except Exception as e:
        # -------------------------------------------------
        # FAILURE HANDLING
        # -------------------------------------------------
        logger.exception("Worker error")

        try:
            if "job_id" in locals():
                logger.error(f"Marking job {job_id} as FAILED")

                r.hset(
                    key,
                    mapping={
                        "status": "FAILED",
                        "error": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )

                r.lpush(DLQ_NAME, job_raw)
                logger.error(f"Job moved to DLQ: {job_id}")

        except Exception:
            logger.exception("Failure during error handling")

        time.sleep(2)
