# worker/processor.py

import os

from worker.ocr import run_ocr
from worker.transcribe import run_transcription
from worker.youtube_ingest import process_youtube_job

OCR_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _looks_like_ocr_input(job: dict) -> bool:
    filename = (job.get("filename") or "").strip()
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in OCR_EXTS


def process_job(job_id: str, job: dict):
    source = (job.get("source") or "").lower()
    job_type = (job.get("job_type") or job.get("type") or "").upper()

    if source == "youtube":
        return process_youtube_job(job_id, job)

    # Robust OCR routing even if upstream payload is inconsistent.
    if source == "ocr" or job_type == "OCR" or _looks_like_ocr_input(job):
        return run_ocr(job_id, job)

    return run_transcription(job_id, job)
