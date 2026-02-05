# -*- coding: utf-8 -*-
"""
REAL AUDIO TRANSCRIPTION (Gemini ASR)
WITH VERBOSE LOGGING + GCS OUTPUT
(NO APPROVAL GATE)
REDIS SAFE (RECONNECT ON STALE CONNECTION)
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

from worker.utils.gcs import upload_text, download_from_gcs

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

CHUNK_DURATION_SEC = 5 * 60  # 5 min

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")
if not PROMPT_FILE or not PROMPT_NAME:
    raise RuntimeError("PROMPT_FILE or PROMPT_NAME not set")

# =========================================================
# REDIS (SAFE FACTORY)
# =========================================================
def get_redis():
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=2,
        retry_on_timeout=True,
        health_check_interval=15,
    )

# =========================================================
# REDIS SAFE WRITE
# =========================================================
def safe_hset(key: str, mapping: dict, retries: int = 1):
    for attempt in range(retries + 1):
        try:
            r = get_redis()
            r.hset(key, mapping=mapping)
            return
        except redis.exceptions.ConnectionError as e:
            log(f"Redis HSET failed (attempt {attempt + 1}): {e}")
            if attempt >= retries:
                raise

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

def update(job_id: str, *, stage: str, progress: int, status: str = "PROCESSING"):
    safe_hset(
        f"job_status:{job_id}",
        {
            "status": status,
            "stage": stage,
            "progress": progress,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

# =========================================================
# AUDIO SPLIT
# =========================================================
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

    log(f"Total chunks: {len(chunks)}")
    return chunks

# =========================================================
# GEMINI ASR
# =========================================================
def transcribe_chunk(mp3_path: str, idx: int, total: int) -> str:
    log(f"Gemini ASR chunk {idx}/{total}")

    with open(mp3_path, "rb") as f:
        audio_bytes = f.read()

    t0 = time.perf_counter()
    response = model.generate_content(
        [
            Part.from_text(AUDIO_PROMPT),
            Part.from_data(audio_bytes, mime_type="audio/mpeg"),
        ],
        generation_config={"temperature": 0, "max_output_tokens": 8192},
    )

    log(f"Chunk {idx} completed in {round(time.perf_counter() - t0, 2)}s")

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty transcription output")

    return text

# =========================================================
# ENTRYPOINT
# =========================================================
def run_transcription(job_id: str, job: dict) -> dict:
    # -------------------------------------------------
    # 1. Download input from GCS
    # -------------------------------------------------
    if "input_gcs_uri" not in job:
        raise RuntimeError("input_gcs_uri missing in job payload")

    input_gcs_uri = job["input_gcs_uri"]
    local_input = download_from_gcs(input_gcs_uri)

    if not os.path.exists(local_input):
        raise FileNotFoundError(local_input)

    log(f"Using local input: {local_input}")

    # -------------------------------------------------
    # 2. Transcription
    # -------------------------------------------------
    update(job_id, stage="Preparing audio", progress=5)

    chunks = split_audio(local_input)
    total = len(chunks)

    texts: List[str] = []

    for idx, chunk in enumerate(chunks, start=1):
        update(
            job_id,
            stage=f"Transcribing chunk {idx}/{total}",
            progress=10 + int((idx / total) * 80),
        )
        texts.append(transcribe_chunk(chunk, idx, total))

    # -------------------------------------------------
    # 3. Upload transcript to GCS
    # -------------------------------------------------
    final_text = "\n\n".join(texts)

    upload = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/transcript.txt",
    )

    # -------------------------------------------------
    # 4. FINAL STATE — COMPLETED
    # -------------------------------------------------
    safe_hset(
        f"job_status:{job_id}",
        {
            "status": "COMPLETED",
            "stage": "Completed",
            "progress": 100,
            "output_path": upload["gcs_uri"],
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    log(f"Job completed → {upload['gcs_uri']}")

    return {
        "gcs_uri": upload["gcs_uri"],
        "status": "COMPLETED",
    }
