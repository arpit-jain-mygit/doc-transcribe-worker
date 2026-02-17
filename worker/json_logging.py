# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import json
import logging
from datetime import datetime, timezone
from typing import Any


_EXCLUDED_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            norm = _normalize(v)
            if norm is not None:
                out[str(k)] = norm
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return str(value)


class JsonLogFormatter(logging.Formatter):
    # User value: This step keeps the user OCR/transcription flow accurate and dependable.
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    # User value: This step keeps the user OCR/transcription flow accurate and dependable.
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _EXCLUDED_FIELDS or key in payload:
                continue
            norm = _normalize(value)
            if norm is not None:
                payload[key] = norm

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def configure_json_logging(service: str, level: int) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(service=service))
    root.handlers = [handler]
    root.setLevel(level)
