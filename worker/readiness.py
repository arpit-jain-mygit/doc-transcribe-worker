# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import json
import os
import sys

import redis
from google.cloud import storage


# User value: prevents invalid input so users get reliable OCR/transcription outcomes.
def check() -> dict:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    bucket_name = os.getenv("GCS_BUCKET_NAME", "")
    checks = {"redis": "unknown", "gcs": "unknown"}

    try:
        rc = redis.Redis.from_url(redis_url, decode_responses=True)
        rc.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error:{exc.__class__.__name__}"

    try:
        client = storage.Client()
        if bucket_name:
            client.bucket(bucket_name).exists()
        checks["gcs"] = "ok"
    except Exception as exc:
        checks["gcs"] = f"error:{exc.__class__.__name__}"

    status = "ok" if checks["redis"] == "ok" and checks["gcs"] == "ok" else "degraded"
    return {"status": status, "checks": checks}


if __name__ == "__main__":
    payload = check()
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0 if payload["status"] == "ok" else 1)
