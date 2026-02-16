from __future__ import annotations

import logging
from typing import Optional

from worker.contract import (
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
)

logger = logging.getLogger("worker.status_machine")

_ALLOWED = {
    None: {
        JOB_STATUS_QUEUED,
        JOB_STATUS_PROCESSING,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
    },
    JOB_STATUS_QUEUED: {
        JOB_STATUS_QUEUED,
        JOB_STATUS_PROCESSING,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
    },
    JOB_STATUS_PROCESSING: {
        JOB_STATUS_PROCESSING,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
    },
    JOB_STATUS_COMPLETED: {JOB_STATUS_COMPLETED},
    JOB_STATUS_FAILED: {JOB_STATUS_FAILED},
    JOB_STATUS_CANCELLED: {JOB_STATUS_CANCELLED},
}


def _norm(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    s = str(status).strip().upper()
    return s or None


def is_allowed_transition(current: Optional[str], target: Optional[str]) -> bool:
    target_n = _norm(target)
    if not target_n:
        return True
    current_n = _norm(current)
    allowed = _ALLOWED.get(current_n, _ALLOWED[None])
    return target_n in allowed


def guarded_hset(r, *, key: str, mapping: dict, context: str, request_id: str = "") -> tuple[bool, Optional[str], Optional[str]]:
    target = _norm(mapping.get("status"))
    if not target:
        r.hset(key, mapping=mapping)
        return True, None, None

    current_data = r.hgetall(key) or {}
    current = _norm(current_data.get("status"))

    if not is_allowed_transition(current, target):
        logger.warning(
            "status_transition_blocked context=%s key=%s current=%s target=%s request_id=%s",
            context,
            key,
            current,
            target,
            request_id,
        )
        return False, current, target

    r.hset(key, mapping=mapping)
    return True, current, target
