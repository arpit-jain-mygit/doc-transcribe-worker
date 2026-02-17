# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
from worker.orchestrator.router import execute_job


# User value: routes work so user OCR/transcription jobs are processed correctly.
def dispatch(job: dict):
    job_id = job.get("job_id")
    if not job_id:
        raise ValueError("job_id missing in payload")

    return execute_job(job_id, job)
