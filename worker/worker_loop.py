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
REDIS_URL = os.environ.get("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL not set")

logger.info("Starting worker")
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
        _, job_raw = r.brpop(QUEUE_NAME)
        wait_time = round(time.time() - start_wait, 2)

        logger.info(f"Job received after {wait_time}s")

        job = json.loads(job_raw)
        job_id = job.get("job_id", "UNKNOWN")
        key = f"job:{job_id}"

        logger.info(f"Job payload: {job}")

        # ---------------------------------------------
        # Mark job as processing
        # ---------------------------------------------
        r.hset(
            key,
            mapping={
                "status": "processing",
                "progress": 0,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        job_start = time.time()

        # ---------------------------------------------
        # Dispatch
        # ---------------------------------------------
        logger.info(f"Dispatching job {job_id}")

        output = dispatch(job)

        duration = round(time.time() - job_start, 2)

        # ---------------------------------------------
        # Mark success
        # ---------------------------------------------
        r.hset(
            key,
            mapping={
                "status": "completed",
                "progress": 100,
                "output_uri": output.get("output_path") if isinstance(output, dict) else "",
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
                r.hset(
                    key,
                    mapping={
                        "status": "failed",
                        "error": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                r.lpush(DLQ_NAME, job_raw)
                logger.error(f"Job moved to DLQ: {job_id}")
        except Exception:
            logger.exception("Failed while handling job failure")

        # Prevent tight crash loops
        time.sleep(2)
