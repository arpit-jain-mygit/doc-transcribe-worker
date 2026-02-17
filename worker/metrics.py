# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import logging
import threading
from copy import deepcopy

logger = logging.getLogger("worker.metrics")
_LOCK = threading.Lock()

_COUNTERS: dict[str, int] = {}
_TIMERS: dict[str, dict[str, float]] = {}


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _tagged_name(name: str, tags: dict[str, str]) -> str:
    if not tags:
        return name
    parts = [f"{k}={v}" for k, v in sorted(tags.items()) if v]
    if not parts:
        return name
    return f"{name}|{'|'.join(parts)}"


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def incr(name: str, amount: int = 1, **tags) -> None:
    metric = _tagged_name(name, {k: str(v) for k, v in tags.items()})
    with _LOCK:
        _COUNTERS[metric] = int(_COUNTERS.get(metric, 0)) + int(amount)
        total = _COUNTERS[metric]
    logger.info(
        "metric_counter_update",
        extra={"metric_name": metric, "metric_type": "counter", "delta": amount, "total": total},
    )


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def observe_ms(name: str, duration_ms: float, **tags) -> None:
    metric = _tagged_name(name, {k: str(v) for k, v in tags.items()})
    value = float(max(0.0, duration_ms))
    with _LOCK:
        current = _TIMERS.get(metric)
        if not current:
            _TIMERS[metric] = {"count": 1.0, "sum_ms": value, "min_ms": value, "max_ms": value}
        else:
            current["count"] += 1.0
            current["sum_ms"] += value
            current["min_ms"] = min(current["min_ms"], value)
            current["max_ms"] = max(current["max_ms"], value)
    logger.info(
        "metric_timer_observe",
        extra={"metric_name": metric, "metric_type": "timer_ms", "value_ms": round(value, 3)},
    )


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def snapshot() -> dict:
    with _LOCK:
        counters = deepcopy(_COUNTERS)
        timers = deepcopy(_TIMERS)
    return {"counters": counters, "timers_ms": timers}
