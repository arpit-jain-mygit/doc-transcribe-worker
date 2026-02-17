# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import redis
import os
import logging

logger = logging.getLogger("worker.redis")

REDIS_URL = os.getenv("REDIS_URL")

# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def get_redis():
    return redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_connect_timeout=2,
        retry_on_timeout=True,
        health_check_interval=15,
    )

# User value: This step keeps the user OCR/transcription flow accurate and dependable.
def safe_hset(key, mapping, retries=1):
    for attempt in range(retries + 1):
        try:
            r = get_redis()
            r.hset(key, mapping=mapping)
            return
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Redis HSET failed (attempt {attempt+1}): {e}")
            if attempt >= retries:
                raise
