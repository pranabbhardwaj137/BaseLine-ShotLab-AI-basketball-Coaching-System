import os
import unittest
import tempfile
import sqlite3

from basketball.persistence.shot_lab_db import ShotLabDB, SCHEMA_VERSION


class TestBallTrackingFlow(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        self.db = ShotLabDB(self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_schema_version_and_advisory_columns(self):
        # Phase 8 advanced the schema (v5 review history, v6 player settings);
        # the Phase 7 advisory columns must still exist in every later version.
        self.assertGreaterEqual(SCHEMA_VERSION, 4)
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(shots)")
            cols = {row["name"] for row in cursor.fetchall()}

            # Verify advisory columns exist in schema v4
            self.assertIn("automated_outcome", cols)
            self.assertIn("automated_outcome_conf", cols)
            self.assertIn("trajectory_fit_r2", cols)
            self.assertIn("entry_angle_deg", cols)
            self.assertIn("ball_coverage_ratio", cols)
            self.assertIn("ball_model_version", cols)

    def test_save_shot_preserves_human_ground_truth_and_advisory_metrics(self):
        session_id = self.db.create_session("test_player", "frontal", "catch_and_shoot")
        shot_data = {
            "session_id": session_id,
            "player_id": "test_player",
            "camera_view": "frontal",
            "shot_type": "catch_and_shoot",
            "shot_style": "jump_shot",
            "outcome": "make",                # Human ground-truth
            "outcome_source": "live_hotkey",
            "review_status": "approved",
            "tracking_confidence": "SUFFICIENT",
            # Advisory metrics from ball tracking
            "automated_outcome": "miss",      # Machine prediction differed
            "automated_outcome_conf": 0.82,
            "trajectory_fit_r2": 0.91,
            "entry_angle_deg": 48.5,
            "ball_coverage_ratio": 0.88,
            "ball_model_version": "yolov8n_best"
        }
        shot_id = self.db.save_shot(shot_data)

        # Retrieve and verify separation
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shots WHERE shot_id = ?", (shot_id,))
            row = cursor.fetchone()

            # Human ground truth must remain untouched
            self.assertEqual(row["outcome"], "make")
            self.assertEqual(row["review_status"], "approved")

            # Advisory metrics must be stored accurately
            self.assertEqual(row["automated_outcome"], "miss")
            self.assertEqual(row["automated_outcome_conf"], 0.82)
            self.assertAlmostEqual(row["trajectory_fit_r2"], 0.91, places=2)
            self.assertAlmostEqual(row["entry_angle_deg"], 48.5, places=1)
            self.assertAlmostEqual(row["ball_coverage_ratio"], 0.88, places=2)
            self.assertEqual(row["ball_model_version"], "yolov8n_best")

    def test_maybe_ball_tracker_default_and_toggle(self):
        try:
            import ultralytics
        except ImportError:
            self.skipTest("ultralytics not installed (optional YOLO dependency)")
        from basketball.app.main import maybe_ball_tracker
        tracker = maybe_ball_tracker(enabled=True, weights="models/best.pt", detect_every=1)
        self.assertIsNotNone(tracker)
        self.assertEqual(tracker.mode, "custom")
        self.assertTrue(tracker.rim_supported)

        disabled = maybe_ball_tracker(enabled=False, weights="models/best.pt", detect_every=1)
        self.assertIsNone(disabled)

    def test_main_cli_ball_tracking_flags(self):
        from basketball.app.main import build_parser
        parser = build_parser()

        # Default should enable ball tracking
        default_args = parser.parse_args([])
        self.assertTrue(default_args.ball)
        self.assertEqual(default_args.yolo, "models/best.pt")

        # Explicit --no-ball should disable
        no_ball_args = parser.parse_args(["--no-ball"])
        self.assertFalse(no_ball_args.ball)

        # Explicit --ball should enable
        ball_args = parser.parse_args(["--ball"])
        self.assertTrue(ball_args.ball)

    def test_pre_pose_ball_info_drawing(self):
        import numpy as np
        from basketball.tracking.ball_tracker import BallTracker

        tracker = BallTracker(weights_path="models/best.pt")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        detections = {
            "ball": [100.0, 100.0, 130.0, 130.0],
            "rim": [500.0, 200.0, 550.0, 220.0],
            "ball_conf": 0.85,
            "rim_conf": 0.90,
            "rim_status": "CONFIRMED_RIM",
        }

        # Structure as constructed in main.py when output is None
        ball_info = {
            "status": "no_pose",
            "mode": tracker.mode,
            "rim_status": tracker.rim_status,
            "ball": detections.get("ball"),
            "rim": detections.get("rim"),
            "ball_conf": detections.get("ball_conf", 0.0),
            "release_angle": None,
            "flight_centers": [],
        }

        # Should render bounding boxes onto frame without exception
        rendered_frame = tracker.draw(frame, ball_info)
        self.assertIsNotNone(rendered_frame)
        self.assertEqual(rendered_frame.shape, (480, 640, 3))


if __name__ == "__main__":
    unittest.main()
