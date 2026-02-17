from worker.orchestrator.router import execute_job


def dispatch(job: dict):
    job_id = job.get("job_id")
    if not job_id:
        raise ValueError("job_id missing in payload")

    return execute_job(job_id, job)
