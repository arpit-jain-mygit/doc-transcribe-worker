import os
import redis


class JobCancelledError(Exception):
    pass


def _redis_client() -> redis.Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def is_cancelled(job_id: str, r: redis.Redis | None = None) -> bool:
    rc = r or _redis_client()
    data = rc.hgetall(f"job_status:{job_id}")
    if not data:
        return False
    return data.get("cancel_requested") == "1" or (data.get("status") or "").upper() == "CANCELLED"


def ensure_not_cancelled(job_id: str, r: redis.Redis | None = None):
    if is_cancelled(job_id, r=r):
        raise JobCancelledError(f"Job {job_id} cancelled by user")
