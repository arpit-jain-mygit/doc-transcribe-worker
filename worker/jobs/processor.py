# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
# worker/jobs/processor.py

from worker.orchestrator.router import execute_job


# User value: supports process_job so the OCR/transcription journey stays clear and reliable.
def process_job(job_id: str, job: dict):
    return execute_job(job_id, job)
