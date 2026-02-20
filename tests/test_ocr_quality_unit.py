# User value: This test keeps OCR quality scoring stable so users get consistent quality hints.
import unittest

from PIL import Image

from worker.quality.ocr_quality import (
    apply_guard_rules,
    recalibrate_weights,
    score_from_metrics,
    score_page,
    summarize_document_quality,
)


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

    # User value: ensures guard rules prevent obvious false-low scores on clean readable text.
    def test_apply_guard_rules_boosts_clean_text(self):
        guards = {
            "clean_text_min_chars": 20,
            "clean_text_garbage_max": 0.12,
            "clean_text_char_conf_min": 0.78,
            "clean_text_floor": 0.65,
            "hint_suppress_density_min": 0.35,
            "clean_proxy_density_min": 0.04,
            "clean_proxy_floor": 0.62,
            "sparse_clean_density_max": 0.25,
            "sparse_clean_bonus": 0.08,
            "dense_clean_bonus": 0.08,
            "dense_clean_char_conf_min": 0.90,
            "dense_clean_garbage_max": 0.05,
            "dense_clean_density_min": 0.15,
            "dense_blur_density_min": 0.70,
            "dense_blur_min": 0.80,
            "dense_blur_penalty": 0.10,
            "dense_blur_penalty_noise_min": 0.08,
        }
        metrics = {
            "char_conf_proxy": 0.91,
            "contrast_score": 0.2,
            "blur_score": 0.55,
            "text_density_score": 0.4,
            "garbage_ratio": 0.02,
        }
        score, hints = apply_guard_rules(
            score=0.42,
            metrics=metrics,
            hints=["Image appears blurry", "Low contrast detected"],
            text="Readable content " * 5,
            guards=guards,
        )
        self.assertGreaterEqual(score, 0.65)
        self.assertEqual(hints, [])

    # User value: ensures proxy guard rescues likely false-low scores even when text length is short.
    def test_apply_guard_rules_proxy_floor_for_short_text(self):
        guards = {
            "clean_text_min_chars": 200,
            "clean_text_garbage_max": 0.12,
            "clean_text_char_conf_min": 0.78,
            "clean_text_floor": 0.65,
            "hint_suppress_density_min": 0.35,
            "clean_proxy_density_min": 0.04,
            "clean_proxy_floor": 0.62,
            "sparse_clean_density_max": 0.25,
            "sparse_clean_bonus": 0.08,
            "dense_clean_bonus": 0.08,
            "dense_clean_char_conf_min": 0.90,
            "dense_clean_garbage_max": 0.05,
            "dense_clean_density_min": 0.15,
            "dense_blur_density_min": 0.70,
            "dense_blur_min": 0.80,
            "dense_blur_penalty": 0.10,
            "dense_blur_penalty_noise_min": 0.08,
        }
        metrics = {
            "char_conf_proxy": 0.84,
            "contrast_score": 0.11,
            "blur_score": 0.98,
            "text_density_score": 0.05,
            "garbage_ratio": 0.11,
        }
        score, _ = apply_guard_rules(
            score=0.42,
            metrics=metrics,
            hints=["Image appears blurry", "Low contrast detected"],
            text="short text",
            guards=guards,
        )
        self.assertEqual(score, 0.70)

    # User value: keeps dense blurry scans from over-scoring due text volume.
    def test_dense_blur_penalty_applies(self):
        guards = {
            "clean_text_min_chars": 20,
            "clean_text_garbage_max": 0.12,
            "clean_text_char_conf_min": 0.78,
            "clean_text_floor": 0.65,
            "hint_suppress_density_min": 0.35,
            "clean_proxy_density_min": 0.04,
            "clean_proxy_floor": 0.62,
            "sparse_clean_density_max": 0.25,
            "sparse_clean_bonus": 0.08,
            "dense_clean_bonus": 0.08,
            "dense_clean_char_conf_min": 0.90,
            "dense_clean_garbage_max": 0.05,
            "dense_clean_density_min": 0.15,
            "dense_blur_density_min": 0.70,
            "dense_blur_min": 0.80,
            "dense_blur_penalty": 0.10,
            "dense_blur_penalty_noise_min": 0.08,
        }
        metrics = {
            "char_conf_proxy": 0.84,
            "contrast_score": 0.90,
            "blur_score": 0.86,
            "text_density_score": 0.95,
            "garbage_ratio": 0.11,
        }
        score, _ = apply_guard_rules(
            score=0.91,
            metrics=metrics,
            hints=[],
            text="Dense readable text " * 20,
            guards=guards,
        )
        self.assertEqual(score, 0.81)

    # User value: ensures dense clean text is not penalized by blur-only proxy noise.
    def test_dense_clean_bonus_prevents_unfair_drop(self):
        guards = {
            "clean_text_min_chars": 20,
            "clean_text_garbage_max": 0.12,
            "clean_text_char_conf_min": 0.78,
            "clean_text_floor": 0.65,
            "hint_suppress_density_min": 0.35,
            "clean_proxy_density_min": 0.04,
            "clean_proxy_floor": 0.62,
            "sparse_clean_density_max": 0.25,
            "sparse_clean_bonus": 0.08,
            "dense_clean_bonus": 0.08,
            "dense_clean_char_conf_min": 0.90,
            "dense_clean_garbage_max": 0.05,
            "dense_clean_density_min": 0.15,
            "dense_blur_density_min": 0.70,
            "dense_blur_min": 0.80,
            "dense_blur_penalty": 0.10,
            "dense_blur_penalty_noise_min": 0.08,
        }
        metrics = {
            "char_conf_proxy": 0.95,
            "contrast_score": 0.45,
            "blur_score": 0.88,
            "text_density_score": 0.80,
            "garbage_ratio": 0.02,
        }
        score, _ = apply_guard_rules(
            score=0.72,
            metrics=metrics,
            hints=["Image appears blurry"],
            text="Clear dense content " * 30,
            guards=guards,
        )
        self.assertEqual(score, 0.80)

    # User value: validates offline recalibration can learn better weights from labeled examples.
    def test_recalibrate_weights_improves_mae(self):
        samples = [
            {
                "metrics": {
                    "char_conf_proxy": 0.9,
                    "text_density_score": 0.8,
                    "contrast_score": 0.4,
                    "blur_score": 0.6,
                    "garbage_ratio": 0.1,
                },
                "target_score": 0.75,
            },
            {
                "metrics": {
                    "char_conf_proxy": 0.7,
                    "text_density_score": 0.2,
                    "contrast_score": 0.2,
                    "blur_score": 0.9,
                    "garbage_ratio": 0.3,
                },
                "target_score": 0.35,
            },
        ]
        baseline = 0.0
        for sample in samples:
            baseline += abs(score_from_metrics(sample["metrics"], {
                "char_conf_proxy": 0.30,
                "text_density_score": 0.20,
                "contrast_score": 0.20,
                "blur_quality_score": 0.15,
                "noise_quality_score": 0.15,
            }) - sample["target_score"])
        baseline /= len(samples)

        weights, mae = recalibrate_weights(samples, step=0.1, spread=0.1)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=4)
        self.assertLessEqual(mae, baseline)


if __name__ == "__main__":
    unittest.main()
