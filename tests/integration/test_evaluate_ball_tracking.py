import os
import unittest
import json
import tempfile

try:
    from evaluation.evaluate_ball_tracking import compute_file_sha256, evaluate_video_ball_tracking
except ImportError:
    from evaluate_ball_tracking import compute_file_sha256, evaluate_video_ball_tracking


class TestEvaluateBallTracking(unittest.TestCase):
    def test_compute_file_sha256(self):
        if os.path.exists("models/best.pt"):
            sha = compute_file_sha256("models/best.pt")
            self.assertEqual(sha, "d3a52414eb0970661d98473663a858ce7c05db6d8a6e107a413d2c714231d43f")

    def test_evaluate_video_ball_tracking_short_clip(self):
        test_clip = "raw_clips/sid_4_97deg_wrim.mp4"
        if os.path.exists(test_clip) and os.path.exists("models/best.pt"):
            results = evaluate_video_ball_tracking(
                weights_path="models/best.pt",
                clips=[test_clip],
                max_frames_per_clip=15
            )
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertIn("ball_coverage_ratio", res)
            self.assertIn("rim_coverage_ratio", res)
            self.assertIn("advisory_outcome", res)
            self.assertIn(res["advisory_outcome"], ["make", "miss", "unknown"])
            self.assertIn("advisory_reason", res)
            # In short clip without full qualified trajectory, outcome must be unknown
            self.assertEqual(res["advisory_outcome"], "unknown")
            self.assertIn(res["advisory_reason"], [
                "RIM_NOT_DETECTED",
                "POOR_TRAJECTORY_FIT",
                "INSUFFICIENT_FLIGHT_POINTS",
                "UNAVAILABLE_NO_WEIGHTS"
            ])

    def test_evaluate_video_preserves_human_ground_truth(self):
        """Confirm that evaluate_video_ball_tracking reports ground truth without mutating it."""
        test_clip = "raw_clips/sid_4_97deg_wrim.mp4"
        if os.path.exists(test_clip) and os.path.exists("shot_lab.db"):
            results = evaluate_video_ball_tracking(
                weights_path="models/best.pt",
                clips=[test_clip],
                max_frames_per_clip=10
            )
            res = results[0]
            if "human_ground_truth_outcome" in res:
                self.assertIn(res["human_ground_truth_outcome"], ["make", "miss", "none", "unknown"])
                self.assertGreater(res.get("human_ground_truth_intervals_total", 0), 0)


if __name__ == "__main__":
    unittest.main()
