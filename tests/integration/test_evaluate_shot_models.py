"""
test_evaluate_shot_models.py - Unit tests for evaluate_shot_models.py
"""

import unittest
try:
    from evaluation.evaluate_shot_models import match_events
except ImportError:
    from evaluate_shot_models import match_events


class TestEvaluateShotModels(unittest.TestCase):
    def test_match_events_perfect_alignment(self):
        detected = [100, 200, 300]
        ground_truth = [100, 200, 300]

        tp, fp, fn, errors = match_events(detected, ground_truth, tolerance=15)
        self.assertEqual(tp, 3)
        self.assertEqual(fp, 0)
        self.assertEqual(fn, 0)
        self.assertEqual(errors, [0, 0, 0])

    def test_match_events_with_timing_error(self):
        detected = [105, 208]  # +5 frames, +8 frames
        ground_truth = [100, 200]

        tp, fp, fn, errors = match_events(detected, ground_truth, tolerance=15)
        self.assertEqual(tp, 2)
        self.assertEqual(fp, 0)
        self.assertEqual(fn, 0)
        self.assertEqual(errors, [5, 8])

    def test_match_events_false_positives_and_negatives(self):
        # One match, one false alarm (fp), one missed shot (fn)
        detected = [100, 400]
        ground_truth = [102, 250]

        tp, fp, fn, errors = match_events(detected, ground_truth, tolerance=15)
        self.assertEqual(tp, 1)  # 100 matched with 102
        self.assertEqual(fp, 1)  # 400 is FP
        self.assertEqual(fn, 1)  # 250 is FN
        self.assertEqual(errors, [2])


if __name__ == "__main__":
    unittest.main()
