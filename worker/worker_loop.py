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

logger.info("Starting worker")
logger.info(f"REDIS_URL={REDIS_URL}")
logger.info("Connecting to Redis")

try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    logger.info("Redis connection successful")
except Exception:
    logger.exception("Redis connection failed")
    raise

QUEUE_NAME = "doc_jobs"
DLQ_NAME = "doc_jobs_dead"

logger.info(f"Listening on Redis queue: {QUEUE_NAME}")

# =========================================================
# MAIN LOOP
# =========================================================
while True:
    try:
        logger.info("Waiting for job (BRPOP)...")

        start_wait = time.time()
        queue, job_raw = r.brpop(QUEUE_NAME)
        wait_time = round(time.time() - start_wait, 2)

        logger.info(f"BRPOP returned from queue={queue}")
        logger.info(f"Job received after {wait_time}s")
        logger.debug(f"Raw job payload={job_raw}")

        job = json.loads(job_raw)
        job_id = job.get("job_id", "UNKNOWN")
        key = f"job_status:{job_id}"

        logger.info(f"Parsed job_id={job_id}")
        logger.info(f"Job payload keys={list(job.keys())}")

        # ---------------------------------------------
        # Mark job as processing
        # ---------------------------------------------
        logger.info(f"Marking job {job_id} as PROCESSING in Redis")

        r.hset(
            key,
            mapping={
                "status": "PROCESSING",
                "progress": 1,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        job_start = time.time()

        # ---------------------------------------------
        # Dispatch
        # ---------------------------------------------
        logger.info(f"Dispatching job {job_id} → dispatcher.dispatch()")

        output = dispatch(job)

        logger.info(f"Dispatch returned: {output}")

        duration = round(time.time() - job_start, 2)

        # ---------------------------------------------
        # Mark success
        # ---------------------------------------------
        logger.info(f"Finalizing job {job_id} in Redis")

        r.hset(
            key,
            mapping={
                "status": "COMPLETED",
                "progress": 100,
                "updated_at": datetime.utcnow().isoformat(),
                "duration_sec": duration,
            },
        )

        logger.info(f"Job completed: {job_id} in {duration}s")

    except Exception as e:
        # ---------------------------------------------
        # FAILURE HANDLING
        # ---------------------------------------------
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
            logger.exception("Failed while handling job failure")

        time.sleep(2)
