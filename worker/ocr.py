# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
# -*- coding: utf-8 -*-
"""
REAL PDF OCR (Gemini Vision OCR)
Drop-in replacement for pytesseract-based ocr.py
"""

import io
import math
import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from typing import List

import redis
from google.api_core.exceptions import ResourceExhausted
from dotenv import load_dotenv
from pdf2image import convert_from_path, pdfinfo_from_path
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
from worker.status_machine import guarded_hset
from worker.utils.retry_policy import REDIS_POLICY, run_with_retry
from worker.quality.ocr_quality import score_page, summarize_document_quality

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

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


# User value: supports _env_int so the OCR/transcription journey stays clear and reliable.
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(str(raw).strip())

 
def _env_int_alias(primary: str, legacy: str, default: int) -> int:
    raw = os.getenv(primary)
    if raw is None:
        raw = os.getenv(legacy)
    if raw is None:
        return default
    return int(str(raw).strip())


OCR_DPI = _env_int("OCR_DPI", 300)
OCR_PAGE_BATCH_SIZE = _env_int("OCR_PAGE_BATCH_SIZE", 0)
OCR_PAGE_RETRIES = _env_int("OCR_PAGE_RETRIES", 2)
GEMINI_PAGES_PER_REQUEST = _env_int("GEMINI_PAGES_PER_REQUEST", 1)
GEMINI_429_COOLDOWN_SEC = _env_int_alias("GEMINI_429_COOLDOWN_SEC", "OCR_429_COOLDOWN_SEC", 60)
GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC = _env_int_alias("GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC", "OCR_429_COOLDOWN_LOG_INTERVAL_SEC", 10)
GEMINI_429_MAX_COOLDOWNS_PER_PAGE = _env_int_alias("GEMINI_429_MAX_COOLDOWNS_PER_PAGE", "OCR_429_MAX_COOLDOWNS_PER_PAGE", 30)
OCR_ALLOW_EMPTY_PAGE_FALLBACK = str(os.getenv("OCR_ALLOW_EMPTY_PAGE_FALLBACK", "1")).strip().lower() not in ("0", "false", "no")

if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID not set")
if OCR_DPI < 72:
    raise RuntimeError("OCR_DPI must be >= 72")
if OCR_PAGE_BATCH_SIZE < 0:
    raise RuntimeError("OCR_PAGE_BATCH_SIZE must be >= 0")
if OCR_PAGE_RETRIES < 0:
    raise RuntimeError("OCR_PAGE_RETRIES must be >= 0")
if GEMINI_PAGES_PER_REQUEST < 1:
    raise RuntimeError("GEMINI_PAGES_PER_REQUEST must be >= 1")
if GEMINI_429_COOLDOWN_SEC < 1:
    raise RuntimeError("GEMINI_429_COOLDOWN_SEC must be >= 1")
if GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC < 1:
    raise RuntimeError("GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC must be >= 1")
if GEMINI_429_MAX_COOLDOWNS_PER_PAGE < 1:
    raise RuntimeError("GEMINI_429_MAX_COOLDOWNS_PER_PAGE must be >= 1")

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


# User value: supports log so the OCR/transcription journey stays clear and reliable.
def log(msg: str):
    logger.info("[OCR %s] %s", datetime.utcnow().isoformat(), msg)


class PageRateLimitExceeded(RuntimeError):
    def __init__(self, page_num: int):
        super().__init__(f"Gemini 429 cooldown exhausted for page {page_num}")
        self.page_num = page_num

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


# User value: loads latest OCR/transcription data so users see current status.
def load_named_prompt(prompt_file: str, prompt_name: str) -> str:
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()

    variants = [prompt_name, f"{prompt_name}_PROMPT"] if not str(prompt_name).endswith("_PROMPT") else [prompt_name]
    start = ""
    for name in variants:
        for prefix in ("### PROMPT: ", "### "):
            marker = f"{prefix}{name}"
            if marker in content:
                start = marker
                break
        if start:
            break
    end = "=== END PROMPT ==="
    if not start:
        raise RuntimeError(f"Prompt '{prompt_name}' not found")
    return content.split(start, 1)[1].split(end, 1)[0].strip()


# User value: maps user-selected PDF type to deterministic OCR prompt behavior.
def resolve_ocr_prompt(job: dict, page_num: int) -> str:
    subtype = str(job.get("content_subtype") or "").strip().lower()
    # Current requirement: both OCR subtypes share the same Jain shastra verbatim prompt.
    if subtype in {"jain_literature", "general"} and PROMPT_FILE:
        try:
            prompt = load_named_prompt(PROMPT_FILE, "JAIN_SHASTRA_VERBATIM_TRANSCRIPTION")
            return prompt.replace("{PAGE_NUMBER}", str(page_num)).replace("{page}", str(page_num))
        except Exception:
            pass
    return PROMPT_TEMPLATE.format(page=page_num)


def resolve_batch_ocr_prompt(job: dict, page_numbers: list[int]) -> str:
    pages_csv = ",".join(str(p) for p in page_numbers)
    base = resolve_ocr_prompt(job, page_numbers[0] if page_numbers else 1)
    return (
        f"{base}\n\n"
        "BATCH MODE INSTRUCTIONS:\n"
        f"- You are receiving multiple page images in this request.\n"
        f"- The pages, in order, are: {pages_csv}.\n"
        "- Return ONLY valid JSON with this exact schema:\n"
        '{"pages":[{"page":<int>,"text":"<verbatim transcription>"}]}\n'
        "- Include one item per page in the same order.\n"
        "- Do not add markdown fences, commentary, or extra keys."
    )

# =========================================================
# UTILS
# =========================================================
# User value: supports pil_to_png_bytes so the OCR/transcription journey stays clear and reliable.
def pil_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# User value: supports sanitize_filename so the OCR/transcription journey stays clear and reliable.
def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    if not name:
        name = "transcript"
    return name[:max_len]


# User value: normalizes data so users see consistent OCR/transcription results.
def normalize_output_filename(raw_name: str | None) -> str:
    stem, _ = os.path.splitext(raw_name or "transcript")
    return f"{sanitize_filename(stem)}.txt"


def ocr_pages_cache_key(job_id: str) -> str:
    return f"job_ocr_pages:{job_id}"


def _redis_retryable(op: str, target: str, fn):
    def _on_retry(attempt: int, exc: BaseException) -> None:
        logger.warning("ocr_redis_retry op=%s target=%s attempt=%s/%s error=%s", op, target, attempt, REDIS_POLICY.max_retries, exc)

    return run_with_retry(
        operation=op,
        target=target,
        fn=fn,
        retryable=(redis.exceptions.ConnectionError, redis.exceptions.TimeoutError),
        policy=REDIS_POLICY,
        on_retry=_on_retry,
    )


def load_cached_page_texts(job_id: str) -> dict[int, str]:
    key = ocr_pages_cache_key(job_id)
    raw = _redis_retryable("redis_hgetall", key, lambda: r.hgetall(key) or {})
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            page_num = int(k)
        except Exception:
            continue
        out[page_num] = v or ""
    return out


def cache_page_text(job_id: str, page_num: int, text: str) -> None:
    key = ocr_pages_cache_key(job_id)
    _redis_retryable("redis_hset", f"{key}:{page_num}", lambda: r.hset(key, str(page_num), text))


def clear_cached_page_texts(job_id: str) -> None:
    key = ocr_pages_cache_key(job_id)
    _redis_retryable("redis_delete", key, lambda: r.delete(key))


def ocr_failed_pages_cache_key(job_id: str) -> str:
    return f"job_ocr_failed_pages:{job_id}"


def load_cached_failed_pages(job_id: str) -> set[int]:
    key = ocr_failed_pages_cache_key(job_id)
    raw_members = _redis_retryable("redis_smembers", key, lambda: r.smembers(key) or set())
    out: set[int] = set()
    for raw in raw_members:
        try:
            out.add(int(str(raw).strip()))
        except Exception:
            continue
    return out


def cache_failed_page(job_id: str, page_num: int) -> None:
    key = ocr_failed_pages_cache_key(job_id)
    _redis_retryable("redis_sadd", f"{key}:{page_num}", lambda: r.sadd(key, str(page_num)))


def clear_cached_failed_pages(job_id: str) -> None:
    key = ocr_failed_pages_cache_key(job_id)
    _redis_retryable("redis_delete", key, lambda: r.delete(key))


def _is_gemini_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, ResourceExhausted):
        return True
    msg = str(exc).lower()
    return "resource exhausted" in msg or "statuscode.resource_exhausted" in msg or "429" in msg


def _wait_for_429_cooldown(*, page_num: int, cooldown_no: int, wait_sec: int) -> None:
    logger.warning(
        "ocr_rate_limit_cooldown_started page=%s cooldown_index=%s wait_sec=%s",
        page_num,
        cooldown_no,
        wait_sec,
    )
    step = max(1, GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC)
    remaining = wait_sec
    while remaining > 0:
        sleep_for = min(step, remaining)
        logger.info(
            "ocr_rate_limit_cooldown_waiting page=%s cooldown_index=%s remaining_sec=%s",
            page_num,
            cooldown_no,
            remaining,
        )
        time.sleep(sleep_for)
        remaining -= sleep_for
    logger.warning(
        "ocr_rate_limit_cooldown_finished page=%s cooldown_index=%s",
        page_num,
        cooldown_no,
    )


def _extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("Batch OCR response does not contain JSON object")
    return raw[start : end + 1]




# User value: supports iter_pdf_pages so the OCR/transcription journey stays clear and reliable.
def iter_pdf_pages(input_path: str):
    if OCR_PAGE_BATCH_SIZE <= 0:
        pages = convert_from_path(input_path, dpi=OCR_DPI)
        yield 1, pages, len(pages)
        return

    info = pdfinfo_from_path(input_path)
    total_pages = int(info.get("Pages", 0) or 0)
    if total_pages <= 0:
        raise RuntimeError("No pages detected in input PDF")

    for first_page in range(1, total_pages + 1, OCR_PAGE_BATCH_SIZE):
        last_page = min(total_pages, first_page + OCR_PAGE_BATCH_SIZE - 1)
        pages = convert_from_path(
            input_path,
            dpi=OCR_DPI,
            first_page=first_page,
            last_page=last_page,
        )
        yield first_page, pages, total_pages


# User value: supports safe_hset so the OCR/transcription journey stays clear and reliable.
def safe_hset(key: str, mapping: dict, retries: int = 1):
    policy = REDIS_POLICY
    if retries != REDIS_POLICY.max_retries:
        policy = type(REDIS_POLICY)(
            name=REDIS_POLICY.name,
            max_retries=max(0, retries),
            base_delay_sec=REDIS_POLICY.base_delay_sec,
            max_delay_sec=REDIS_POLICY.max_delay_sec,
            jitter_ratio=REDIS_POLICY.jitter_ratio,
        )

    # User value: supports _write_once so the OCR/transcription journey stays clear and reliable.
    def _write_once():
        rc = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=2,
            socket_timeout=10,
            retry_on_timeout=True,
            health_check_interval=15,
        )
        ok, current_status, _ = guarded_hset(
            rc,
            key=key,
            mapping=mapping,
            context="OCR_SAFE_HSET",
            request_id=str(mapping.get("request_id") or ""),
        )
        if not ok:
            logger.warning("ocr_status_transition_blocked key=%s from=%s to=%s", key, current_status, mapping.get("status"))
        return None

    # User value: improves reliability when OCR/transcription dependencies fail transiently.
    def _on_retry(attempt: int, exc: BaseException) -> None:
        logger.warning("ocr_safe_hset_retry key=%s attempt=%s/%s error=%s", key, attempt, policy.max_retries, exc)

    run_with_retry(
        operation="redis_hset",
        target=key,
        fn=_write_once,
        retryable=(redis.exceptions.ConnectionError, redis.exceptions.TimeoutError),
        policy=policy,
        on_retry=_on_retry,
    )

# User value: updates user-visible OCR/transcription state accurately.
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
# User value: supports gemini_ocr so the OCR/transcription journey stays clear and reliable.
def gemini_ocr(image: Image.Image, page_num: int, job: dict) -> str:
    png_bytes = pil_to_png_bytes(image)
    vertex_image = VertexImage.from_bytes(png_bytes)

    log(f"Starting Gemini OCR for page {page_num}")
    t0 = time.perf_counter()

    response = model.generate_content(
        [
            Part.from_text(resolve_ocr_prompt(job, page_num)),
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


def gemini_ocr_batch(page_items: list[tuple[int, Image.Image]], job: dict) -> dict[int, str]:
    if not page_items:
        return {}

    page_numbers = [p for p, _ in page_items]
    parts = [Part.from_text(resolve_batch_ocr_prompt(job, page_numbers))]
    for _, image in page_items:
        png_bytes = pil_to_png_bytes(image)
        parts.append(Part.from_image(VertexImage.from_bytes(png_bytes)))

    log(f"Starting Gemini OCR batch pages={page_numbers}")
    t0 = time.perf_counter()
    response = model.generate_content(
        parts,
        generation_config={
            "temperature": 0,
            "max_output_tokens": 8192,
        },
    )
    dt = round(time.perf_counter() - t0, 2)
    log(f"Gemini OCR batch completed pages={page_numbers} in {dt}s")

    raw_text = (response.text or "").strip()
    if not raw_text:
        raise RuntimeError(f"Empty OCR output for batch pages={page_numbers}")

    obj = json.loads(_extract_json_object(raw_text))
    rows = obj.get("pages")
    if not isinstance(rows, list):
        raise RuntimeError("Batch OCR response missing 'pages' list")

    out: dict[int, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            p = int(item.get("page"))
        except Exception:
            continue
        if p not in page_numbers:
            continue
        out[p] = str(item.get("text") or "").strip()

    missing = [p for p in page_numbers if p not in out]
    if missing:
        raise RuntimeError(f"Batch OCR response missing pages={missing}")

    return out


# User value: retries transient empty-page model responses so one weak page does not fail full OCR job.
def gemini_ocr_with_retries(image: Image.Image, page_num: int, job: dict) -> str:
    last_err: Exception | None = None
    attempts = OCR_PAGE_RETRIES + 1
    cooldown_count = 0
    attempt = 1
    while attempt <= attempts:
        try:
            return gemini_ocr(image, page_num, job)
        except RuntimeError as exc:
            last_err = exc
            if "Empty OCR output page" not in str(exc):
                raise
            logger.warning(
                "ocr_empty_page_retry job_page=%s attempt=%s/%s error=%s",
                page_num,
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                time.sleep(min(1.5, 0.4 * attempt))
                attempt += 1
                continue
            if OCR_ALLOW_EMPTY_PAGE_FALLBACK:
                logger.warning("ocr_empty_page_fallback job_page=%s using_placeholder=true", page_num)
                return ""
            raise
        except Exception as exc:
            if not _is_gemini_rate_limited(exc):
                raise
            cooldown_count += 1
            if cooldown_count > GEMINI_429_MAX_COOLDOWNS_PER_PAGE:
                logger.error(
                    "ocr_rate_limit_cooldown_exhausted page=%s cooldowns=%s max=%s",
                    page_num,
                    cooldown_count - 1,
                    GEMINI_429_MAX_COOLDOWNS_PER_PAGE,
                )
                raise PageRateLimitExceeded(page_num)
            logger.warning(
                "ocr_rate_limit_detected page=%s attempt=%s/%s cooldown_index=%s/%s error=%s",
                page_num,
                attempt,
                attempts,
                cooldown_count,
                GEMINI_429_MAX_COOLDOWNS_PER_PAGE,
                exc,
            )
            _wait_for_429_cooldown(
                page_num=page_num,
                cooldown_no=cooldown_count,
                wait_sec=GEMINI_429_COOLDOWN_SEC,
            )
            # Retry same page after cooldown without advancing the pipeline.
            continue
    if last_err:
        raise last_err
    return ""


def gemini_ocr_batch_with_retries(page_items: list[tuple[int, Image.Image]], job: dict) -> dict[int, str]:
    if not page_items:
        return {}
    page_numbers = [p for p, _ in page_items]
    first_page = min(page_numbers)
    last_page = max(page_numbers)
    cooldown_count = 0
    while True:
        try:
            return gemini_ocr_batch(page_items, job)
        except Exception as exc:
            if not _is_gemini_rate_limited(exc):
                raise
            cooldown_count += 1
            if cooldown_count > GEMINI_429_MAX_COOLDOWNS_PER_PAGE:
                logger.error(
                    "ocr_rate_limit_cooldown_exhausted batch_pages=%s-%s cooldowns=%s max=%s",
                    first_page,
                    last_page,
                    cooldown_count - 1,
                    GEMINI_429_MAX_COOLDOWNS_PER_PAGE,
                )
                raise PageRateLimitExceeded(first_page)
            logger.warning(
                "ocr_rate_limit_detected batch_pages=%s-%s cooldown_index=%s/%s error=%s",
                first_page,
                last_page,
                cooldown_count,
                GEMINI_429_MAX_COOLDOWNS_PER_PAGE,
                exc,
            )
            _wait_for_429_cooldown(
                page_num=first_page,
                cooldown_no=cooldown_count,
                wait_sec=GEMINI_429_COOLDOWN_SEC,
            )
            continue

# =========================================================
# WORKER ENTRYPOINT
# =========================================================
# User value: supports run_ocr so the OCR/transcription journey stays clear and reliable.
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

    log(
        f"OCR strategy dpi={OCR_DPI} page_batch_size={OCR_PAGE_BATCH_SIZE if OCR_PAGE_BATCH_SIZE > 0 else 'all'} "
        f"gemini_pages_per_request={GEMINI_PAGES_PER_REQUEST} job_id={job_id}"
    )

    texts: List[str] = []
    start = time.perf_counter()
    processed_pages = 0
    total_pages = 0
    page_scores: List[float] = []
    all_quality_hints: List[str] = []
    failed_rate_limited_pages: set[int] = load_cached_failed_pages(job_id)
    cached_pages = load_cached_page_texts(job_id)
    resume_page = max(cached_pages.keys(), default=0)

    if resume_page > 0:
        log(
            f"OCR resume checkpoint detected: resume_from_page={resume_page + 1} "
            f"cached_pages={len(cached_pages)} job_id={job_id}"
        )

    for batch_first_page, pages, batch_total_pages in iter_pdf_pages(input_path):
        if total_pages == 0:
            total_pages = batch_total_pages
            log(f"PDF pages detected: {total_pages}")

        batch_last_page = batch_first_page + len(pages) - 1
        chunk_size = OCR_PAGE_BATCH_SIZE if OCR_PAGE_BATCH_SIZE > 0 else total_pages
        chunk_index = ((batch_first_page - 1) // max(1, chunk_size)) + 1
        total_chunks = max(1, math.ceil(total_pages / max(1, chunk_size)))

        log(
            f"OCR chunk created: chunk={chunk_index}/{total_chunks} "
            f"page_range={batch_first_page}-{batch_last_page} "
            f"pages_in_chunk={len(pages)} chunk_size_config={chunk_size}"
        )

        batched_items: list[tuple[int, Image.Image]] = []

        def flush_batched_items():
            nonlocal processed_pages, batched_items
            if not batched_items:
                return
            if len(batched_items) == 1:
                only_idx, only_page = batched_items[0]
                try:
                    text_single = gemini_ocr_with_retries(only_page, only_idx, job)
                    cache_page_text(job_id, only_idx, text_single)
                    log(f"OCR checkpoint saved: page={only_idx}")
                except PageRateLimitExceeded:
                    text_single = ""
                    failed_rate_limited_pages.add(only_idx)
                    cache_failed_page(job_id, only_idx)
                    cache_page_text(job_id, only_idx, text_single)
                    log(
                        f"OCR page skipped after Gemini cooldown exhaustion: "
                        f"page={only_idx} max_cooldowns={GEMINI_429_MAX_COOLDOWNS_PER_PAGE}"
                    )
                    all_quality_hints.append(
                        f"Page {only_idx}: skipped after repeated Gemini 429 (cooldown exhausted)"
                    )
                texts.append(text_single)
                page_score, page_metrics, page_hints = score_page(text_single, only_page)
                page_scores.append(page_score)
                if page_hints:
                    all_quality_hints.extend([f"Page {only_idx}: {hint}" for hint in page_hints])
                if not text_single:
                    all_quality_hints.append(f"Page {only_idx}: OCR response was empty after retries")
                elapsed = time.perf_counter() - start
                avg = elapsed / max(1, processed_pages)
                eta = int(avg * (total_pages - only_idx))
                safe_hset(
                    f"job_status:{job_id}",
                    {
                        "current_page": only_idx,
                        "total_pages": total_pages,
                        "eta_sec": eta,
                        "ocr_page_score": page_score,
                        "ocr_page_metrics": json.dumps(page_metrics, ensure_ascii=False),
                    },
                )
                batched_items = []
                return

            page_nums = [p for p, _ in batched_items]
            log(f"OCR gemini_batch dispatch pages={page_nums}")
            try:
                batch_texts = gemini_ocr_batch_with_retries(batched_items, job)
                for page_num, page_obj in batched_items:
                    text_batch = batch_texts.get(page_num, "")
                    cache_page_text(job_id, page_num, text_batch)
                    log(f"OCR checkpoint saved: page={page_num}")
                    texts.append(text_batch)
                    page_score, page_metrics, page_hints = score_page(text_batch, page_obj)
                    page_scores.append(page_score)
                    if page_hints:
                        all_quality_hints.extend([f"Page {page_num}: {hint}" for hint in page_hints])
                    if not text_batch:
                        all_quality_hints.append(f"Page {page_num}: OCR response was empty after retries")
                    elapsed = time.perf_counter() - start
                    avg = elapsed / max(1, processed_pages)
                    eta = int(avg * (total_pages - page_num))
                    safe_hset(
                        f"job_status:{job_id}",
                        {
                            "current_page": page_num,
                            "total_pages": total_pages,
                            "eta_sec": eta,
                            "ocr_page_score": page_score,
                            "ocr_page_metrics": json.dumps(page_metrics, ensure_ascii=False),
                        },
                    )
            except PageRateLimitExceeded:
                for page_num, _page_obj in batched_items:
                    texts.append("")
                    failed_rate_limited_pages.add(page_num)
                    cache_failed_page(job_id, page_num)
                    cache_page_text(job_id, page_num, "")
                    log(
                        f"OCR page skipped after Gemini cooldown exhaustion: "
                        f"page={page_num} max_cooldowns={GEMINI_429_MAX_COOLDOWNS_PER_PAGE}"
                    )
                    all_quality_hints.append(
                        f"Page {page_num}: skipped after repeated Gemini 429 (cooldown exhausted)"
                    )
            batched_items = []

        for offset, page in enumerate(pages, start=0):
            idx = batch_first_page + offset
            processed_pages += 1

            ensure_not_cancelled(job_id, r=r)
            update(
                job_id,
                stage=f"OCR page {idx}/{total_pages}",
                progress=10 + int((idx / total_pages) * 80),
            )

            if idx in cached_pages:
                text = cached_pages[idx]
                log(f"OCR resume page_hit: page={idx} source=checkpoint_cache")
                texts.append(text)
                page_score, page_metrics, page_hints = score_page(text, page)
                page_scores.append(page_score)
                if page_hints:
                    all_quality_hints.extend([f"Page {idx}: {hint}" for hint in page_hints])
                if not text:
                    all_quality_hints.append(f"Page {idx}: OCR response was empty after retries")
                elapsed = time.perf_counter() - start
                avg = elapsed / max(1, processed_pages)
                eta = int(avg * (total_pages - idx))
                safe_hset(
                    f"job_status:{job_id}",
                    {
                        "current_page": idx,
                        "total_pages": total_pages,
                        "eta_sec": eta,
                        "ocr_page_score": page_score,
                        "ocr_page_metrics": json.dumps(page_metrics, ensure_ascii=False),
                    },
                )
                continue

            batched_items.append((idx, page))
            if len(batched_items) >= GEMINI_PAGES_PER_REQUEST:
                flush_batched_items()

        flush_batched_items()

        log(
            f"OCR chunk completed: chunk={chunk_index}/{total_chunks} "
            f"processed_page_range={batch_first_page}-{batch_last_page} "
            f"processed_pages_total={processed_pages}/{total_pages}"
        )

    if total_pages <= 0:
        raise RuntimeError("No pages detected in input PDF")

    ensure_not_cancelled(job_id, r=r)
    update(job_id, stage="Finalizing OCR", progress=95)

    ocr_quality_score, low_confidence_pages = summarize_document_quality(
        page_scores=page_scores,
    )
    for page_num in sorted(failed_rate_limited_pages):
        if page_num not in low_confidence_pages:
            low_confidence_pages.append(page_num)
    low_confidence_pages = sorted(low_confidence_pages)
    quality_hints = all_quality_hints[:10]

    final_text = "\n\n".join(texts)
    output_filename = normalize_output_filename(job.get("output_filename") or job.get("filename"))

    uploaded = upload_text(
        content=final_text,
        destination_path=f"jobs/{job_id}/{output_filename}",
    )
    clear_cached_page_texts(job_id)
    clear_cached_failed_pages(job_id)

    safe_hset(
        f"job_status:{job_id}",
        {
            "contract_version": CONTRACT_VERSION,
            "status": "COMPLETED",
            "stage": "Completed",
            "progress": 100,
            "output_path": uploaded["gcs_uri"],
            "output_filename": output_filename,
            "ocr_quality_score": ocr_quality_score,
            "low_confidence_pages": json.dumps(low_confidence_pages, ensure_ascii=False),
            "quality_hints": json.dumps(quality_hints, ensure_ascii=False),
            "error_code": "",
            "error_message": "",
            "error_detail": "",
            "error": "",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    log(
        f"OCR completed -> {uploaded['gcs_uri']} quality_score={ocr_quality_score} "
        f"low_pages={len(low_confidence_pages)} skipped_pages={len(failed_rate_limited_pages)}"
    )
    return {
        "gcs_uri": uploaded["gcs_uri"],
        "output_filename": output_filename,
        "status": "COMPLETED",
    }
