# -*- coding: utf-8 -*-
"""
PDF → Text OCR Engine
Callable worker module (local-first, Gemini OCR)
"""

import os
import sys
import time
import io
from datetime import datetime
from typing import Dict

import redis
from pdf2image import convert_from_path
from PIL import Image

from google.cloud import aiplatform
from vertexai.preview.generative_models import (
    GenerativeModel,
    Part,
    Image as VertexImage,
)
from worker.utils.gcs import upload_text, append_log

# =========================================================
# UTF-8 SAFE OUTPUT
# =========================================================
sys.stdout.reconfigure(encoding="utf-8")

# =========================================================
# CONFIG
# =========================================================
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash"

REDIS_URL = os.environ.get("REDIS_URL")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

DPI = 300
OUTPUT_DIR = "/tmp/output_texts"

PROMPT_TEMPLATE = """
Role: You are an expert Indic-language archivist.

Task:
Transcribe every visible word from the attached page image with 100% accuracy.

Rules (STRICT):
1. Do NOT translate or summarize.
2. Preserve all scripts and symbols exactly.
3. Maintain line breaks and spacing.
4. Begin output with: "=== Page {page} ==="
5. Output ONLY verbatim transcription.
"""

# =========================================================
# INIT VERTEX AI
# =========================================================
aiplatform.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel(MODEL_NAME)

# =========================================================
# LOGGING
# =========================================================
def log(msg: str):
    print(f"[OCR {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# =========================================================
# UTIL
# =========================================================
def pil_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

# =========================================================
# GEMINI OCR CALL
# =========================================================
def gemini_ocr(prompt: str, image: Image.Image, page_num: int):
    png_bytes = pil_to_png_bytes(image)
    vertex_image = VertexImage.from_bytes(png_bytes)

    start = time.perf_counter()
    response = model.generate_content(
        [
            Part.from_text(prompt),
            Part.from_image(vertex_image),
        ],
        generation_config={
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 8192,
        },
    )

    log(f"Page {page_num}: Gemini completed in {time.perf_counter() - start:.2f}s")
    return response

# =========================================================
# WORKER ENTRYPOINT
# =========================================================
def run_pdf_ocr(job: Dict) -> Dict:
    job_id = job["job_id"]
    pdf_path = job["local_path"]

    start_time = time.perf_counter()

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(
        OUTPUT_DIR, f"{os.path.splitext(os.path.basename(pdf_path))[0]}.txt"
    )

    pages = convert_from_path(pdf_path, dpi=DPI)
    total_pages = len(pages)

    # -----------------------------------------------------
    # Resume support
    # -----------------------------------------------------
    last_done = int(
        redis_client.hget(f"job_status:{job_id}", "current_page") or 0
    )
    log(f"Resuming from page {last_done + 1} / {total_pages}")

    with open(out_path, "a", encoding="utf-8") as out:
        for idx, page in enumerate(pages, start=1):

            if idx <= last_done:
                continue

            # -------------------------------------------------
            # Cancel support
            # -------------------------------------------------
            if redis_client.hget(f"job_status:{job_id}", "cancelled") == "true":
                redis_client.hset(
                    f"job_status:{job_id}",
                    mapping={
                        "status": "CANCELLED",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                log("Job cancelled by user")
                return {"status": "CANCELLED"}

            for retry in range(5):
                try:
                    response = gemini_ocr(
                        PROMPT_TEMPLATE.format(page=idx), page, idx
                    )
                    break
                except Exception as e:
                    if "429" in str(e):
                        wait = 30 * (retry + 1)
                        log(f"Rate limited (429). Sleeping {wait}s before retrying page {idx}")
                        time.sleep(wait)
                        continue
                    raise
            else:
                raise RuntimeError("Exceeded OCR retry attempts for page")

            text = (response.text or "").strip()

            if not text:
                raise RuntimeError(f"Empty OCR output page {idx}")

            out.write(f"=== Page {idx} ===\n{text}\n\n")

            elapsed = time.perf_counter() - start_time
            avg_page_sec = elapsed / idx
            eta_sec = int(avg_page_sec * (total_pages - idx))

            # -------------------------------------------------
            # Live progress + ETA
            # -------------------------------------------------
            redis_client.hset(
                f"job_status:{job_id}",
                mapping={
                    "status": "PROCESSING",
                    "current_page": idx,
                    "total_pages": total_pages,
                    "avg_page_sec": round(avg_page_sec, 2),
                    "eta_sec": eta_sec,
                    "output_path": out_path,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
    append_log(job_id, "Uploading OCR output to GCS")

    gcs_base = f"jobs/{job_id}"

    with open(out_path, "r", encoding="utf-8") as f:
        gcs_out = upload_text(
            content=f.read(),
            destination_path=f"{gcs_base}/ocr.txt",
        )

    redis_client.hset(
        f"job_status:{job_id}",
        mapping={
            "status": "COMPLETED",
            "output_path": gcs_out["gcs_uri"],
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    return {
        "status": "COMPLETED",
        "output_path": gcs_out["gcs_uri"]
    }
