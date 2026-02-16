# worker/utils/gcs.py
# -*- coding: utf-8 -*-

import os
import json
import base64
import time
from datetime import datetime, timedelta
from google.cloud import storage
import logging

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME")

if not GCS_BUCKET:
    raise RuntimeError("GCS_BUCKET_NAME env var not set")

_client = None
logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%s, using default=%s", name, raw, default)
        return default
    return max(0, value)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%s, using default=%s", name, raw, default)
        return default
    return max(0.0, value)


GCS_RETRIES = _env_int("GCS_RETRIES", 3)
GCS_BACKOFF_SEC = _env_float("GCS_BACKOFF_SEC", 0.5)


def _retry_io(operation: str, target: str, fn):
    for attempt in range(GCS_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:
            logger.warning(
                "gcs_io_retry op=%s attempt=%s/%s target=%s error=%s",
                operation,
                attempt + 1,
                GCS_RETRIES + 1,
                target,
                exc,
            )
            if attempt >= GCS_RETRIES:
                raise
            time.sleep(GCS_BACKOFF_SEC * (2 ** attempt))


def _get_client():
    """
    Lazily initialize and cache GCS client.
    Supports base64-encoded service account JSON via
    GOOGLE_APPLICATION_CREDENTIALS_JSON.
    """
    global _client
    if _client is not None:
        return _client

    creds_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_b64:
        creds = json.loads(base64.b64decode(creds_b64))
        _client = storage.Client.from_service_account_info(creds)
    else:
        _client = storage.Client()

    return _client


# ---------------------------------------------------------
# INTERNAL: SIGNED URL
# ---------------------------------------------------------
def _signed_url(blob, expires_days: int = 7) -> str:
    """
    Generate browser-downloadable HTTPS URL.
    """
    return _retry_io(
        operation="signed_url",
        target=getattr(blob, "name", "unknown"),
        fn=lambda: blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=expires_days),
            method="GET",
        ),
    )


# ---------------------------------------------------------
# ✅ PUBLIC SIGNED URL (FIXES IMPORT ERROR)
# ---------------------------------------------------------
def generate_signed_url(
    bucket_name: str,
    blob_path: str,
    expires_days: int = 7,
) -> str:
    client = _get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    return _signed_url(blob, expires_days=expires_days)


# ---------------------------------------------------------
# UPLOAD TEXT
# ---------------------------------------------------------
def upload_text(
    *,
    content: str,
    destination_path: str,
    content_type: str = "text/plain; charset=utf-8",
) -> dict:
    client = _get_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(destination_path)

    # Prefix UTF-8 BOM so mobile viewers reliably detect Hindi text encoding.
    payload = content
    if isinstance(payload, str) and not payload.startswith("\ufeff"):
        payload = "\ufeff" + payload

    _retry_io(
        operation="upload_text",
        target=destination_path,
        fn=lambda: blob.upload_from_string(
            payload,
            content_type=content_type,
        ),
    )

    signed_url = _signed_url(blob)

    return {
        "gcs_uri": f"gs://{GCS_BUCKET}/{destination_path}",
        "signed_url": signed_url,
        "bucket": GCS_BUCKET,
        "blob": destination_path,
    }


# ---------------------------------------------------------
# UPLOAD FILE
# ---------------------------------------------------------
def upload_file(*, local_path: str, destination_path: str) -> dict:
    client = _get_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(destination_path)

    _retry_io(
        operation="upload_file",
        target=destination_path,
        fn=lambda: blob.upload_from_filename(local_path),
    )

    signed_url = _signed_url(blob)

    return {
        "gcs_uri": f"gs://{GCS_BUCKET}/{destination_path}",
        "signed_url": signed_url,
        "bucket": GCS_BUCKET,
        "blob": destination_path,
    }


# ---------------------------------------------------------
# APPEND WORKER LOG
# ---------------------------------------------------------
def append_log(job_id: str, message: str):
    ts = datetime.utcnow().isoformat() + "Z"
    path = f"jobs/{job_id}/logs/worker.log"

    client = _get_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(path)

    existing = ""
    if blob.exists():
        existing = blob.download_as_text(encoding="utf-8")

    blob.upload_from_string(
        existing + f"[{ts}] {message}\n",
        content_type="text/plain; charset=utf-8",
    )


# ---------------------------------------------------------
# DOWNLOAD FROM GCS (LOCAL)
# ---------------------------------------------------------
def download_from_gcs(gcs_uri: str) -> str:
    logger.info(f"GCS download started: gcs_uri={gcs_uri}")

    path = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = path.split("/", 1)

    local_path = f"/tmp/{os.path.basename(blob_path)}"
    client = _get_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    _retry_io(
        operation="download",
        target=gcs_uri,
        fn=lambda: blob.download_to_filename(local_path),
    )

    logger.info(f"GCS download completed: local_path={local_path}")
    return local_path
