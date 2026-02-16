import logging
import os
from typing import List

logger = logging.getLogger("worker.startup")


def _is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _validate_redis_url(value: str | None, key: str, errors: List[str]) -> None:
    if _is_blank(value):
        errors.append(f"{key} is required")
        return
    if not (value.startswith("redis://") or value.startswith("rediss://")):
        errors.append(f"{key} must start with redis:// or rediss://")


def _require_keys(keys: List[str], errors: List[str]) -> None:
    for key in keys:
        if _is_blank(os.getenv(key)):
            errors.append(f"{key} is required")


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

    queue_mode = (os.getenv("QUEUE_MODE", "single") or "single").strip().lower()
    if queue_mode not in {"single", "both"}:
        errors.append("QUEUE_MODE must be either 'single' or 'both'")
    elif queue_mode == "single":
        _require_keys(["QUEUE_NAME", "DLQ_NAME"], errors)
    else:
        _require_keys(
            ["LOCAL_QUEUE_NAME", "LOCAL_DLQ_NAME", "CLOUD_QUEUE_NAME", "CLOUD_DLQ_NAME"],
            errors,
        )

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
