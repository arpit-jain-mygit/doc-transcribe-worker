# worker/utils/gcs.py
# -*- coding: utf-8 -*-

import os
import json
import base64
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
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(days=expires_days),
        method="GET",
    )


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

    blob.upload_from_string(
        content,
        content_type=content_type,
    )

    signed_url = _signed_url(blob)

    return {
        "gcs_uri": f"gs://{GCS_BUCKET}/{destination_path}",
        "signed_url": signed_url,          # ✅ ADDITION
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

    blob.upload_from_filename(local_path)

    signed_url = _signed_url(blob)

    return {
        "gcs_uri": f"gs://{GCS_BUCKET}/{destination_path}",
        "signed_url": signed_url,          # ✅ ADDITION
        "bucket": GCS_BUCKET,
        "blob": destination_path,
    }


# ---------------------------------------------------------
# APPEND WORKER LOG
# ---------------------------------------------------------
def append_log(job_id: str, message: str):
    """
    Append a single line to jobs/<job_id>/logs/worker.log in GCS.
    Requires storage.objects.get + create permissions.
    """
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
client = storage.Client()

def download_from_gcs(gcs_uri: str) -> str:
    logger.info(f"GCS download started: gcs_uri={gcs_uri}")

    path = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = path.split("/", 1)

    local_path = f"/tmp/{os.path.basename(blob_path)}"
    client.bucket(bucket_name).blob(blob_path).download_to_filename(local_path)

    logger.info(f"GCS download completed: local_path={local_path}")
    return local_path
