# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

logger = logging.getLogger("worker.retry")


# User value: supports _env_int so the OCR/transcription journey stays clear and reliable.
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%s, using default=%s", name, raw, default)
        return default


# User value: supports _env_float so the OCR/transcription journey stays clear and reliable.
def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%s, using default=%s", name, raw, default)
        return default


@dataclass(frozen=True)
class RetryPolicy:
    name: str
    max_retries: int
    base_delay_sec: float
    max_delay_sec: float
    jitter_ratio: float = 0.2


DEFAULT_REDIS_RETRIES = _env_int("WORKER_REDIS_RETRIES", 2)
DEFAULT_REDIS_BACKOFF_SEC = _env_float("WORKER_REDIS_BACKOFF_SEC", 0.15)
DEFAULT_REDIS_MAX_BACKOFF_SEC = _env_float("WORKER_REDIS_MAX_BACKOFF_SEC", 2.0)

DEFAULT_GCS_RETRIES = _env_int("GCS_RETRIES", 3)
DEFAULT_GCS_BACKOFF_SEC = _env_float("GCS_BACKOFF_SEC", 0.5)
DEFAULT_GCS_MAX_BACKOFF_SEC = _env_float("GCS_MAX_BACKOFF_SEC", 5.0)


REDIS_POLICY = RetryPolicy(
    name="redis",
    max_retries=DEFAULT_REDIS_RETRIES,
    base_delay_sec=DEFAULT_REDIS_BACKOFF_SEC,
    max_delay_sec=DEFAULT_REDIS_MAX_BACKOFF_SEC,
    jitter_ratio=0.2,
)

GCS_POLICY = RetryPolicy(
    name="gcs",
    max_retries=DEFAULT_GCS_RETRIES,
    base_delay_sec=DEFAULT_GCS_BACKOFF_SEC,
    max_delay_sec=DEFAULT_GCS_MAX_BACKOFF_SEC,
    jitter_ratio=0.2,
)


# User value: supports _compute_delay so the OCR/transcription journey stays clear and reliable.
def _compute_delay(policy: RetryPolicy, attempt: int) -> float:
    # attempt starts at 1 for first retry delay
    exponential = policy.base_delay_sec * (2 ** max(0, attempt - 1))
    capped = min(exponential, policy.max_delay_sec)
    if policy.jitter_ratio <= 0:
        return capped
    jitter = capped * policy.jitter_ratio * random.random()
    return capped + jitter


# User value: improves reliability when OCR/transcription dependencies fail transiently.
def run_with_retry(
    *,
    operation: str,
    target: str,
    fn: Callable[[], T],
    retryable: Iterable[type[BaseException]],
    policy: RetryPolicy,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    retryable_tuple = tuple(retryable)
    attempt = 0
    while True:
        try:
            return fn()
        except retryable_tuple as exc:
            if attempt >= policy.max_retries:
                raise
            attempt += 1
            if on_retry:
                on_retry(attempt, exc)
            delay = _compute_delay(policy, attempt)
            logger.warning(
                "retry_scheduled policy=%s operation=%s target=%s attempt=%s/%s delay_sec=%.3f error=%s",
                policy.name,
                operation,
                target,
                attempt,
                policy.max_retries,
                delay,
                exc,
            )
            time.sleep(delay)
