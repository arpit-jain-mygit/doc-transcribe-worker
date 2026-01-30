import logging

from worker.utils.gcs import download_from_gcs
from worker.ocr import run_pdf_ocr
from worker.transcribe import run_audio_transcription

logger = logging.getLogger(__name__)

def dispatch(job: dict, progress_cb=None) -> str:
    job_id = job["job_id"]

    logger.info(f"[DISPATCHER] Incoming job: {job_id}")
    logger.info(f"[DISPATCHER] Payload: {job}")

    try:
        logger.info(f"[DISPATCHER] Downloading input from GCS")
        local_path = download_from_gcs(job["gcs_uri"])

        logger.info(f"[DISPATCHER] Downloaded to {local_path}")

        # 🔑 Inject local path for pipelines
        job["local_path"] = local_path

        filename = job["filename"].lower()

        if filename.endswith(".pdf"):
            logger.info(f"[DISPATCHER] Routing to OCR pipeline")
            result = run_pdf_ocr(job)

            output_uri = result.get("output_path")

        elif filename.endswith((".mp3", ".wav", ".m4a", ".mp4", ".mov")):
            logger.info(f"[DISPATCHER] Routing to transcription pipeline")
            result = run_audio_transcription(job)

            output_uri = result.get("output_path")

        else:
            raise ValueError(f"Unsupported file type: {filename}")

        if not output_uri:
            raise RuntimeError("Pipeline did not return output_uri")

        logger.info(f"[DISPATCHER] Job completed: {job_id}")
        return output_uri

    except Exception:
        logger.exception(f"[DISPATCHER] Job failed: {job_id}")
        raise
