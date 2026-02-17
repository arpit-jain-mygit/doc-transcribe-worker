# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
import unittest

from worker.status_machine import is_allowed_transition


class StatusMachineUnitTests(unittest.TestCase):
    # User value: keeps users updated with live OCR/transcription progress.
    def test_terminal_statuses_are_sticky(self):
        self.assertTrue(is_allowed_transition("COMPLETED", "COMPLETED"))
        self.assertFalse(is_allowed_transition("COMPLETED", "PROCESSING"))
        self.assertTrue(is_allowed_transition("FAILED", "FAILED"))
        self.assertFalse(is_allowed_transition("FAILED", "COMPLETED"))

    # User value: supports test_processing_can_transition_to_terminal so the OCR/transcription journey stays clear and reliable.
    def test_processing_can_transition_to_terminal(self):
        self.assertTrue(is_allowed_transition("PROCESSING", "COMPLETED"))
        self.assertTrue(is_allowed_transition("PROCESSING", "FAILED"))
        self.assertTrue(is_allowed_transition("PROCESSING", "CANCELLED"))

    # User value: supports test_empty_target_is_allowed so the OCR/transcription journey stays clear and reliable.
    def test_empty_target_is_allowed(self):
        self.assertTrue(is_allowed_transition("QUEUED", ""))
        self.assertTrue(is_allowed_transition(None, None))


if __name__ == "__main__":
    unittest.main()
