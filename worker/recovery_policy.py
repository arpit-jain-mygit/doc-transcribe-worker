# User value: This module makes retry/fail-fast decisions explicit so failures are explainable to users and ops.
from __future__ import annotations

from typing import Dict, Tuple


# User value: classifies retry reason so users see whether failure is transient or input-related.
def classify_recovery_reason(error_code: str) -> str:
    code = str(error_code or "").upper()
    if code in {"INFRA_REDIS", "INFRA_GCS", "RATE_LIMIT_EXCEEDED"}:
        return "TRANSIENT_INFRA"
    if code in {"MEDIA_DECODE_FAILED", "INPUT_NOT_FOUND"}:
        return "INPUT_MEDIA"
    return "UNKNOWN_OR_FATAL"


# User value: computes deterministic recovery action so behavior is predictable and testable.
def decide_recovery_action(
    *,
    error_code: str,
    attempts: int,
    budget_transient: int,
    budget_media: int,
    budget_default: int,
) -> Dict[str, object]:
    code = str(error_code or "").upper()
    reason = classify_recovery_reason(code)

    if reason == "TRANSIENT_INFRA":
        budget = max(0, int(budget_transient))
    elif reason == "INPUT_MEDIA":
        budget = max(0, int(budget_media))
    else:
        budget = max(0, int(budget_default))

    attempt_now = max(0, int(attempts))
    retry_allowed = attempt_now < budget
    next_attempt = attempt_now + 1 if retry_allowed else attempt_now

    action = "retry_with_backoff" if retry_allowed else "fail_fast_dlq"
    return {
        "recovery_action": action,
        "recovery_reason": reason,
        "recovery_attempt": next_attempt,
        "recovery_max_attempts": budget,
        "retry_allowed": retry_allowed,
    }


# User value: preserves compatibility with existing retry checks while sharing one recovery policy.
def should_retry(error_code: str, attempts: int, budgets: Tuple[int, int, int]) -> tuple[bool, int]:
    bt, bm, bd = budgets
    decision = decide_recovery_action(
        error_code=error_code,
        attempts=attempts,
        budget_transient=bt,
        budget_media=bm,
        budget_default=bd,
    )
    return bool(decision["retry_allowed"]), int(decision["recovery_max_attempts"])
