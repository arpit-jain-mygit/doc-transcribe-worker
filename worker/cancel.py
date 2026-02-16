import logging
import os
import time
import redis


logger = logging.getLogger("worker.cancel")


class JobCancelledError(Exception):
    pass


def _redis_client() -> redis.Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=2,
        socket_timeout=10,
        retry_on_timeout=True,
        health_check_interval=15,
    )


def is_cancelled(job_id: str, r: redis.Redis | None = None, retries: int = 2) -> bool:
    # Cancellation checks should not fail a running job on transient Redis drops.
    # Retry with fresh connections; if still unavailable, continue as "not cancelled".
    for attempt in range(retries + 1):
        rc = r if attempt == 0 and r is not None else _redis_client()
        try:
            data = rc.hgetall(f"job_status:{job_id}")
            if not data:
                return False
            return data.get("cancel_requested") == "1" or (data.get("status") or "").upper() == "CANCELLED"
        except redis.exceptions.ConnectionError as exc:
            logger.warning(
                "cancel_check_redis_connection_error job_id=%s attempt=%s/%s error=%s",
                job_id,
                attempt + 1,
                retries + 1,
                exc,
            )
            time.sleep(0.15)
            continue

    logger.warning(
        "cancel_check_redis_unavailable job_id=%s action=continue_processing",
        job_id,
    )
    return False


def ensure_not_cancelled(job_id: str, r: redis.Redis | None = None):
    if is_cancelled(job_id, r=r):
        raise JobCancelledError(f"Job {job_id} cancelled by user")
