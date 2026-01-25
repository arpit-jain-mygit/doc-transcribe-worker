# -*- coding: utf-8 -*-
"""
Job Dispatcher for doc-transcribe-worker

Responsible for:
- validating job payloads
- routing jobs to the correct execution pipeline
- returning normalized results

NO execution logic lives here.
"""

from typing import Dict
from datetime import datetime

from worker.transcribe import run_audio_transcription
from worker.ocr import run_pdf_ocr


# =========================================================
# Logging helpers (dispatcher-level)
# =========================================================
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[DISPATCHER {ts}] {msg}", flush=True)


def log_ok(msg: str):
    log(f"✅ {msg}")


def log_err(msg: str):
    log(f"❌ {msg}")


# =========================================================
# Exceptions
# =========================================================
class UnsupportedJobError(Exception):
    pass


# =========================================================
# Dispatcher
# =========================================================
def dispatch(job: Dict) -> Dict:
    """
    Dispatch a job to the appropriate pipeline.

    Expected job schema (minimum):

    {
        "job_id": "uuid",
        "job_type": "TRANSCRIPTION" | "OCR",
        "input_type": "VIDEO" | "AUDIO" | "PDF",
        ...
    }
    """

    log("Incoming job received")
    log(f"Raw job payload: {job}")

    validate_job(job)

    job_id = job.get("job_id", "unknown")
    job_type = job["job_type"].upper()
    input_type = job["input_type"].upper()

    log(f"Job ID: {job_id}")
    log(f"Job type: {job_type}, Input type: {input_type}")

    try:
        if job_type == "TRANSCRIPTION":
            if input_type in ("VIDEO", "AUDIO"):
                log("Routing to audio/video transcription pipeline")
                result = run_audio_transcription(job)
                log_ok("Transcription pipeline completed")
                return result

            raise UnsupportedJobError(
                f"TRANSCRIPTION does not support input_type={input_type}"
            )

        if job_type == "OCR":
            if input_type == "PDF":
                log("Routing to PDF OCR pipeline")
                result = run_pdf_ocr(job)
                log_ok("OCR pipeline completed")
                return result

            raise UnsupportedJobError(
                f"OCR does not support input_type={input_type}"
            )

        raise UnsupportedJobError(f"Unsupported job_type={job_type}")

    except Exception as e:
        log_err(f"Dispatcher failed for job_id={job_id}: {e}")
        raise


# =========================================================
# Validation
# =========================================================
# =========================================================
# Schema Validation
# =========================================================
def validate_job(job: Dict):
    log("Validating job schema")

    if not isinstance(job, dict):
        raise ValueError("Job must be a dictionary")

    # ---- Common fields ----
    required_common = ["job_type", "input_type"]
    for field in required_common:
        if field not in job:
            raise ValueError(f"Missing required field: {field}")

    job_type = job["job_type"].upper()
    input_type = job["input_type"].upper()

    # ---- OCR Job ----
    if job_type == "OCR":
        if input_type != "PDF":
            raise ValueError("OCR jobs require input_type=PDF")

        if "local_path" not in job:
            raise ValueError("OCR jobs require 'local_path'")

        if not isinstance(job["local_path"], str):
            raise ValueError("'local_path' must be a string")

    # ---- Transcription Job ----
    elif job_type == "TRANSCRIPTION":
        if input_type not in ("VIDEO", "AUDIO"):
            raise ValueError(
                "TRANSCRIPTION jobs require input_type=VIDEO or AUDIO"
            )

        if "url" not in job:
            raise ValueError("TRANSCRIPTION jobs require 'url'")

        if not isinstance(job["url"], str):
            raise ValueError("'url' must be a string")

    else:
        raise ValueError(f"Unsupported job_type: {job_type}")

    log_ok("Job schema validation passed")
