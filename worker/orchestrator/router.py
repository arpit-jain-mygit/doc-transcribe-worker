import logging
import os

from worker.executors.ocr_executor import execute_ocr
from worker.executors.transcription_executor import execute_transcription

logger = logging.getLogger("worker.orchestrator.router")

OCR_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def looks_like_ocr_input(job: dict) -> bool:
    filename = (job.get("filename") or "").strip()
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in OCR_EXTS


def resolve_executor(job: dict):
    source = (job.get("source") or "").lower()
    job_type = (job.get("job_type") or job.get("type") or "").upper()

    if source == "ocr" or job_type == "OCR" or looks_like_ocr_input(job):
        return "ocr", execute_ocr

    return "transcription", execute_transcription


def execute_job(job_id: str, job: dict):
    route, executor = resolve_executor(job)
    logger.info(
        "orchestrator_route_selected route=%s job_id=%s request_id=%s source=%s job_type=%s",
        route,
        job_id,
        job.get("request_id") or "",
        job.get("source") or "",
        job.get("job_type") or job.get("type") or "",
    )
    return executor(job_id, job)
