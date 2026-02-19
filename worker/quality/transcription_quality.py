# User value: This module gives users deterministic transcription quality signals without extra model cost.
from __future__ import annotations

import re
from typing import Dict, List, Tuple


# User value: tokenizes transcript text consistently so quality scoring stays predictable across runs.
def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"\w+", text or "", flags=re.UNICODE) if w]


# User value: measures how much transcript content is Hindi/Devanagari for user trust checks.
def _devanagari_ratio(text: str) -> float:
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    dev_count = sum(1 for ch in letters if "\u0900" <= ch <= "\u097F")
    return max(0.0, min(1.0, dev_count / len(letters)))


# User value: flags repetitive noisy outputs so users can review weak transcript regions quickly.
def _repeat_ratio(words: List[str]) -> float:
    if len(words) < 2:
        return 0.0
    repeats = 0
    for i in range(1, len(words)):
        if words[i].lower() == words[i - 1].lower():
            repeats += 1
    return max(0.0, min(1.0, repeats / (len(words) - 1)))


# User value: scores one transcript segment and returns actionable hints for low-quality text.
def score_segment(text: str) -> Tuple[float, Dict[str, float], List[str]]:
    words = _words(text)
    word_count = len(words)
    char_count = len((text or "").strip())

    devanagari_ratio = _devanagari_ratio(text)
    repeat_ratio = _repeat_ratio(words)
    unique_ratio = (len({w.lower() for w in words}) / word_count) if word_count else 0.0
    density_score = min(1.0, word_count / 80.0)
    length_score = min(1.0, char_count / 450.0)

    score = (
        0.28 * density_score
        + 0.22 * length_score
        + 0.22 * devanagari_ratio
        + 0.18 * unique_ratio
        + 0.10 * (1.0 - repeat_ratio)
    )
    score = max(0.0, min(1.0, score))

    hints: List[str] = []
    if word_count < 8:
        hints.append("Very short segment text")
    if devanagari_ratio < 0.45:
        hints.append("Low Hindi-script ratio")
    if repeat_ratio > 0.20:
        hints.append("High repeated-word ratio")
    if unique_ratio < 0.35 and word_count >= 8:
        hints.append("Low vocabulary variety")

    metrics = {
        "word_count": float(word_count),
        "char_count": float(char_count),
        "devanagari_ratio": round(devanagari_ratio, 4),
        "repeat_ratio": round(repeat_ratio, 4),
        "unique_ratio": round(unique_ratio, 4),
        "density_score": round(density_score, 4),
        "length_score": round(length_score, 4),
    }
    return score, metrics, hints


# User value: summarizes segment quality into one score and targeted guidance users can act on.
def summarize_segments(
    segment_rows: List[Dict],
    low_threshold: float = 0.60,
) -> Tuple[float, List[int], List[str]]:
    if not segment_rows:
        return 0.0, [], []

    scores = [float(row.get("score", 0.0)) for row in segment_rows]
    avg = sum(scores) / len(scores)

    low_segments: List[int] = []
    hints: List[str] = []
    for row in segment_rows:
        idx = int(row.get("segment_index", 0))
        score = float(row.get("score", 0.0))
        hint = str(row.get("hint", "")).strip()
        if score < low_threshold and idx > 0:
            low_segments.append(idx)
            if hint:
                hints.append(f"Segment {idx}: {hint}")

    return round(max(0.0, min(1.0, avg)), 4), low_segments, hints[:10]
