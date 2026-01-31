# -*- coding: utf-8 -*-
"""
REAL AUDIO TRANSCRIPTION (Gemini ASR)
WITH VERBOSE LOGGING + GCS OUTPUT
"""

import os
import sys
import re
import time
import unicodedata
from datetime import datetime
from typing import List

import redis
from dotenv import load_dotenv
from pydub import AudioSegment

from google.cloud import aiplatform
from vertexai.preview.generative_models import GenerativeModel, Part

from worker.utils.gcs import upload_text

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

PROMPT_FILE = os.getenv("PROMPT_FILE")
PROMPT_NAME = os.getenv("PROMPT_NAME")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CHUNK_DURATION_SEC = 5 * 60
TRANSCRIPTS_DIR = "output_texts"

os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")
if not PROMPT_FILE or not PROMPT_NAME:
    raise RuntimeError("PROMPT_FILE or PROMPT_NAME not set")

# =========================================================
# REDIS
# =========================================================
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# =========================================================
# INIT VERTEX
# =========================================================
aiplatform.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel(MODEL_NAME)

# =========================================================
# LOGGING
# =========================================================
def log(msg: str):
    print(f"[TRANSCRIBE {datetime.utcnow().isoformat()}] {msg}", flush=True)

# =========================================================
# PROMPT
# =========================================================
def load_named_prompt(prompt_file: str, prompt_name: str) -> str:
    log(f"Loading prompt '{prompt_name}'")
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()

    start = f"### PROMPT: {prompt_name}"
    end = "=== END PROMPT ==="

    if start not in content:
        raise RuntimeError(f"Prompt '{prompt_name}' not found")

    return content.split(start, 1)[1].split(end, 1)[0].strip()


AUDIO_PROMPT = load_named_prompt(PROMPT_FILE, PROMPT_NAME)

# =========================================================
# UTILS
# =========================================================
def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:max_len]


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


def split_audio(mp3_path: str) -> List[str]:
    audio = AudioSegment.from_file(mp3_path)
    duration_sec = int(len(audio) / 1000)
    log(f"Audio duration: {duration_sec}s")

    chunk_ms = CHUNK_DURATION_SEC * 1000
    chunks = []

    for i, start in enumerate(range(0, len(audio), chunk_ms), start=1):
        out = mp3_path.replace(".mp3", f"_chunk_{i}.mp3")
        audio[start:start + chunk_ms].export(out, format="mp3")
        log(f"Created chunk {i}: {os.path.basename(out)}")
        chunks.append(out)

    return chunks


def transcribe_chunk(mp3_path: str, idx: int, total: int) -> str:
    log(f"Gemini ASR chunk {idx}/{total}")
    with open(mp3_path, "rb") as f:
        audio_bytes = f.read()

    response = model.generate_content(
        [
            Part.from_text(AUDIO_PROMPT),
            Part.from_data(audio_bytes, mime_type="audio/mpeg"),
        ],
        generation_config={"temperature": 0, "max_output_tokens": 8192},
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty transcription output")

    return text

# =========================================================
# ENTRYPOINT
# =========================================================
def run_transcription(job_id: str, job: dict) -> str:
    input_path = job["local_path"]

    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    log(f"Starting transcription job_id={job_id}")
    update(job_id, stage="Preparing audio", progress=5)

    chunks = split_audio(input_path)
    texts = []

    for idx, chunk in enumerate(chunks, start=1):
        update(
            job_id,
            stage=f"Transcribing {idx}/{len(chunks)}",
            progress=10 + int((idx / len(chunks)) * 80),
        )
        texts.append(transcribe_chunk(chunk, idx, len(chunks)))

    final_text = "\n\n".join(texts)

    base = sanitize_filename(os.path.basename(input_path))
    local_out = os.path.join(TRANSCRIPTS_DIR, f"{base}.txt")

    with open(local_out, "w", encoding="utf-8") as f:
        f.write(final_text)

    gcs = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/transcript.txt",
    )

    # ✅ STORE BUCKET + BLOB (NOT URL)
    r.hset(
        f"job_status:{job_id}",
        mapping={
            "status": "COMPLETED",
            "stage": "Completed",
            "progress": 100,
            "output_bucket": gcs["bucket"],
            "output_blob": gcs["blob"],
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    log("Transcription completed")
    return local_out
