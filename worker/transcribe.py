# -*- coding: utf-8 -*-
"""
Audio / Video Transcription Engine
Callable worker module (Vertex AI Gemini – billing-backed)
FILE-BASED TRANSCRIPTION (GCS → local file)
"""

import os
import sys
import re
import unicodedata
import time
from datetime import datetime
from typing import Dict, List

import redis
from dotenv import load_dotenv
from pydub import AudioSegment

from google.cloud import aiplatform
from vertexai.preview.generative_models import (
    GenerativeModel,
    Part,
)

from worker.utils.gcs import upload_text, append_log

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
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash"

TRANSCRIPTS_DIR = "/tmp/transcripts"
CHUNK_DURATION_SEC = 5 * 60  # 5 minutes

os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

PROMPT_FILE = os.environ.get("PROMPT_FILE")
PROMPT_NAME = os.environ.get("PROMPT_NAME")

REDIS_URL = os.environ.get("REDIS_URL")

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")
if not PROMPT_FILE or not PROMPT_NAME:
    raise RuntimeError("PROMPT_FILE or PROMPT_NAME not set")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL not set")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# =========================================================
# REDIS PROGRESS
# =========================================================
def update_progress(job_id: str, *, stage: str, progress: int, eta_sec: int = 0):
    redis_client.hset(
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
# INIT VERTEX AI
# =========================================================
aiplatform.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel(MODEL_NAME)

# =========================================================
# LOGGING
# =========================================================
def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str):
    print(f"[TRANSCRIBE {ts()}] {msg}", flush=True)

# =========================================================
# PROMPT LOADER
# =========================================================
def load_named_prompt(prompt_file: str, prompt_name: str) -> str:
    log(f"Loading prompt '{prompt_name}'")

    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()

    start = f"### PROMPT: {prompt_name}"
    end = "=== END PROMPT ==="

    if start not in content:
        raise RuntimeError(f"Prompt '{prompt_name}' not found")

    prompt = content.split(start, 1)[1].split(end, 1)[0].strip()
    if not prompt:
        raise RuntimeError("Prompt is empty")

    return prompt

AUDIO_PROMPT = load_named_prompt(PROMPT_FILE, PROMPT_NAME)

# =========================================================
# UTIL
# =========================================================
def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:max_len]

def split_audio_into_chunks(mp3_path: str) -> List[str]:
    audio = AudioSegment.from_file(mp3_path)
    chunk_ms = CHUNK_DURATION_SEC * 1000

    chunks = []
    for i, start in enumerate(range(0, len(audio), chunk_ms), start=1):
        chunk = audio[start:start + chunk_ms]
        out = mp3_path.replace(".", f"_chunk_{i}.")
        chunk.export(out, format="mp3")
        chunks.append(out)

    return chunks

def transcribe_audio(mp3_path: str) -> str:
    log(f"Gemini transcription: {os.path.basename(mp3_path)}")

    with open(mp3_path, "rb") as f:
        audio_bytes = f.read()

    response = model.generate_content(
        [
            Part.from_text(AUDIO_PROMPT),
            Part.from_data(audio_bytes, mime_type="audio/mpeg"),
        ],
        generation_config={
            "temperature": 0,
            "max_output_tokens": 8192,
        },
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty transcription output")

    return text

# =========================================================
# WORKER ENTRYPOINT (FILE MODE)
# =========================================================
def run_audio_transcription(job: Dict) -> Dict:
    job_id = job["job_id"]
    mp3_path = job["local_path"]

    log(f"Starting transcription job_id={job_id}")
    update_progress(job_id, stage="Preparing audio", progress=5, eta_sec=120)

    chunks = split_audio_into_chunks(mp3_path)
    total_chunks = len(chunks)

    redis_client.hset(
        f"job_status:{job_id}",
        mapping={"current_page": 0, "total_pages": total_chunks},
    )

    texts: List[str] = []
    start = time.perf_counter()

    for idx, chunk in enumerate(chunks, start=1):
        update_progress(
            job_id,
            stage=f"Transcribing chunk {idx}/{total_chunks}",
            progress=int((idx / total_chunks) * 80),
        )

        text = transcribe_audio(chunk)
        texts.append(text)

        elapsed = time.perf_counter() - start
        avg = elapsed / idx
        eta = int(avg * (total_chunks - idx))

        redis_client.hset(
            f"job_status:{job_id}",
            mapping={
                "current_page": idx,
                "eta_sec": eta,
            },
        )

    update_progress(job_id, stage="Finalizing transcript", progress=90)

    final_text = "\n\n".join(texts)

    base = sanitize_filename(os.path.basename(mp3_path))
    out_path = os.path.join(TRANSCRIPTS_DIR, f"{base}.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_text)

    append_log(job_id, "Uploading transcript to GCS")

    gcs_out = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/transcript.txt",
    )

    redis_client.hset(
        f"job_status:{job_id}",
        mapping={
            "status": "COMPLETED",
            "progress": 100,
            "output_uri": gcs_out["gcs_uri"],
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    log(f"Job completed job_id={job_id}")

    return {
        "job_id": job_id,
        "status": "COMPLETED",
        "output_path": gcs_out["gcs_uri"],
    }
