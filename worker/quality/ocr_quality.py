# User value: This file computes deterministic OCR quality so users get consistent quality guidance without extra model cost.
import re
from typing import Dict, List, Tuple

from PIL import Image, ImageFilter, ImageStat

NOISE_CHAR_RE = re.compile(r"[^a-zA-Z0-9\u0900-\u097F\s.,;:!?()\"\-]")


# User value: keeps quality scores bounded so user-facing quality signals stay predictable.
def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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


# User value: computes page-level quality score + hints so users can trust output or decide re-upload.
def score_page(text: str, image: Image.Image) -> Tuple[float, Dict[str, float], List[str]]:
    conf = char_conf_proxy(text)
    contrast = contrast_score(image)
    blur = blur_score(image)
    density = text_density_score(text, image)
    noise = garbage_ratio(text)

    score = clamp01(
        0.30 * conf
        + 0.20 * density
        + 0.20 * contrast
        + 0.15 * (1.0 - blur)
        + 0.15 * (1.0 - noise)
    )
    score = round(score, 2)

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
    return score, metrics, hints


# User value: summarizes page-level scores into one document-level quality signal for simple user decisions.
def summarize_document_quality(page_scores: List[float], low_threshold: float = 0.65) -> Tuple[float, List[int]]:
    if not page_scores:
        return 0.0, []
    avg = round(sum(page_scores) / max(1, len(page_scores)), 2)
    low_pages = [idx + 1 for idx, score in enumerate(page_scores) if float(score) < float(low_threshold)]
    return avg, low_pages
