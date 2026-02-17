# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging
from datetime import datetime

import redis

from worker.status_machine import guarded_hset

logger = logging.getLogger("worker.adapters.status_store")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def update_status(redis_client: redis.Redis, job_id: str, *, context: str = "STATUS_STORE", **fields):
    key = f"job_status:{job_id}"
    fields["updated_at"] = datetime.utcnow().isoformat()
    ok, prev_status, _ = guarded_hset(redis_client, key=key, mapping=fields, context=context, request_id=str(fields.get("request_id") or ""))
    if not ok:
        logger.warning("status_store_blocked key=%s from=%s to=%s", key, prev_status, fields.get("status"))
    redis_client.expire(key, 24 * 3600)
    return ok
