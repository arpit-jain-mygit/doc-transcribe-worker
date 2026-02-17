# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
from __future__ import annotations

import redis


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _is_gcs_connection_error(low: str) -> bool:
    connection_markers = (
        "remote end closed connection",
        "remotedisconnected",
        "connection aborted",
        "connection reset",
        "httpsconnectionpool",
        "sslerror",
    )
    gcs_markers = (
        "storage.googleapis.com",
        "googleapis.com/storage",
        "google.cloud.storage",
        "gcs",
        "signed_url",
        "upload",
        "download",
        "blob",
    )
    has_connection_issue = any(m in low for m in connection_markers)
    has_gcs_context = any(m in low for m in gcs_markers)
    return has_connection_issue and has_gcs_context


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def classify_error(exc: Exception) -> tuple[str, str]:
    text = f"{exc}".strip()
    low = text.lower()

    if _is_gcs_connection_error(low):
        return ("INFRA_GCS", "Storage service connection issue while uploading output. Please retry.")

    if "resource exhausted" in low or "429" in low or "quota" in low:
        return ("RATE_LIMIT_EXCEEDED", "Service is busy right now. Please retry shortly.")
    if "ffmpeg" in low or "decoding failed" in low or "could not decode" in low:
        return ("MEDIA_DECODE_FAILED", "Input media could not be decoded. Please upload a supported file.")
    if isinstance(exc, FileNotFoundError) or "no such file" in low:
        return ("INPUT_NOT_FOUND", "Input file was not found for processing.")
    if (
        isinstance(exc, redis.exceptions.ConnectionError)
        or "redis" in low
        or "connection closed" in low
        or "closed by server" in low
        or "timeout" in low
    ):
        return ("INFRA_REDIS", "Queue/storage connection issue while processing.")
    return ("PROCESSING_FAILED", "Processing failed due to an internal error.")
