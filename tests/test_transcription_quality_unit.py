# User value: This test keeps transcription quality scoring stable so users get consistent quality guidance.
import unittest

from worker.quality.transcription_quality import score_segment, summarize_segments


class TranscriptionQualityUnitTests(unittest.TestCase):
    # User value: validates segment scoring boundaries so UI never shows invalid percentages.
    def test_score_segment_bounded(self):
        score, metrics, hints = score_segment("यह एक साफ़ हिंदी वाक्य है जिसमें पर्याप्त शब्द हैं।")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertIn("devanagari_ratio", metrics)
        self.assertIsInstance(hints, list)

    # User value: ensures noisy/repetitive short segments are marked lower with hints.
    def test_score_segment_low_quality_pattern(self):
        score, _, hints = score_segment("test test test")
        self.assertLess(score, 0.6)
        self.assertGreaterEqual(len(hints), 1)

    # User value: ensures summary highlights weak segments for targeted transcript review.
    def test_summarize_segments(self):
        rows = [
            {"segment_index": 1, "score": 0.91, "hint": ""},
            {"segment_index": 2, "score": 0.44, "hint": "High noise"},
            {"segment_index": 3, "score": 0.58, "hint": "Low Hindi-script ratio"},
        ]
        avg, lows, hints = summarize_segments(rows, low_threshold=0.60)
        self.assertAlmostEqual(avg, 0.6433, places=3)
        self.assertEqual(lows, [2, 3])
        self.assertEqual(len(hints), 2)


if __name__ == "__main__":
    unittest.main()
