# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging
import os
import redis

from worker.utils.retry_policy import REDIS_POLICY, run_with_retry


logger = logging.getLogger("worker.cancel")


class JobCancelledError(Exception):
    pass


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
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


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def is_cancelled(job_id: str, r: redis.Redis | None = None, retries: int = 2) -> bool:
    # Backward-compatible parameter: if explicit retries provided, override policy.
    policy = REDIS_POLICY
    if retries != REDIS_POLICY.max_retries:
        policy = type(REDIS_POLICY)(
            name=REDIS_POLICY.name,
            max_retries=max(0, retries),
            base_delay_sec=REDIS_POLICY.base_delay_sec,
            max_delay_sec=REDIS_POLICY.max_delay_sec,
            jitter_ratio=REDIS_POLICY.jitter_ratio,
        )

    # User value: This step keeps the user OCR/transcription flow accurate and dependable.
    def _read_cancel_state() -> bool:
        rc = r if r is not None else _redis_client()
        data = rc.hgetall(f"job_status:{job_id}")
        if not data:
            return False
        return data.get("cancel_requested") == "1" or (data.get("status") or "").upper() == "CANCELLED"

    # User value: This step keeps the user OCR/transcription flow accurate and dependable.
    def _on_retry(attempt: int, exc: BaseException) -> None:
        logger.warning(
            "cancel_check_redis_connection_error job_id=%s attempt=%s/%s error=%s",
            job_id,
            attempt,
            policy.max_retries,
            exc,
        )

    try:
        return run_with_retry(
            operation="cancel_check",
            target=job_id,
            fn=_read_cancel_state,
            retryable=(redis.exceptions.ConnectionError, redis.exceptions.TimeoutError),
            policy=policy,
            on_retry=_on_retry,
        )
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        logger.warning(
            "cancel_check_redis_unavailable job_id=%s action=continue_processing",
            job_id,
        )
        return False


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def ensure_not_cancelled(job_id: str, r: redis.Redis | None = None):
    if is_cancelled(job_id, r=r):
        raise JobCancelledError(f"Job {job_id} cancelled by user")
