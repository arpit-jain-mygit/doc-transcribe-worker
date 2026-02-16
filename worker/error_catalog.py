from __future__ import annotations


def classify_error(exc: Exception) -> tuple[str, str]:
    text = f"{exc}".strip()
    low = text.lower()

    if "resource exhausted" in low or "429" in low or "quota" in low:
        return ("RATE_LIMIT_EXCEEDED", "Service is busy right now. Please retry shortly.")
    if "ffmpeg" in low or "decoding failed" in low or "could not decode" in low:
        return ("MEDIA_DECODE_FAILED", "Input media could not be decoded. Please upload a supported file.")
    if isinstance(exc, FileNotFoundError) or "no such file" in low:
        return ("INPUT_NOT_FOUND", "Input file was not found for processing.")
    if "redis" in low or "connection closed" in low or "timeout" in low:
        return ("INFRA_REDIS", "Queue/storage connection issue while processing.")
    return ("PROCESSING_FAILED", "Processing failed due to an internal error.")
