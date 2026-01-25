# -*- coding: utf-8 -*-
"""
Audio / Video Transcription Engine
Callable worker module (Vertex AI Gemini – billing-backed)
"""

import os
import sys
import re
import unicodedata
import time
from datetime import datetime
from typing import Dict

import yt_dlp
from dotenv import load_dotenv

from google.cloud import aiplatform
from vertexai.preview.generative_models import (
    GenerativeModel,
    Part,
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
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash"

CACHE_DIR = ".cache"
AUDIO_CACHE_DIR = os.path.join(CACHE_DIR, "audio")
TRANSCRIPTS_DIR = "transcripts"

os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

PROMPT_FILE = os.environ.get("PROMPT_FILE")
PROMPT_NAME = os.environ.get("PROMPT_NAME")

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")
if not PROMPT_FILE or not PROMPT_NAME:
    raise RuntimeError("PROMPT_FILE or PROMPT_NAME not set")

# =========================================================
# INIT VERTEX AI (SAME AS OCR)
# =========================================================
aiplatform.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel(MODEL_NAME)

# =========================================================
# LOGGING HELPERS
# =========================================================
def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str):
    print(f"[TRANSCRIBE {ts()}] {msg}", flush=True)

def log_ok(msg: str):
    log(f"✅ {msg}")

def log_warn(msg: str):
    log(f"⚠️  {msg}")

def log_err(msg: str):
    log(f"❌ {msg}")

# =========================================================
# yt-dlp QUIET LOGGER
# =========================================================
class YTDLPQuietLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        log_err(f"yt-dlp error: {msg}")

# =========================================================
# PROMPT LOADER (UNCHANGED)
# =========================================================
def load_named_prompt(prompt_file: str, prompt_name: str) -> str:
    log(f"Loading prompt '{prompt_name}' from {prompt_file}")

    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()

    start = f"### PROMPT: {prompt_name}"
    end = "=== END PROMPT ==="

    if start not in content:
        raise RuntimeError(f"Prompt '{prompt_name}' not found")

    prompt = content.split(start, 1)[1].split(end, 1)[0].strip()
    if not prompt:
        raise RuntimeError(f"Prompt '{prompt_name}' is empty")

    log_ok("Prompt loaded successfully")
    return prompt

AUDIO_PROMPT = load_named_prompt(PROMPT_FILE, PROMPT_NAME)

# =========================================================
# UTILITIES
# =========================================================
def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:max_len]

def get_video_info(url: str) -> dict:
    log("Resolving video metadata")
    start = time.perf_counter()

    with yt_dlp.YoutubeDL({
        "quiet": True,
        "no_warnings": True,
        "logger": YTDLPQuietLogger(),
    }) as ydl:
        info = ydl.extract_info(url, download=False)

    log_ok(
        f"Metadata resolved: id={info.get('id')} "
        f"({time.perf_counter() - start:.2f}s)"
    )
    return info

def download_youtube_audio(url: str) -> Dict:
    info = get_video_info(url)
    video_id = info["id"]
    title = info.get("title", video_id)

    mp3_path = os.path.join(AUDIO_CACHE_DIR, f"{video_id}.mp3")

    if os.path.exists(mp3_path):
        log_warn("Using cached audio")
        return {"mp3_path": mp3_path, "title": title, "video_id": video_id}

    log(f"Downloading audio for video_id={video_id}")
    start = time.perf_counter()

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "outtmpl": os.path.join(AUDIO_CACHE_DIR, f"{video_id}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not os.path.exists(mp3_path):
        raise RuntimeError("MP3 not generated")

    log_ok(
        f"Audio downloaded successfully "
        f"({time.perf_counter() - start:.2f}s)"
    )

    return {"mp3_path": mp3_path, "title": title, "video_id": video_id}

# =========================================================
# VERTEX AI TRANSCRIPTION (KEY FIX)
# =========================================================
def transcribe_audio(mp3_path: str) -> str:
    log(f"Sending audio to Vertex AI: {os.path.basename(mp3_path)}")
    start = time.perf_counter()

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

    log_ok(
        f"Vertex transcription completed "
        f"({time.perf_counter() - start:.2f}s)"
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty transcription")

    return text

# =========================================================
# WORKER ENTRYPOINT
# =========================================================
def run_audio_transcription(job: Dict) -> Dict:
    """
    job:
      {
        "job_id": "...",
        "job_type": "TRANSCRIBE",
        "input_type": "YOUTUBE" | "AUDIO",
        "url": "..."
      }
    """

    pipeline_start = time.perf_counter()
    job_id = job.get("job_id")
    url = job["url"]

    log("============================================================")
    log(f"Starting transcription job | job_id={job_id}")
    log(f"Input URL: {url}")
    log("============================================================")

    audio = download_youtube_audio(url)
    text = transcribe_audio(audio["mp3_path"])

    out_name = f"{audio['video_id']}__{sanitize_filename(audio['title'])}.txt"
    out_path = os.path.join(TRANSCRIPTS_DIR, out_name)

    log(f"Writing transcription output to {out_path}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    total_time = time.perf_counter() - pipeline_start

    log("============================================================")
    log_ok("Transcription job completed successfully")
    log(f"Output file: {out_path}")
    log(f"Total time: {total_time:.2f}s")
    log("============================================================")

    filename = os.path.basename(out_path)

    return {
        "job_id": job_id,
        "status": "COMPLETED",
        "output_path": out_path,
        "output_filename": filename,  # ✅ ADD THIS
        "duration_sec": round(total_time, 2),
    }
