# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging

from worker.ocr import run_ocr

logger = logging.getLogger("worker.executors.ocr")


# User value: supports execute_ocr so the OCR/transcription journey stays clear and reliable.
def execute_ocr(job_id: str, job: dict):
    logger.info("executor_start executor=ocr job_id=%s request_id=%s", job_id, job.get("request_id") or "")
    return run_ocr(job_id, job)
