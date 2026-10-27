import unittest
import numpy as np
from basketball.tracking.ball_tracker import BallTracker, load_yolo


class TestBallTracker(unittest.TestCase):
    def _create_test_tracker(self, weights_path=None):
        tracker = BallTracker(weights_path=weights_path)
        tracker.rim_supported = True
        tracker.mode = "custom"
        return tracker

    def test_load_yolo_dynamic_weights(self):
        try:
            import ultralytics
        except ImportError:
            self.skipTest("ultralytics not installed (optional YOLO dependency)")
        model, mode, ball_cls, rim_cls = load_yolo("models/best.pt")
        self.assertIsNotNone(model, "Should load models/best.pt")
        self.assertEqual(mode, "custom")
        # models/best.pt has classes: 0: basketball, 1: rim, 2: sports ball
        self.assertTrue(len(ball_cls) > 0, "Should resolve ball classes")
        self.assertTrue(len(rim_cls) > 0, "Should resolve rim classes")
        self.assertIn(0, ball_cls)
        self.assertIn(1, rim_cls)

    def test_load_yolo_fallback_nonexistent(self):
        # Nonexistent custom path should fallback to best.pt or yolov8n without crashing
        model, mode, ball_cls, rim_cls = load_yolo("nonexistent_path/fake.pt")
        self.assertIn(mode, ["custom", "coco", "unavailable"])

    def test_advisory_outcome_qualified_make(self):
        """Side 1A: N >= 4, rim detected, R^2 >= 0.70, passes near rim -> make."""
        tracker = self._create_test_tracker()
        self.assertTrue(tracker.rim_supported)

        tracker.on_shot_started("shot_make_qual", frame_idx=10, timestamp_ms=333)
        tracker.on_shot_release("shot_make_qual", frame_idx=25, timestamp_ms=833)

        rim_box = [480.0, 290.0, 520.0, 310.0]  # center (500, 300)

        # Inverted image coordinates: ball ascends (y drops to 150 at x=350), then descends to (500, 320)
        xs = [200.0, 250.0, 300.0, 350.0, 400.0, 450.0, 500.0]
        for x in xs:
            # Vertex at (350, 150), reaches (500, 318.75) which is vertically below rim center at (500, 300)
            y = 0.0075 * ((x - 350.0) ** 2) + 150.0
            ball_box = [x - 15.0, y - 15.0, x + 15.0, y + 15.0]
            detections = {
                "ball": ball_box,
                "rim": rim_box,
                "ball_conf": 0.85,
                "rim_conf": 0.90,
                "rim_status": "CONFIRMED_RIM"
            }
            tracker.update(detections, landmarks=None, timestamp_ms=int(x * 10))

        summary = tracker.on_shot_ended("shot_make_qual", frame_idx=45, timestamp_ms=1500)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["shot_id"], "shot_make_qual")
        self.assertGreaterEqual(summary["flight_points_count"], 4)
        self.assertIsNotNone(summary["trajectory_fit_r2"])
        self.assertGreaterEqual(summary["trajectory_fit_r2"], 0.70)
        self.assertEqual(summary["outcome"], "make")
        self.assertEqual(summary["outcome_reason"], "TRAJECTORY_ENTRY_CONFIRMED")
        self.assertGreaterEqual(summary["outcome_conf"], 0.70)

    def test_advisory_outcome_qualified_miss(self):
        """Side 1B: N >= 4, rim detected, R^2 >= 0.70, misses rim alignment -> miss."""
        tracker = self._create_test_tracker()
        tracker.on_shot_started("shot_miss_qual", frame_idx=10, timestamp_ms=333)
        tracker.on_shot_release("shot_miss_qual", frame_idx=25, timestamp_ms=833)

        # Rim at x=600, y=300
        rim_box = [580.0, 290.0, 620.0, 310.0]

        # Ball trajectory lands at x=400 (far to the left of rim at 600)
        xs = [200.0, 240.0, 280.0, 320.0, 360.0, 400.0]
        for x in xs:
            y = 0.01 * ((x - 300.0) ** 2) + 180.0
            ball_box = [x - 15.0, y - 15.0, x + 15.0, y + 15.0]
            detections = {
                "ball": ball_box,
                "rim": rim_box,
                "ball_conf": 0.85,
                "rim_conf": 0.90,
                "rim_status": "CONFIRMED_RIM"
            }
            tracker.update(detections, landmarks=None, timestamp_ms=int(x * 10))

        summary = tracker.on_shot_ended("shot_miss_qual", frame_idx=45, timestamp_ms=1500)
        self.assertIsNotNone(summary)
        self.assertGreaterEqual(summary["trajectory_fit_r2"], 0.70)
        self.assertEqual(summary["outcome"], "miss")
        self.assertEqual(summary["outcome_reason"], "MISSED_TRAJECTORY_ALIGNMENT")

    def test_advisory_outcome_rejected_poor_trajectory_fit(self):
        """Side 2A: R^2 < 0.70 -> unknown with POOR_TRAJECTORY_FIT."""
        tracker = self._create_test_tracker()
        tracker.on_shot_started("shot_noisy", frame_idx=10)
        tracker.on_shot_release("shot_noisy", frame_idx=20)

        rim_box = [480.0, 290.0, 520.0, 310.0]

        # Zig-zag jittery coordinates that fail parabolic R^2 threshold
        noisy_pts = [
            (200.0, 300.0),
            (250.0, 100.0),
            (300.0, 450.0),
            (350.0, 120.0),
            (400.0, 390.0),
            (450.0, 180.0)
        ]
        for x, y in noisy_pts:
            ball_box = [x - 10.0, y - 10.0, x + 10.0, y + 10.0]
            detections = {
                "ball": ball_box,
                "rim": rim_box,
                "ball_conf": 0.80,
                "rim_conf": 0.85,
                "rim_status": "CONFIRMED_RIM"
            }
            tracker.update(detections, landmarks=None)

        summary = tracker.on_shot_ended("shot_noisy", frame_idx=40)
        self.assertIsNotNone(summary)
        # Verify R^2 is below 0.70 and outcome is unknown
        r2 = summary.get("trajectory_fit_r2")
        self.assertTrue(r2 is None or r2 < 0.70)
        self.assertEqual(summary["outcome"], "unknown")
        self.assertEqual(summary["outcome_reason"], "POOR_TRAJECTORY_FIT")

    def test_advisory_outcome_rejected_insufficient_points(self):
        """Side 2B: N < 4 points -> unknown with INSUFFICIENT_FLIGHT_POINTS."""
        tracker = self._create_test_tracker()
        tracker.on_shot_started("shot_few_pts", frame_idx=10)
        tracker.on_shot_release("shot_few_pts", frame_idx=20)

        rim_box = [480.0, 290.0, 520.0, 310.0]
        # Only 2 points
        for x in [200.0, 250.0]:
            ball_box = [x - 10, 200 - 10, x + 10, 200 + 10]
            tracker.update({"ball": ball_box, "rim": rim_box, "ball_conf": 0.8, "rim_conf": 0.85}, landmarks=None)

        summary = tracker.on_shot_ended("shot_few_pts", frame_idx=30)
        self.assertEqual(summary["outcome"], "unknown")
        self.assertEqual(summary["outcome_reason"], "INSUFFICIENT_FLIGHT_POINTS")

    def test_advisory_outcome_rejected_no_rim_detected(self):
        """Side 2C: Rim not detected -> unknown with RIM_NOT_DETECTED."""
        tracker = self._create_test_tracker()
        tracker.on_shot_started("shot_no_rim", frame_idx=10)
        tracker.on_shot_release("shot_no_rim", frame_idx=20)

        # 6 valid points, but rim is None
        for x in [200.0, 250.0, 300.0, 350.0, 400.0, 450.0]:
            y = 0.005 * ((x - 300.0) ** 2) + 150.0
            ball_box = [x - 10, y - 10, x + 10, y + 10]
            tracker.update({"ball": ball_box, "rim": None, "ball_conf": 0.85, "rim_conf": 0.0}, landmarks=None)

        summary = tracker.on_shot_ended("shot_no_rim", frame_idx=40)
        self.assertEqual(summary["outcome"], "unknown")
        self.assertEqual(summary["outcome_reason"], "RIM_NOT_DETECTED")

    def test_advisory_outcome_rejected_unavailable_weights(self):
        """Side 2D: Weights not loaded / rim unsupported -> unknown with UNAVAILABLE_NO_WEIGHTS."""
        tracker = BallTracker(weights_path="nonexistent/dummy.pt")
        tracker.rim_supported = False
        tracker.on_shot_started("shot_unavail", frame_idx=10)
        tracker.on_shot_release("shot_unavail", frame_idx=20)

        for x in [200.0, 250.0, 300.0, 350.0]:
            tracker.update({"ball": [x, 100, x + 20, 120], "ball_conf": 0.8}, landmarks=None)

        summary = tracker.on_shot_ended("shot_unavail", frame_idx=35)
        self.assertEqual(summary["outcome"], "unknown")
        self.assertEqual(summary["outcome_reason"], "UNAVAILABLE_NO_WEIGHTS")


if __name__ == "__main__":
    unittest.main()
