# -*- coding: utf-8 -*-
"""
REAL PDF OCR (Gemini Vision OCR)
Drop-in replacement for pytesseract-based ocr.py
"""

import io
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from typing import List

import redis
from dotenv import load_dotenv
from pdf2image import convert_from_path
from PIL import Image

from google.cloud import aiplatform
from vertexai.preview.generative_models import (
    GenerativeModel,
    Part,
    Image as VertexImage,
)

from worker.cancel import ensure_not_cancelled
from worker.contract import CONTRACT_VERSION
from worker.utils.gcs import download_from_gcs, upload_text

# =========================================================
# UTF-8 SAFE OUTPUT
# =========================================================
sys.stdout.reconfigure(encoding="utf-8")

# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

# =========================================================
# CONFIG
# =========================================================
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash"

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DPI = 300

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")

# =========================================================
# REDIS
# =========================================================
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# =========================================================
# INIT VERTEX AI
# =========================================================
aiplatform.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel(MODEL_NAME)

# =========================================================
# LOGGING
# =========================================================
logger = logging.getLogger("worker.ocr")


def log(msg: str):
    logger.info("[OCR %s] %s", datetime.utcnow().isoformat(), msg)

# =========================================================
# PROMPT
# =========================================================
PROMPT_TEMPLATE = """
Role: You are an expert OCR engine.

Task:
Transcribe every visible word from the attached page image with 100% accuracy.

Rules (STRICT):
1. Do NOT translate or summarize.
2. Preserve all scripts, symbols, punctuation exactly.
3. Maintain original line breaks and spacing.
4. Begin output with: "=== Page {page} ==="
5. Output ONLY verbatim transcription.
"""

# =========================================================
# UTILS
# =========================================================
def pil_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    if not name:
        name = "transcript"
    return name[:max_len]


def normalize_output_filename(raw_name: str | None) -> str:
    stem, _ = os.path.splitext(raw_name or "transcript")
    return f"{sanitize_filename(stem)}.txt"




def safe_hset(key: str, mapping: dict, retries: int = 1):
    for attempt in range(retries + 1):
        try:
            rc = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_keepalive=True, socket_connect_timeout=2, socket_timeout=10, retry_on_timeout=True, health_check_interval=15)
            rc.hset(key, mapping=mapping)
            return
        except redis.exceptions.ConnectionError as exc:
            logger.warning("ocr_safe_hset_connection_error attempt=%s/%s error=%s", attempt + 1, retries + 1, exc)
            if attempt >= retries:
                raise
            time.sleep(0.15)

def update(job_id: str, *, stage: str, progress: int, status: str = "PROCESSING", eta_sec: int = 0):
    safe_hset(
        f"job_status:{job_id}",
        mapping={
            "contract_version": CONTRACT_VERSION,
            "status": status,
            "stage": stage,
            "progress": progress,
            "eta_sec": eta_sec,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

# =========================================================
# GEMINI OCR
# =========================================================
def gemini_ocr(image: Image.Image, page_num: int) -> str:
    png_bytes = pil_to_png_bytes(image)
    vertex_image = VertexImage.from_bytes(png_bytes)

    log(f"Starting Gemini OCR for page {page_num}")
    t0 = time.perf_counter()

    response = model.generate_content(
        [
            Part.from_text(PROMPT_TEMPLATE.format(page=page_num)),
            Part.from_image(vertex_image),
        ],
        generation_config={
            "temperature": 0,
            "max_output_tokens": 8192,
        },
    )

    dt = round(time.perf_counter() - t0, 2)
    log(f"Gemini OCR completed page {page_num} in {dt}s")

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError(f"Empty OCR output page {page_num}")

    return text

# =========================================================
# WORKER ENTRYPOINT
# =========================================================
def run_ocr(job_id: str, job: dict) -> dict:
    ensure_not_cancelled(job_id, r=r)
    input_path = job.get("input_path")
    if not input_path:
        input_gcs_uri = job.get("input_gcs_uri")
        if not input_gcs_uri:
            raise RuntimeError("input_path or input_gcs_uri missing in OCR job")
        input_path = download_from_gcs(input_gcs_uri)

    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    log(f"Starting OCR job_id={job_id}")
    ensure_not_cancelled(job_id, r=r)
    update(job_id, stage="Loading PDF", progress=5, eta_sec=120)

    pages = convert_from_path(input_path, dpi=DPI)
    total_pages = len(pages)

    log(f"PDF pages detected: {total_pages}")

    texts: List[str] = []
    start = time.perf_counter()

    for idx, page in enumerate(pages, start=1):
        ensure_not_cancelled(job_id, r=r)
        update(
            job_id,
            stage=f"OCR page {idx}/{total_pages}",
            progress=10 + int((idx / total_pages) * 80),
        )

        text = gemini_ocr(page, idx)
        texts.append(text)

        elapsed = time.perf_counter() - start
        avg = elapsed / idx
        eta = int(avg * (total_pages - idx))

        safe_hset(
            f"job_status:{job_id}",
            {
                "current_page": idx,
                "total_pages": total_pages,
                "eta_sec": eta,
            },
        )

    ensure_not_cancelled(job_id, r=r)
    update(job_id, stage="Finalizing OCR", progress=95)

    final_text = "\n\n".join(texts)
    output_filename = normalize_output_filename(job.get("output_filename") or job.get("filename"))

    uploaded = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/{output_filename}",
    )

    safe_hset(
        f"job_status:{job_id}",
        {
            "contract_version": CONTRACT_VERSION,
            "status": "COMPLETED",
            "stage": "Completed",
            "progress": 100,
            "output_path": uploaded["gcs_uri"],
            "output_filename": output_filename,
            "error_code": "",
            "error_message": "",
            "error_detail": "",
            "error": "",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    log(f"OCR completed -> {uploaded['gcs_uri']}")
    return {
        "gcs_uri": uploaded["gcs_uri"],
        "output_filename": output_filename,
        "status": "COMPLETED",
    }
