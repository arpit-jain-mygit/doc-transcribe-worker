import logging

from worker.transcribe import run_transcription

logger = logging.getLogger("worker.executors.transcription")


def execute_transcription(job_id: str, job: dict):
    logger.info("executor_start executor=transcription job_id=%s request_id=%s", job_id, job.get("request_id") or "")
    return run_transcription(job_id, job)
