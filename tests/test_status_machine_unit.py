import unittest

from worker.status_machine import is_allowed_transition


class StatusMachineUnitTests(unittest.TestCase):
    def test_terminal_statuses_are_sticky(self):
        self.assertTrue(is_allowed_transition("COMPLETED", "COMPLETED"))
        self.assertFalse(is_allowed_transition("COMPLETED", "PROCESSING"))
        self.assertTrue(is_allowed_transition("FAILED", "FAILED"))
        self.assertFalse(is_allowed_transition("FAILED", "COMPLETED"))

    def test_processing_can_transition_to_terminal(self):
        self.assertTrue(is_allowed_transition("PROCESSING", "COMPLETED"))
        self.assertTrue(is_allowed_transition("PROCESSING", "FAILED"))
        self.assertTrue(is_allowed_transition("PROCESSING", "CANCELLED"))

    def test_empty_target_is_allowed(self):
        self.assertTrue(is_allowed_transition("QUEUED", ""))
        self.assertTrue(is_allowed_transition(None, None))


if __name__ == "__main__":
    unittest.main()
