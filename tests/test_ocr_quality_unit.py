# User value: This test keeps OCR quality scoring stable so users get consistent quality hints.
import unittest

from PIL import Image

from worker.quality.ocr_quality import score_page, summarize_document_quality


class OCRQualityUnitTests(unittest.TestCase):
    # User value: validates score boundaries so users never see invalid quality percentages.
    def test_score_page_returns_bounded_score(self):
        img = Image.new("RGB", (200, 200), color="white")
        score, metrics, hints = score_page("Sample OCR text 123", img)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertIn("contrast_score", metrics)
        self.assertIsInstance(hints, list)

    # User value: ensures low-quality pages are identified correctly for targeted re-upload guidance.
    def test_summarize_document_quality_identifies_low_pages(self):
        avg, low_pages = summarize_document_quality([0.92, 0.61, 0.5], low_threshold=0.65)
        self.assertAlmostEqual(avg, 0.68, places=2)
        self.assertEqual(low_pages, [2, 3])

    # User value: ensures empty input remains safe and predictable for UI rendering.
    def test_summarize_empty(self):
        avg, low_pages = summarize_document_quality([])
        self.assertEqual(avg, 0.0)
        self.assertEqual(low_pages, [])


if __name__ == "__main__":
    unittest.main()
