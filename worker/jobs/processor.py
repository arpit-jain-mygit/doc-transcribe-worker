# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
# worker/jobs/processor.py

from worker.orchestrator.router import execute_job


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def process_job(job_id: str, job: dict):
    return execute_job(job_id, job)
