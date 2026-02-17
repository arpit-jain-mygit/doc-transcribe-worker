# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging

from worker.transcribe import run_transcription

logger = logging.getLogger("worker.executors.transcription")


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def execute_transcription(job_id: str, job: dict):
    logger.info("executor_start executor=transcription job_id=%s request_id=%s", job_id, job.get("request_id") or "")
    return run_transcription(job_id, job)
