# worker/processor.py

from worker.transcribe import run_transcription
from worker.youtube_ingest import process_youtube_job


def process_job(job_id: str, job: dict):
    source = job.get("source")

    if source == "youtube":
        return process_youtube_job(job_id, job)

    return run_transcription(job_id, job)

