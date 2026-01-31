import os
import time
from datetime import datetime
import redis

from worker.ocr import run_ocr
from worker.transcribe import run_transcription

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def update_status(job_id, **fields):
    key = f"job_status:{job_id}"
    fields["updated_at"] = datetime.utcnow().isoformat()
    r.hset(key, mapping=fields)
    r.expire(key, 24 * 3600)


from worker.transcribe import run_transcription

def dispatch(job: dict):
    job_type = job.get("job_type")

    if job_type == "TRANSCRIPTION":
        return run_transcription(job["job_id"], job)

    raise ValueError(f"Unknown job_type: {job_type}")
