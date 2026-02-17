# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
from __future__ import annotations

import os
from datetime import datetime, timezone


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _to_int(value, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _input_type_from_job(job: dict) -> str:
    filename = str(job.get("filename") or "").lower()
    if filename.endswith(".pdf"):
        return "PDF"
    if filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        return "IMAGE"
    if filename.endswith((".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma")):
        return "AUDIO"
    if filename.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")):
        return "VIDEO"
    source = str(job.get("source") or "").lower()
    if source == "ocr":
        return "PDF"
    if source in {"transcription", "av", "audio", "video"}:
        return "AUDIO"
    return "UNKNOWN"


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _error_type_from_code(error_code: str) -> str:
    code = (error_code or "").upper()
    if code.startswith("INPUT_") or code.startswith("VALIDATION_"):
        return "VALIDATION"
    if code.startswith("MEDIA_") or code.startswith("MODEL_"):
        return "MODEL"
    if code.startswith("INFRA_") or code.startswith("PROCESSING_") or code.startswith("RATE_"):
        return "SYSTEM"
    if code.startswith("IO_"):
        return "IO"
    return "SYSTEM"


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def build_dead_letter_entry(
    *,
    job: dict,
    queue_name: str,
    dlq_name: str,
    source_label: str,
    error_code: str,
    error_message: str,
    error_detail: str,
    failed_stage: str,
    worker_id: str,
) -> dict:
    attempts = _to_int(job.get("attempts") or job.get("attempt"), 1)
    max_attempts = _to_int(job.get("max_attempts"), _to_int(os.getenv("WORKER_MAX_ATTEMPTS"), 1))

    return {
        "schema_version": "v1",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAILED",
        "job_id": str(job.get("job_id") or ""),
        "request_id": str(job.get("request_id") or ""),
        "job_type": str(job.get("job_type") or job.get("type") or ""),
        "input_type": _input_type_from_job(job),
        "queue_name": queue_name,
        "dlq_name": dlq_name,
        "queue_source": source_label,
        "failed_stage": failed_stage or "Processing failed",
        "error_code": error_code,
        "error_type": _error_type_from_code(error_code),
        "error": error_message,
        "error_detail": error_detail,
        "attempts": max(1, attempts),
        "max_attempts": max(1, max_attempts),
        "worker_id": worker_id,
        "payload": job,
    }
