# User value: This test keeps recovery decisions predictable so users and ops see consistent retry behavior.
import unittest

from worker.recovery_policy import classify_recovery_reason, decide_recovery_action


class RecoveryPolicyUnitTests(unittest.TestCase):
    # User value: ensures transient infra errors choose retry_with_backoff while budget remains.
    def test_transient_error_retries(self):
        decision = decide_recovery_action(
            error_code="INFRA_REDIS",
            attempts=0,
            budget_transient=2,
            budget_media=0,
            budget_default=0,
        )
        self.assertEqual(decision["recovery_action"], "retry_with_backoff")
        self.assertEqual(decision["recovery_reason"], "TRANSIENT_INFRA")
        self.assertTrue(decision["retry_allowed"])

    # User value: ensures fatal/default errors fail fast when budget is exhausted.
    def test_default_error_fail_fast(self):
        decision = decide_recovery_action(
            error_code="PROCESSING_FAILED",
            attempts=0,
            budget_transient=1,
            budget_media=0,
            budget_default=0,
        )
        self.assertEqual(decision["recovery_action"], "fail_fast_dlq")
        self.assertEqual(decision["recovery_reason"], "UNKNOWN_OR_FATAL")
        self.assertFalse(decision["retry_allowed"])

    # User value: ensures media issues map to INPUT_MEDIA reason for clearer guidance.
    def test_media_reason_mapping(self):
        self.assertEqual(classify_recovery_reason("MEDIA_DECODE_FAILED"), "INPUT_MEDIA")


if __name__ == "__main__":
    unittest.main()
