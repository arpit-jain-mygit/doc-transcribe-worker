# worker/jobs/processor.py

from worker.orchestrator.router import execute_job


def process_job(job_id: str, job: dict):
    return execute_job(job_id, job)
