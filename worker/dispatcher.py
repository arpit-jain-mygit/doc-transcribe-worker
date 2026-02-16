import os
from datetime import datetime
import redis
from worker.status_machine import guarded_hset
from worker.jobs.processor import process_job

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def update_status(job_id, **fields):
    key = f"job_status:{job_id}"
    fields["updated_at"] = datetime.utcnow().isoformat()
    guarded_hset(r, key=key, mapping=fields, context="DISPATCHER_UPDATE_STATUS")
    r.expire(key, 24 * 3600)


def dispatch(job: dict):
    job_id = job.get("job_id")
    if not job_id:
        raise ValueError("job_id missing in payload")

    return process_job(job_id, job)

