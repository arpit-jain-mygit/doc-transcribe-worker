# worker/processor.py

from worker.ocr import run_ocr
from worker.transcribe import run_transcription
from worker.youtube_ingest import process_youtube_job


def process_job(job_id: str, job: dict):
    source = (job.get("source") or "").lower()
    job_type = (job.get("job_type") or job.get("type") or "").upper()

    if source == "youtube":
        return process_youtube_job(job_id, job)

    if job_type == "OCR":
        return run_ocr(job_id, job)

    return run_transcription(job_id, job)
