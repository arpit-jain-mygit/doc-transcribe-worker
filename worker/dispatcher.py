import logging

from worker.utils.gcs import download_from_gcs
from worker.transcribe import transcribe_file
from worker.ocr import ocr_pdf

logger = logging.getLogger(__name__)

def dispatch(job: dict):
    job_id = job["job_id"]

    logger.info(f"Incoming job received: job_id={job_id}")
    logger.info(f"Job payload: {job}")

    try:
        logger.info(f"Downloading input from GCS: job_id={job_id}")
        local_path = download_from_gcs(job["gcs_uri"])

        logger.info(
            f"Download complete: job_id={job_id}, local_path={local_path}"
        )

        filename = job["filename"].lower()

        if filename.endswith(".pdf"):
            logger.info(f"Routing to OCR pipeline: job_id={job_id}")
            ocr_pdf(local_path, job)

        elif filename.endswith((".mp3", ".wav", ".m4a", ".mp4", ".mov")):
            logger.info(f"Routing to transcription pipeline: job_id={job_id}")
            transcribe_file(local_path, job)

        else:
            raise ValueError(f"Unsupported file type: {filename}")

        logger.info(f"Job completed successfully: job_id={job_id}")

    except Exception:
        logger.exception(f"Job execution failed: job_id={job_id}")
        raise
