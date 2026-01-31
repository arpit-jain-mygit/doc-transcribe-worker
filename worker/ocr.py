# -*- coding: utf-8 -*-
"""
REAL PDF OCR (Gemini Vision OCR)
Drop-in replacement for pytesseract-based ocr.py
"""

import os
import sys
import time
import io
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
OUTPUT_DIR = "output_texts"

os.makedirs(OUTPUT_DIR, exist_ok=True)

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
def log(msg: str):
    print(f"[OCR {datetime.utcnow().isoformat()}] {msg}", flush=True)

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


def update(job_id: str, *, stage: str, progress: int, eta_sec: int = 0):
    r.hset(
        f"job_status:{job_id}",
        mapping={
            "status": "PROCESSING",
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
def run_ocr(job_id: str, job: dict) -> str:
    input_path = job["input_path"]

    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    log(f"Starting OCR job_id={job_id}")
    update(job_id, stage="Loading PDF", progress=5, eta_sec=120)

    pages = convert_from_path(input_path, dpi=DPI)
    total_pages = len(pages)

    log(f"PDF pages detected: {total_pages}")

    texts: List[str] = []
    start = time.perf_counter()

    for idx, page in enumerate(pages, start=1):
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

        r.hset(
            f"job_status:{job_id}",
            mapping={
                "current_page": idx,
                "total_pages": total_pages,
                "eta_sec": eta,
            },
        )

    update(job_id, stage="Finalizing OCR", progress=95)

    out_path = os.path.join(OUTPUT_DIR, f"{job_id}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(texts))

    log(f"OCR completed → {out_path}")
    return out_path
