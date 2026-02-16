# -*- coding: utf-8 -*-
"""
REAL AUDIO TRANSCRIPTION (Gemini ASR)
WITH VERBOSE LOGGING + GCS OUTPUT
(NO APPROVAL GATE)
REDIS SAFE (RECONNECT ON STALE CONNECTION)

⚠️ DIAGNOSTIC BUILD — NO BEHAVIOR CHANGES
"""

import logging
import os
import sys
import re
import time
import unicodedata
import hashlib
from datetime import datetime
from typing import List

import redis
from dotenv import load_dotenv
from pydub import AudioSegment

from google.cloud import aiplatform
from vertexai.preview.generative_models import GenerativeModel, Part

from worker.cancel import ensure_not_cancelled
from worker.contract import CONTRACT_VERSION
from worker.utils.gcs import upload_text, download_from_gcs
from worker.status_machine import guarded_hset

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
# LOGGING
# =========================================================
logger = logging.getLogger("worker.transcribe")


def log(msg: str):
    logger.info("[TRANSCRIBE %s] %s", datetime.utcnow().isoformat(), msg)

# =========================================================
# REDIS (SAFE FACTORY)
# =========================================================
def get_redis():
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=2,
        socket_timeout=15,
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
            ok, current_status, _ = guarded_hset(
                r,
                key=key,
                mapping=mapping,
                context="TRANSCRIBE_SAFE_HSET",
                request_id=str(mapping.get("request_id") or ""),
            )
            if not ok:
                log(f"Blocked status transition key={key} from={current_status} to={mapping.get('status')}")
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
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    if not name:
        name = "transcript"
    return name[:max_len]


def normalize_output_filename(raw_name: str | None) -> str:
    stem, _ = os.path.splitext(raw_name or "transcript")
    return f"{sanitize_filename(stem)}.txt"


def update(job_id: str, *, stage: str, progress: int, status: str = "PROCESSING"):
    safe_hset(
        f"job_status:{job_id}",
        {
            "contract_version": CONTRACT_VERSION,
            "status": status,
            "stage": stage,
            "progress": progress,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

# =========================================================
# AUDIO SPLIT (DIAGNOSTIC)
# =========================================================
def split_audio(mp3_path: str) -> List[str]:
    file_size = os.path.getsize(mp3_path)
    with open(mp3_path, "rb") as f:
        mp3_md5 = hashlib.md5(f.read()).hexdigest()

    log(f"MP3 file size={file_size} bytes")
    log(f"MP3 md5={mp3_md5}")

    audio = AudioSegment.from_file(mp3_path)

    log(f"Decoded frame_rate={audio.frame_rate}")
    log(f"Decoded channels={audio.channels}")
    log(f"Decoded sample_width={audio.sample_width}")
    log(f"Decoded duration_ms={len(audio)}")

    pcm_head = audio[:30000].raw_data
    pcm_md5 = hashlib.md5(pcm_head).hexdigest()
    log(f"PCM head (30s) md5={pcm_md5}")

    duration_sec = int(len(audio) / 1000)
    log(f"Audio duration seconds={duration_sec}")

    chunk_ms = CHUNK_DURATION_SEC * 1000
    chunks = []

    for i, start in enumerate(range(0, len(audio), chunk_ms), start=1):
        chunk_audio = audio[start:start + chunk_ms]

        chunk_pcm_md5 = hashlib.md5(chunk_audio.raw_data).hexdigest()
        log(
            f"Chunk {i} duration_ms={len(chunk_audio)} "
            f"pcm_md5={chunk_pcm_md5}"
        )

        out = mp3_path.replace(".mp3", f"_chunk_{i}.mp3")
        chunk_audio.export(out, format="mp3")

        log(f"Created chunk file={os.path.basename(out)}")
        chunks.append(out)

    log(f"Total chunks={len(chunks)}")
    return chunks

# =========================================================
# GEMINI ASR
# =========================================================
def transcribe_chunk(mp3_path: str, idx: int, total: int) -> str:
    log(f"Gemini ASR chunk {idx}/{total}")

    with open(mp3_path, "rb") as f:
        audio_bytes = f.read()

    log(f"Chunk {idx} mp3 size={len(audio_bytes)} bytes")

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

    log(f"Chunk {idx} transcript chars={len(text)}")
    return text

# =========================================================
# ENTRYPOINT
# =========================================================
def run_transcription(job_id: str, job: dict, *, finalize: bool = True) -> dict:
    ensure_not_cancelled(job_id)
    if "input_gcs_uri" not in job:
        raise RuntimeError("input_gcs_uri missing in job payload")

    input_gcs_uri = job["input_gcs_uri"]
    local_input = download_from_gcs(input_gcs_uri)

    if not os.path.exists(local_input):
        raise FileNotFoundError(local_input)

    log(f"Using local input={local_input}")

    ensure_not_cancelled(job_id)
    update(job_id, stage="Preparing audio", progress=5)

    chunks = split_audio(local_input)
    total = len(chunks)

    texts: List[str] = []

    for idx, chunk in enumerate(chunks, start=1):
        ensure_not_cancelled(job_id)
        update(
            job_id,
            stage=f"Transcribing chunk {idx}/{total}",
            progress=10 + int((idx / total) * 80),
        )
        texts.append(transcribe_chunk(chunk, idx, total))

    ensure_not_cancelled(job_id)
    final_text = "\n\n".join(texts)
    log(f"Final transcript length chars={len(final_text)}")

    output_filename = normalize_output_filename(job.get("output_filename") or job.get("filename"))

    upload = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/{output_filename}",
    )

    if finalize:
        safe_hset(
            f"job_status:{job_id}",
            {
                "contract_version": CONTRACT_VERSION,
                "status": "COMPLETED",
                "stage": "Completed",
                "progress": 100,
                "output_path": upload["gcs_uri"],
                "output_filename": output_filename,
                "error_code": "",
                "error_message": "",
                "error_detail": "",
                "error": "",
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    log(f"Job completed -> {upload['gcs_uri']}")

    return {
        "gcs_uri": upload["gcs_uri"],
        "output_filename": output_filename,
        "status": "COMPLETED",
    }
