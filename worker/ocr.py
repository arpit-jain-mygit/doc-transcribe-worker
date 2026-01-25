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
# CONFIG
# =========================================================
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash"

DPI = 300
OUTPUT_DIR = "output_texts"

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
# LOGGING HELPERS
# =========================================================
def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str):
    print(f"[OCR {ts()}] {msg}", flush=True)

def log_ok(msg: str):
    log(f"✅ {msg}")

def log_warn(msg: str):
    log(f"⚠️  {msg}")

def log_err(msg: str):
    log(f"❌ {msg}")

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
    log(f"Page {page_num}: Preparing image bytes")
    png_bytes = pil_to_png_bytes(image)

    log(f"Page {page_num}: Sending request to Gemini")
    start = time.perf_counter()

    vertex_image = VertexImage.from_bytes(png_bytes)
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

    log_ok(
        f"Page {page_num}: Gemini response received "
        f"({time.perf_counter() - start:.2f}s)"
    )

    return response

# =========================================================
# WORKER ENTRYPOINT
# =========================================================
def run_pdf_ocr(job: Dict) -> Dict:
    """
    job:
      {
        "input_type": "PDF",
        "local_path": "/path/to/file.pdf"
      }
    """

    pipeline_start = time.perf_counter()

    pdf_path = job["local_path"]
    pdf_name = os.path.basename(pdf_path)
    base = os.path.splitext(pdf_name)[0]

    log("============================================================")
    log(f"Starting OCR job for PDF: {pdf_name}")
    log(f"PDF path: {pdf_path}")
    log(f"DPI: {DPI}")
    log("============================================================")

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{base}.txt")

    # ---------------------------------------------------------
    # PDF → Images
    # ---------------------------------------------------------
    log("Converting PDF to images")
    start = time.perf_counter()
    pages = convert_from_path(pdf_path, dpi=DPI)
    log_ok(
        f"Converted PDF to {len(pages)} image(s) "
        f"({time.perf_counter() - start:.2f}s)"
    )

    # ---------------------------------------------------------
    # OCR each page
    # ---------------------------------------------------------
    with open(out_path, "w", encoding="utf-8") as out:
        for idx, page in enumerate(pages, start=1):
            log(f"Page {idx}/{len(pages)}: OCR started")

            prompt = PROMPT_TEMPLATE.format(page=idx)

            response = gemini_ocr(prompt, page, idx)
            text = (response.text or "").strip()

            if not text:
                log_err(f"Page {idx}: Empty OCR output")
                raise RuntimeError(f"Empty OCR output on page {idx}")

            out.write(f"=== Page {idx} ===\n")
            out.write(text.lstrip())
            out.write("\n\n")

            log_ok(f"Page {idx}: OCR text written")

    total_time = time.perf_counter() - pipeline_start

    log("============================================================")
    log_ok(f"OCR job completed successfully")
    log(f"Output file: {out_path}")
    log(f"Total pages: {len(pages)}")
    log(f"Total time: {total_time:.2f}s")
    log("============================================================")

    return {
        "status": "COMPLETED",
        "output_path": out_path,
        "pages": len(pages),
        "duration_sec": round(total_time, 2),
    }
