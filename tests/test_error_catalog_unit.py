import unittest

import redis

from worker.error_catalog import classify_error


class ErrorCatalogUnitTests(unittest.TestCase):
    def test_gcs_connection_error_maps_to_infra_gcs(self):
        exc = Exception("HTTPSConnectionPool host=storage.googleapis.com: Connection aborted")
        code, message = classify_error(exc)
        self.assertEqual(code, "INFRA_GCS")
        self.assertIn("Storage service", message)

    def test_redis_error_maps_to_infra_redis(self):
        exc = redis.exceptions.ConnectionError("Connection closed by server")
        code, message = classify_error(exc)
        self.assertEqual(code, "INFRA_REDIS")
        self.assertIn("Queue/storage", message)

    def test_missing_file_maps_to_input_not_found(self):
        code, _ = classify_error(FileNotFoundError("no such file"))
        self.assertEqual(code, "INPUT_NOT_FOUND")

    def test_fallback_maps_to_processing_failed(self):
        code, _ = classify_error(RuntimeError("some unknown failure"))
        self.assertEqual(code, "PROCESSING_FAILED")


if __name__ == "__main__":
    unittest.main()
