# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
from worker.orchestrator.router import execute_job


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def dispatch(job: dict):
    job_id = job.get("job_id")
    if not job_id:
        raise ValueError("job_id missing in payload")

    return execute_job(job_id, job)
