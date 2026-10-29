"""Unit tests for LiveCameraEngine in live_service.py."""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from basketball.services.live_service import LiveCameraEngine


class LiveCameraServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = LiveCameraEngine(weights_path=None)

    def test_engine_initializes_gracefully_without_weights(self):
        self.assertEqual(self.engine.frame_index, 0)
        self.assertEqual(self.engine.session_total, 0)
        self.assertEqual(self.engine.current_phase, "idle")

    def test_process_synthetic_bgr_frame_returns_valid_schema(self):
        # Create a synthetic black frame (480x640x3)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = self.engine.process_frame(frame, client_timestamp_ms=1000)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["frame_size"], [640, 480])
        self.assertIn("pose", result)
        self.assertIn("ball", result)
        self.assertIn("rim", result)
        self.assertIn("shot", result)

        self.assertIsInstance(result["pose"]["landmarks"], list)
        self.assertIsInstance(result["ball"]["detected"], bool)
        self.assertIsInstance(result["rim"]["detected"], bool)
        self.assertEqual(result["shot"]["total"], 0)

    def test_monotonic_timestamp_handling(self):
        """Engine guarantees strictly increasing timestamps even if client sends duplicates or inverted clocks."""
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.engine.process_frame(frame, client_timestamp_ms=5000)
        self.assertEqual(self.engine.last_timestamp_ms, 5000)

        # Send same timestamp
        self.engine.process_frame(frame, client_timestamp_ms=5000)
        self.assertGreater(self.engine.last_timestamp_ms, 5000)

        # Send older timestamp
        prev_ts = self.engine.last_timestamp_ms
        self.engine.process_frame(frame, client_timestamp_ms=2000)
        self.assertGreater(self.engine.last_timestamp_ms, prev_ts)

    def test_reset_session_clears_metrics(self):
        self.engine.session_makes = 5
        self.engine.session_misses = 2
        self.engine.session_total = 7
        self.engine.last_shot_outcome = "make"

        reset_res = self.engine.reset_session()
        self.assertEqual(reset_res["makes"], 0)
        self.assertEqual(reset_res["misses"], 0)
        self.assertEqual(reset_res["total"], 0)
        self.assertEqual(reset_res["accuracy"], 0.0)

        self.assertEqual(self.engine.session_makes, 0)
        self.assertEqual(self.engine.session_misses, 0)
        self.assertEqual(self.engine.session_total, 0)
        self.assertIsNone(self.engine.last_shot_outcome)


    @patch("basketball.services.live_service.compute_all_angles")
    def test_compute_all_angles_receives_valid_and_world_landmarks_properly(self, mock_compute):
        """Verifies compute_all_angles receives keyword arguments for landmarks, valid, world_landmarks."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_landmarks = {
            24: {"x": 100, "y": 200, "z": 0.0, "visibility": 0.9, "norm_x": 0.5, "norm_y": 0.5},
        }
        dummy_valid = {24: True}
        dummy_world = {24: {"x": 0.1, "y": 0.5, "z": 0.1}}

        self.engine.pose_engine = MagicMock()
        self.engine.pose_engine.process.return_value = {
            "landmarks": dummy_landmarks,
            "valid": dummy_valid,
            "world_landmarks": dummy_world,
        }
        mock_compute.return_value = {
            "knee_shooting": 165.2,
            "elbow_shooting": 88.4,
        }

        result = self.engine.process_frame(frame, client_timestamp_ms=1000)

        mock_compute.assert_called_once()
        _, kwargs = mock_compute.call_args
        self.assertEqual(kwargs.get("landmarks"), dummy_landmarks)
        self.assertEqual(kwargs.get("valid"), dummy_valid)
        self.assertEqual(kwargs.get("world_landmarks"), dummy_world)
        self.assertEqual(kwargs.get("min_visibility"), 0.45)

        self.assertEqual(result["pose"]["knee_angle"], 165.2)
        self.assertEqual(result["pose"]["elbow_angle"], 88.4)

    def test_phase_detector_receives_angles_and_unpacks_string_phase(self):
        """Verifies phase_detector receives angles keyword arg and returns a string phase rather than a 3-tuple."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_landmarks = {
            24: {"x": 100, "y": 200, "z": 0.0, "visibility": 0.9, "norm_x": 0.5, "norm_y": 0.5},
        }
        self.engine.pose_engine = MagicMock()
        self.engine.pose_engine.process.return_value = {
            "landmarks": dummy_landmarks,
            "valid": {24: True},
            "world_landmarks": None,
        }

        mock_detector = MagicMock()
        mock_detector.update.return_value = ("gathering", 0.05, -2.1)
        self.engine.phase_detector = mock_detector

        result = self.engine.process_frame(frame, client_timestamp_ms=1200)

        mock_detector.update.assert_called_once()
        _, kwargs = mock_detector.update.call_args
        self.assertIn("angles", kwargs)
        self.assertIn("landmarks", kwargs)
        self.assertEqual(kwargs.get("timestamp_ms"), 1200)

        self.assertEqual(self.engine.current_phase, "gathering")
        self.assertIsInstance(self.engine.current_phase, str)
        self.assertEqual(result["pose"]["phase"], "gathering")
        self.assertIsInstance(result["pose"]["phase"], str)
        self.assertEqual(result["shot"]["phase"], "gathering")

    def test_shot_lifecycle_events_sent_to_ball_tracker(self):
        """Verifies ball_tracker receives lifecycle callbacks (started, release, ended) on phase transitions."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_landmarks = {
            24: {"x": 100, "y": 200, "z": 0.0, "visibility": 0.9, "norm_x": 0.5, "norm_y": 0.5},
        }
        self.engine.pose_engine = MagicMock()
        self.engine.pose_engine.process.return_value = {
            "landmarks": dummy_landmarks,
            "valid": {24: True},
        }

        mock_detector = MagicMock()
        self.engine.phase_detector = mock_detector

        mock_tracker = MagicMock()
        mock_tracker.detect.return_value = {
            "ball": [100, 100, 50, 50],
            "rim": [200, 50, 60, 20],
            "ball_conf": 0.85,
            "rim_conf": 0.90,
            "rim_status": "READY",
        }
        mock_tracker.update.return_value = {"status": "in_flight", "flight_centers": []}
        self.engine.ball_tracker = mock_tracker

        # Step 1: Transition to 'gathering' -> on_shot_started should fire
        mock_detector.update.return_value = ("gathering", 0.0, 0.0)
        self.engine.process_frame(frame, client_timestamp_ms=1000)
        mock_tracker.on_shot_started.assert_called_once_with("live_1000", 1, 1000)
        self.assertEqual(self.engine.active_shot_uid, "live_1000")

        # Step 2: Transition to 'releasing' -> on_shot_release should fire
        mock_detector.update.return_value = ("releasing", 0.1, 4.0)
        self.engine.process_frame(frame, client_timestamp_ms=1033)
        mock_tracker.on_shot_release.assert_called_once_with("live_1000", 2, 1033)

        # Step 3: Transition to 'idle' from releasing/follow_through -> on_shot_ended should fire
        mock_detector.update.return_value = ("idle", 0.0, 0.0)
        mock_tracker.on_shot_ended.return_value = {
            "outcome": "make",
            "outcome_conf": 0.85,
        }
        res3 = self.engine.process_frame(frame, client_timestamp_ms=1066)
        mock_tracker.on_shot_ended.assert_called_once_with("live_1000", 3, 1066)
        self.assertEqual(self.engine.last_shot_outcome, "make")
        self.assertEqual(self.engine.session_makes, 1)
        self.assertEqual(self.engine.session_total, 1)
        self.assertEqual(res3["shot"]["outcome"], "make")

    def test_missing_pose_produces_none_angles_and_idle_phase(self):
        """Verifies missing pose produces None for angles and 'idle' for phase without inventing data."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.engine.pose_engine = MagicMock()
        self.engine.pose_engine.process.return_value = None

        result = self.engine.process_frame(frame, client_timestamp_ms=1000)
        self.assertFalse(result["pose"]["detected"])
        self.assertIsNone(result["pose"]["knee_angle"])
        self.assertIsNone(result["pose"]["elbow_angle"])
        self.assertEqual(result["pose"]["phase"], "idle")


if __name__ == "__main__":
    unittest.main()
