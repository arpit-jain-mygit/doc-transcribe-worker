# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging
import os
from typing import List

logger = logging.getLogger("worker.startup")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _validate_redis_url(value: str | None, key: str, errors: List[str]) -> None:
    if _is_blank(value):
        errors.append(f"{key} is required")
        return
    if not (value.startswith("redis://") or value.startswith("rediss://")):
        errors.append(f"{key} must start with redis:// or rediss://")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _require_keys(keys: List[str], errors: List[str]) -> None:
    for key in keys:
        if _is_blank(os.getenv(key)):
            errors.append(f"{key} is required")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _validate_int_range(
    key: str,
    errors: List[str],
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    allow_blank: bool = True,
) -> None:
    raw = os.getenv(key)
    if _is_blank(raw):
        if allow_blank:
            return
        errors.append(f"{key} is required")
        return

    try:
        value = int(str(raw).strip())
    except Exception:
        errors.append(f"{key} must be an integer")
        return

    if min_value is not None and value < min_value:
        errors.append(f"{key} must be >= {min_value}")
    if max_value is not None and value > max_value:
        errors.append(f"{key} must be <= {max_value}")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def validate_startup_env() -> None:
    errors: List[str] = []
    warnings: List[str] = []

    _require_keys(
        [
            "GCP_PROJECT_ID",
            "GCS_BUCKET_NAME",
            "PROMPT_FILE",
            "PROMPT_NAME",
        ],
        errors,
    )
    _validate_redis_url(os.getenv("REDIS_URL"), "REDIS_URL", errors)

    _validate_int_range("TRANSCRIBE_CHUNK_DURATION_SEC", errors, min_value=30, max_value=3600)
    _validate_int_range("OCR_DPI", errors, min_value=72, max_value=600)
    _validate_int_range("OCR_PAGE_BATCH_SIZE", errors, min_value=0, max_value=500)

    queue_mode = (os.getenv("QUEUE_MODE", "single") or "single").strip().lower()
    if queue_mode not in {"single", "both", "partitioned"}:
        errors.append("QUEUE_MODE must be one of 'single', 'both', 'partitioned'")
    elif queue_mode == "single":
        _require_keys(["QUEUE_NAME", "DLQ_NAME"], errors)
    elif queue_mode == "both":
        _require_keys(
            ["LOCAL_QUEUE_NAME", "LOCAL_DLQ_NAME", "CLOUD_QUEUE_NAME", "CLOUD_DLQ_NAME"],
            errors,
        )
    else:
        _require_keys(
            ["OCR_QUEUE_NAME", "OCR_DLQ_NAME", "TRANSCRIPTION_QUEUE_NAME", "TRANSCRIPTION_DLQ_NAME"],
            errors,
        )

    _validate_int_range("WORKER_MAX_INFLIGHT_OCR", errors, min_value=0, max_value=100)
    _validate_int_range("WORKER_MAX_INFLIGHT_TRANSCRIPTION", errors, min_value=0, max_value=100)
    _validate_int_range("RETRY_BUDGET_TRANSIENT", errors, min_value=0, max_value=10)
    _validate_int_range("RETRY_BUDGET_MEDIA", errors, min_value=0, max_value=10)
    _validate_int_range("RETRY_BUDGET_DEFAULT", errors, min_value=0, max_value=10)

    if _is_blank(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")):
        warnings.append(
            "GOOGLE_APPLICATION_CREDENTIALS_JSON is not set; relying on ambient ADC credentials"
        )

    if errors:
        for err in errors:
            logger.error("startup_env_invalid %s", err)
        raise RuntimeError("Startup env validation failed: " + "; ".join(errors))

    for warning in warnings:
        logger.warning("startup_env_warning %s", warning)

    logger.info(
        "startup_env_validated queue_mode=%s keys=%s",
        queue_mode,
        ["REDIS_URL", "GCP_PROJECT_ID", "GCS_BUCKET_NAME", "PROMPT_FILE", "PROMPT_NAME"],
    )
