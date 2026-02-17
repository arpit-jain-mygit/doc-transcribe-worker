import logging

from worker.ocr import run_ocr

logger = logging.getLogger("worker.executors.ocr")


def execute_ocr(job_id: str, job: dict):
    logger.info("executor_start executor=ocr job_id=%s request_id=%s", job_id, job.get("request_id") or "")
    return run_ocr(job_id, job)
