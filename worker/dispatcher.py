import logging

from worker.utils.gcs import download_from_gcs
from worker.transcribe import run_audio_transcription
from worker.ocr import run_pdf_ocr

logger = logging.getLogger(__name__)

def dispatch(job: dict):
    job_id = job["job_id"]

    logger.info(f"[DISPATCHER] Incoming job: {job_id}")
    logger.info(f"[DISPATCHER] Payload: {job}")

    try:
        # 1️⃣ Download input
        logger.info(f"[DISPATCHER] Downloading input from GCS")
        local_path = download_from_gcs(job["gcs_uri"])
        job["local_path"] = local_path

        logger.info(f"[DISPATCHER] Downloaded to {local_path}")

        filename = job["filename"].lower()

        # 2️⃣ Route
        if filename.endswith(".pdf"):
            logger.info(f"[DISPATCHER] Routing to OCR pipeline")
            result = run_pdf_ocr(job)

        elif filename.endswith((".mp3", ".wav", ".m4a", ".mp4", ".mov")):
            logger.info(f"[DISPATCHER] Routing to transcription pipeline")
            result = run_audio_transcription(job)

        else:
            raise ValueError(f"Unsupported file type: {filename}")

        logger.info(f"[DISPATCHER] Job completed: {job_id}")
        return result

    except Exception:
        logger.exception(f"[DISPATCHER] Job failed: {job_id}")
        raise
