# User value: This file provides deterministic OCR quality scoring and guard rails so users get trustworthy quality indicators.
import itertools
import os
import re
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageFilter, ImageStat

NOISE_CHAR_RE = re.compile(r"[^a-zA-Z0-9\u0900-\u097F\s.,;:!?()\"\-]")
DEFAULT_WEIGHTS = {
    "char_conf_proxy": 0.34,
    "text_density_score": 0.12,
    "contrast_score": 0.20,
    "blur_quality_score": 0.18,
    "noise_quality_score": 0.16,
}
DEFAULT_GUARDS = {
    "clean_text_min_chars": 80,
    "clean_text_garbage_max": 0.12,
    "clean_text_char_conf_min": 0.78,
    "clean_text_floor": 0.65,
    "hint_suppress_density_min": 0.35,
    "clean_proxy_density_min": 0.04,
    "clean_proxy_floor": 0.62,
    "sparse_clean_density_max": 0.25,
    "sparse_clean_bonus": 0.08,
    "dense_clean_bonus": 0.08,
    "dense_clean_char_conf_min": 0.90,
    "dense_clean_garbage_max": 0.05,
    "dense_clean_density_min": 0.15,
    "dense_blur_density_min": 0.70,
    "dense_blur_min": 0.80,
    "dense_blur_penalty": 0.10,
    "dense_blur_penalty_noise_min": 0.08,
    "low_threshold": 0.65,
}


# User value: keeps quality scores bounded so user-facing quality signals stay predictable.
def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


# User value: lets us tune score weights safely from env without redeploying code.
def resolve_weights() -> Dict[str, float]:
    raw = os.getenv("OCR_QUALITY_WEIGHTS_JSON", "").strip()
    if not raw:
        return dict(DEFAULT_WEIGHTS)

    try:
        import json

        parsed = json.loads(raw)
    except Exception:
        return dict(DEFAULT_WEIGHTS)

    result = dict(DEFAULT_WEIGHTS)
    for key in DEFAULT_WEIGHTS:
        value = parsed.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            result[key] = float(value)

    total = sum(result.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in result.items()}


# User value: exposes guard thresholds for deterministic calibration and stable UX.
def resolve_guards() -> Dict[str, float]:
    guards = dict(DEFAULT_GUARDS)
    overrides = {
        "clean_text_min_chars": os.getenv("OCR_QUALITY_CLEAN_TEXT_MIN_CHARS"),
        "clean_text_garbage_max": os.getenv("OCR_QUALITY_CLEAN_TEXT_GARBAGE_MAX"),
        "clean_text_char_conf_min": os.getenv("OCR_QUALITY_CLEAN_TEXT_CHAR_CONF_MIN"),
        "clean_text_floor": os.getenv("OCR_QUALITY_CLEAN_TEXT_FLOOR"),
        "hint_suppress_density_min": os.getenv("OCR_QUALITY_HINT_SUPPRESS_DENSITY_MIN"),
        "clean_proxy_density_min": os.getenv("OCR_QUALITY_CLEAN_PROXY_DENSITY_MIN"),
        "clean_proxy_floor": os.getenv("OCR_QUALITY_CLEAN_PROXY_FLOOR"),
        "sparse_clean_density_max": os.getenv("OCR_QUALITY_SPARSE_CLEAN_DENSITY_MAX"),
        "sparse_clean_bonus": os.getenv("OCR_QUALITY_SPARSE_CLEAN_BONUS"),
        "dense_clean_bonus": os.getenv("OCR_QUALITY_DENSE_CLEAN_BONUS"),
        "dense_clean_char_conf_min": os.getenv("OCR_QUALITY_DENSE_CLEAN_CHAR_CONF_MIN"),
        "dense_clean_garbage_max": os.getenv("OCR_QUALITY_DENSE_CLEAN_GARBAGE_MAX"),
        "dense_clean_density_min": os.getenv("OCR_QUALITY_DENSE_CLEAN_DENSITY_MIN"),
        "dense_blur_density_min": os.getenv("OCR_QUALITY_DENSE_BLUR_DENSITY_MIN"),
        "dense_blur_min": os.getenv("OCR_QUALITY_DENSE_BLUR_MIN"),
        "dense_blur_penalty": os.getenv("OCR_QUALITY_DENSE_BLUR_PENALTY"),
        "dense_blur_penalty_noise_min": os.getenv("OCR_QUALITY_DENSE_BLUR_PENALTY_NOISE_MIN"),
        "low_threshold": os.getenv("OCR_QUALITY_LOW_THRESHOLD"),
    }
    for key, raw in overrides.items():
        if raw is None or raw == "":
            continue
        try:
            guards[key] = float(raw)
        except ValueError:
            continue
    guards["clean_text_min_chars"] = int(max(1, guards["clean_text_min_chars"]))
    return guards


# User value: estimates page contrast to flag faint scans before users trust low-quality OCR output.
def contrast_score(image: Image.Image) -> float:
    gray = image.convert("L")
    std = float(ImageStat.Stat(gray).stddev[0])
    return clamp01(std / 64.0)


# User value: estimates blur so users can quickly identify pages likely to produce weak OCR text.
def blur_score(image: Image.Image) -> float:
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mean = float(ImageStat.Stat(edges).mean[0])
    sharpness = clamp01(edge_mean / 32.0)
    return clamp01(1.0 - sharpness)


# User value: detects noisy OCR text patterns so users get practical cleanup/re-upload hints.
def garbage_ratio(text: str) -> float:
    clean = str(text or "").strip()
    if not clean:
        return 1.0
    noisy = len(NOISE_CHAR_RE.findall(clean))
    return noisy / max(1, len(clean))


# User value: estimates text sufficiency so users know when OCR likely missed most content.
def text_density_score(text: str, image: Image.Image) -> float:
    chars = len(str(text or "").strip())
    area = max(1, int(image.size[0]) * int(image.size[1]))
    density = chars / area
    return clamp01(density * 8000.0)


# User value: provides confidence proxy when OCR engine confidence is unavailable.
def char_conf_proxy(text: str) -> float:
    clean = str(text or "").strip()
    if not clean:
        return 0.0
    return clamp01(1.0 - (garbage_ratio(clean) * 1.5))


# User value: computes score deterministically from metrics so calibration is transparent.
def score_from_metrics(metrics: Dict[str, float], weights: Dict[str, float]) -> float:
    raw = (
        weights["char_conf_proxy"] * clamp01(metrics["char_conf_proxy"])
        + weights["text_density_score"] * clamp01(metrics["text_density_score"])
        + weights["contrast_score"] * clamp01(metrics["contrast_score"])
        + weights["blur_quality_score"] * clamp01(1.0 - metrics["blur_score"])
        + weights["noise_quality_score"] * clamp01(1.0 - metrics["garbage_ratio"])
    )
    return round(clamp01(raw), 2)


# User value: avoids false low scores when text is clean but visual heuristics are noisy.
def apply_guard_rules(score: float, metrics: Dict[str, float], hints: List[str], text: str, guards: Dict[str, float]) -> Tuple[float, List[str]]:
    clean = str(text or "").strip()
    is_clean_text = (
        len(clean) >= int(guards["clean_text_min_chars"])
        and metrics["garbage_ratio"] <= float(guards["clean_text_garbage_max"])
        and metrics["char_conf_proxy"] >= float(guards["clean_text_char_conf_min"])
    )
    adjusted = score
    output_hints = list(hints)
    if is_clean_text:
        adjusted = max(adjusted, float(guards["clean_text_floor"]))
        if metrics["text_density_score"] >= float(guards["hint_suppress_density_min"]):
            output_hints = [h for h in output_hints if h not in ("Image appears blurry", "Low contrast detected")]

    # Additional proxy guard: if text-derived signals are clean but page-vision proxies are harsh,
    # avoid severe under-scoring caused by blur/contrast heuristics.
    clean_proxy = (
        metrics["char_conf_proxy"] >= float(guards["clean_text_char_conf_min"])
        and metrics["garbage_ratio"] <= float(guards["clean_text_garbage_max"])
        and metrics["text_density_score"] >= float(guards["clean_proxy_density_min"])
    )
    if clean_proxy:
        adjusted = max(adjusted, float(guards["clean_proxy_floor"]))

    # Sparse + clean readable pages (short notes/quotes) should get a bounded bonus,
    # not a hard floor, so ranking remains continuous.
    sparse_clean = clean_proxy and metrics["text_density_score"] <= float(guards["sparse_clean_density_max"])
    if sparse_clean:
        adjusted = adjusted + float(guards["sparse_clean_bonus"])

    # Dense, clean text pages should retain high score even if visual blur proxy is pessimistic.
    dense_clean = (
        metrics["char_conf_proxy"] >= float(guards["dense_clean_char_conf_min"])
        and metrics["garbage_ratio"] <= float(guards["dense_clean_garbage_max"])
        and metrics["text_density_score"] >= float(guards["dense_clean_density_min"])
    )
    if dense_clean:
        adjusted = adjusted + float(guards["dense_clean_bonus"])

    # Dense pages with heavy blur should get a bounded penalty,
    # not a hard cap, so better dense pages can still rank higher.
    if (
        metrics["text_density_score"] >= float(guards["dense_blur_density_min"])
        and metrics["blur_score"] >= float(guards["dense_blur_min"])
        and metrics["garbage_ratio"] >= float(guards["dense_blur_penalty_noise_min"])
        and not dense_clean
    ):
        adjusted = adjusted - float(guards["dense_blur_penalty"])
    return round(clamp01(adjusted), 2), output_hints


# User value: supports offline tuning from labeled samples so score aligns better with human quality judgment.
def recalibrate_weights(samples: Sequence[Dict[str, object]], step: float = 0.05, spread: float = 0.10) -> Tuple[Dict[str, float], float]:
    defaults = dict(DEFAULT_WEIGHTS)
    if not samples:
        return defaults, 0.0

    deltas = [round(-spread + i * step, 4) for i in range(int((2 * spread) / step) + 1)]
    best = defaults
    best_mae = float("inf")

    keys = list(DEFAULT_WEIGHTS.keys())
    for delta_vec in itertools.product(deltas, repeat=len(keys)):
        candidate = {k: max(0.0, DEFAULT_WEIGHTS[k] + d) for k, d in zip(keys, delta_vec)}
        total = sum(candidate.values())
        if total <= 0:
            continue
        candidate = {k: v / total for k, v in candidate.items()}

        err = 0.0
        count = 0
        for sample in samples:
            metrics = sample.get("metrics")
            target = sample.get("target_score")
            if not isinstance(metrics, dict) or not isinstance(target, (float, int)):
                continue
            pred = score_from_metrics(metrics, candidate)
            err += abs(pred - float(target))
            count += 1
        if count == 0:
            continue
        mae = err / count
        if mae < best_mae:
            best_mae = mae
            best = candidate
    if best_mae == float("inf"):
        return defaults, 0.0
    return best, round(best_mae, 4)


# User value: computes page-level quality score + hints so users can trust output or decide re-upload.
def score_page(text: str, image: Image.Image) -> Tuple[float, Dict[str, float], List[str]]:
    weights = resolve_weights()
    guards = resolve_guards()
    conf = char_conf_proxy(text)
    contrast = contrast_score(image)
    blur = blur_score(image)
    density = text_density_score(text, image)
    noise = garbage_ratio(text)

    hints: List[str] = []
    if blur > 0.60:
        hints.append("Image appears blurry")
    if contrast < 0.40:
        hints.append("Low contrast detected")
    if density < 0.20:
        hints.append("Very little readable text found")
    if noise > 0.25:
        hints.append("OCR output appears noisy")

    metrics = {
        "char_conf_proxy": round(conf, 2),
        "contrast_score": round(contrast, 2),
        "blur_score": round(blur, 2),
        "text_density_score": round(density, 2),
        "garbage_ratio": round(noise, 2),
    }
    score = score_from_metrics(metrics, weights)
    score, hints = apply_guard_rules(score, metrics, hints, text, guards)
    return score, metrics, hints


# User value: summarizes page-level scores into one document-level quality signal for simple user decisions.
def summarize_document_quality(page_scores: List[float], low_threshold: float = 0.65) -> Tuple[float, List[int]]:
    guards = resolve_guards()
    threshold = float(guards.get("low_threshold", low_threshold))
    if not page_scores:
        return 0.0, []
    avg = round(sum(page_scores) / max(1, len(page_scores)), 2)
    low_pages = [idx + 1 for idx, score in enumerate(page_scores) if float(score) < threshold]
    return avg, low_pages
