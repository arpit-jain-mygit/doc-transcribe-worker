# -*- coding: utf-8 -*-
"""
Worker loop for doc-transcribe-worker

Features:
- Redis queue polling
- Job execution via dispatcher
- Retry handling
- Dead-Letter Queue (DLQ)
- Job status tracking (Redis hash)
- Structured JSON logs
- Healthcheck support
"""

import os
import json
import time
import socket
from datetime import datetime

import redis
from dotenv import load_dotenv

from worker.dispatcher import dispatch
from worker.utils.gcs import append_log


# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

# =========================================================
# CONFIG
# =========================================================
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.environ.get("QUEUE_NAME", "doc_jobs")
DLQ_NAME = os.environ.get("DLQ_NAME", "doc_jobs_dead")
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", 3))

WORKER_ID = socket.gethostname()
SCHEMA_VERSION = "v1"

# =========================================================
# REDIS CLIENT
# =========================================================
redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

# =========================================================
# STRUCTURED LOGGING
# =========================================================
def log_event(level: str, message: str, **fields):
    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "message": message,
        "worker_id": WORKER_ID,
        **fields,
    }
    print(json.dumps(payload), flush=True)

# Convenience wrappers
def log_info(msg, **f): log_event("INFO", msg, **f)
def log_warn(msg, **f): log_event("WARN", msg, **f)
def log_error(msg, **f): log_event("ERROR", msg, **f)

# =========================================================
# JOB STATUS TRACKING
# =========================================================
def update_job_status(job_id: str, fields: dict):
    key = f"job_status:{job_id}"
    fields["updated_at"] = datetime.utcnow().isoformat() + "Z"
    redis_client.hset(key, mapping=fields)

# =========================================================
# DEAD-LETTER QUEUE PUSH
# =========================================================
def push_to_dlq(job: dict, error: Exception, attempts: int):
    dlq_entry = {
        "job_id": job.get("job_id"),
        "job_type": job.get("job_type"),
        "input_type": job.get("input_type"),
        "payload": job,
        "status": "FAILED",
        "error": str(error),
        "error_type": error.__class__.__name__,
        "attempts": attempts,
        "max_attempts": MAX_ATTEMPTS,
        "failed_at": datetime.utcnow().isoformat() + "Z",
        "worker_id": WORKER_ID,
        "schema_version": SCHEMA_VERSION,
    }

    redis_client.lpush(DLQ_NAME, json.dumps(dlq_entry))

    log_error(
        "Job moved to DLQ",
        job_id=job.get("job_id"),
        attempts=attempts,
        dlq_queue=DLQ_NAME,
    )

# =========================================================
# HEALTHCHECK
# =========================================================
def healthcheck():
    try:
        redis_client.ping()
        return {
            "status": "OK",
            "worker_id": WORKER_ID,
            "redis": "connected",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
        }

# =========================================================
# WORKER LOOP
# =========================================================
def run_worker():
    log_info(
        "Worker started",
        redis_url=REDIS_URL,
        queue=QUEUE_NAME,
        dlq=DLQ_NAME,
        max_attempts=MAX_ATTEMPTS,
    )

    while True:
        try:
            # -------------------------------------------------
            # BLOCK FOR JOB
            # -------------------------------------------------
            log_info("Waiting for job", action="BRPOP", queue=QUEUE_NAME)
            _, raw_job = redis_client.brpop(QUEUE_NAME)

            # -------------------------------------------------
            # PARSE JOB
            # -------------------------------------------------
            job = json.loads(raw_job)
            job_id = job.get("job_id", "unknown")

            log_info("Job received", job_id=job_id)
            append_log(job_id, "Job received by worker")

            # -------------------------------------------------
            # ATTEMPT TRACKING
            # -------------------------------------------------
            attempt_key = f"job_attempts:{job_id}"
            attempts = redis_client.incr(attempt_key)

            update_job_status(job_id, {
                "job_id": job_id,
                "status": "PROCESSING",
                "job_type": job.get("job_type"),
                "input_type": job.get("input_type"),
                "attempts": attempts,
            })
            append_log(job_id, f"Processing started (attempt {attempts})")

            log_info(
                "Job processing started",
                job_id=job_id,
                attempt=attempts,
            )

            # -------------------------------------------------
            # DISPATCH
            # -------------------------------------------------
            start_exec = time.perf_counter()

            try:
                result = dispatch(job)

                exec_time = time.perf_counter() - start_exec

                output_path = result.get("output_path", "")

                update_job_status(job_id, {
                    "status": "COMPLETED",
                    "output_path": output_path,
                    "output_filename": os.path.basename(output_path) if output_path else "",
                })
                append_log(job_id, "Job completed successfully")

                redis_client.delete(attempt_key)

                log_info(
                    "Job completed successfully",
                    job_id=job_id,
                    duration_sec=round(exec_time, 2),
                )

            except Exception as e:
                exec_time = time.perf_counter() - start_exec

                log_error(
                    "Job execution failed",
                    job_id=job_id,
                    attempt=attempts,
                    duration_sec=round(exec_time, 2),
                    error=str(e),
                )
                append_log(job_id, f"Job execution failed: {str(e)}")

                if attempts >= MAX_ATTEMPTS:
                    update_job_status(job_id, {
                        "status": "FAILED",
                        "error": str(e),
                    })

                    push_to_dlq(job, e, attempts)
                    append_log(job_id, f"Moved to DLQ after {attempts} attempts")

                    redis_client.delete(attempt_key)

                else:
                    log_warn(
                        "Retrying job",
                        job_id=job_id,
                        next_attempt=attempts + 1,
                    )

                    redis_client.lpush(QUEUE_NAME, raw_job)
                    time.sleep(1)

        except Exception as fatal:
            log_error("Worker-level failure", error=str(fatal))
            time.sleep(5)

# =========================================================
# ENTRYPOINT
# =========================================================
if __name__ == "__main__":
    run_worker()
