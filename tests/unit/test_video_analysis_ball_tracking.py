"""Unit tests for ball & rim tracking in video_analysis_service."""

import gzip
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import cv2
import numpy as np

from basketball.services.video_analysis_service import analyze_video
from basketball.tracking.ball_tracker import BallTracker


def _create_synthetic_video(path: str, frames: int = 40, size: tuple = (320, 240), fps: float = 30.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, size)
    for i in range(frames):
        img = np.full((size[1], size[0], 3), (i * 5) % 256, dtype=np.uint8)
        writer.write(img)
    writer.release()


def _mock_pose_dict():
    # Construct a realistic synthetic pose where wrists, elbows, knees, hips have valid numeric coordinates
    res = {}
    for i in range(33):
        res[i] = {
            "norm_x": 0.5,
            "norm_y": 0.5,
            "visibility": 0.95,
            "presence": 0.95,
            "world_x": 0.0,
            "world_y": 0.0,
            "world_z": 0.0,
        }
    # Shoulders
    res[11]["norm_y"] = 0.40; res[12]["norm_y"] = 0.40
    # Elbows
    res[13]["norm_y"] = 0.30; res[14]["norm_y"] = 0.30
    # Wrists (shooting wrist slightly above left wrist)
    res[15]["norm_y"] = 0.20; res[16]["norm_y"] = 0.15
    # Hips
    res[23]["norm_y"] = 0.60; res[24]["norm_y"] = 0.60
    # Knees
    res[25]["norm_y"] = 0.80; res[26]["norm_y"] = 0.80
    # Ankles
    res[27]["norm_y"] = 0.98; res[28]["norm_y"] = 0.98
    return res


def _mock_valid():
    return {i: True for i in range(33)}


class TestVideoAnalysisBallTracking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_bt_vas_")
        self.clip_path = os.path.join(self.temp_dir, "test_clip.mp4")
        _create_synthetic_video(self.clip_path, frames=45, size=(320, 240), fps=30.0)
        self.db_path = os.path.join(self.temp_dir, "test_db.sqlite")
        self.pose_cache_dir = os.path.join(self.temp_dir, "pose_cache")
        os.makedirs(self.pose_cache_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ball_tracker_update_signature_compatibility(self):
        """BallTracker.update accepts detections, landmarks, valid, timestamp_ms without TypeError."""
        tracker = BallTracker()
        detections = {
            "ball": [10.0, 10.0, 20.0, 20.0],
            "ball_conf": 0.9,
            "rim": [100.0, 50.0, 140.0, 70.0],
            "rim_conf": 0.85,
        }
        res = tracker.update(detections, landmarks={11: {"norm_x": 0.5, "norm_y": 0.5}}, valid=True, timestamp_ms=33)
        self.assertIsInstance(res, dict)

        res2 = tracker.update(detections, landmarks=None, valid=None, timestamp_ms=66)
        self.assertIsInstance(res2, dict)

    @patch("basketball.tracking.ball_tracker.BallTracker")
    @patch("basketball.services.video_analysis_service.PoseEngine")
    def test_analyze_video_caches_ball_rim_frames(self, mock_pose_cls, mock_bt_cls):
        """analyze_video saves per-frame ball and rim tracking into pose cache .json.gz."""
        mock_pose = MagicMock()
        mock_pose.process.return_value = {
            "valid": _mock_valid(),
            "landmarks": _mock_pose_dict(),
            "smoothed_landmarks": _mock_pose_dict(),
            "world_landmarks": _mock_pose_dict(),
        }
        mock_pose_cls.return_value = mock_pose

        mock_tracker = MagicMock()
        mock_tracker.mode = "custom"
        mock_tracker.detect.return_value = {
            "ball": [150.0, 120.0, 170.0, 140.0],
            "ball_conf": 0.88,
            "rim": [280.0, 40.0, 310.0, 60.0],
            "rim_conf": 0.92,
            "rim_status": "CONFIRMED_RIM",
        }
        mock_tracker.update.return_value = {}
        mock_bt_cls.return_value = mock_tracker

        cache_file = os.path.join(self.pose_cache_dir, "test_session.json.gz")
        res = analyze_video(
            video_path=self.clip_path,
            db_path=self.db_path,
            session_id="test_session",
            player_id="test_player",
            camera_view="side",
            shot_type="jump_shot",
            shot_style="jump_shot",
            pose_cache_path=cache_file,
        )

        self.assertIn("ball_rim_tracking", res)
        self.assertTrue(os.path.exists(cache_file), "Pose cache .json.gz must be created")

        with gzip.open(cache_file, "rt", encoding="utf-8") as f:
            cache_data = json.load(f)

        self.assertIn("ball_rim", cache_data)
        ball_rim = cache_data["ball_rim"]
        self.assertEqual(len(ball_rim), 45, "Should have tracking data for all 45 frames")
        self.assertIsNotNone(ball_rim[0]["ball"])
        self.assertEqual(ball_rim[0]["ball_conf"], 0.88)
        self.assertIsNotNone(ball_rim[0]["rim"])
        self.assertEqual(ball_rim[0]["rim_conf"], 0.92)

    @patch("basketball.tracking.ball_tracker.BallTracker")
    @patch("basketball.services.video_analysis_service.PoseEngine")
    @patch("basketball.services.video_analysis_service.ShotPhaseDetector")
    @patch("basketball.services.video_analysis_service.SessionRecorder")
    def test_flight_tracking_and_auto_make_proposal(self, mock_rec_cls, mock_fsm_cls, mock_pose_cls, mock_bt_cls):
        """When ball tracker detects a qualified make, the proposed shot proposal sets automated_outcome."""
        mock_rec = MagicMock()
        mock_rec.recording = False
        def start_shot():
            mock_rec.recording = True
        mock_rec.start_shot.side_effect = start_shot
        mock_rec.end_shot.return_value = {
            "sequence_lag_ms": 120.0,
            "elbow_at_release": 165.0,
            "elbow_angle_release_3d": 165.0,
            "avg_elbow_shooting_2d": 160.0,
            "knee_at_dip": 110.0,
            "std_hip_shooting": 2.0,
        }
        mock_rec_cls.return_value = mock_rec

        mock_fsm = MagicMock()
        # Step through:
        # frames 0-4: idle
        # frames 5-8: preparing
        # frames 9-11: set_point
        # frames 12-16: releasing
        # frames 17-21: follow_through
        # frames 22+: idle
        phase_sequence = (
            ["idle"] * 5 +
            ["preparing"] * 4 +
            ["set_point"] * 3 +
            ["releasing"] * 5 +
            ["follow_through"] * 5 +
            ["idle"] * 23
        )
        call_count = [0]
        def detector_step(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            phase = phase_sequence[idx] if idx < len(phase_sequence) else "idle"
            return (phase, 0.0, False)

        mock_fsm.update.side_effect = detector_step
        mock_fsm_cls.return_value = mock_fsm

        mock_pose = MagicMock()
        mock_pose.process.return_value = {
            "valid": _mock_valid(),
            "landmarks": _mock_pose_dict(),
            "smoothed_landmarks": _mock_pose_dict(),
            "world_landmarks": _mock_pose_dict(),
        }
        mock_pose_cls.return_value = mock_pose

        mock_tracker = MagicMock()
        mock_tracker.mode = "custom"
        mock_tracker.detect.return_value = {
            "ball": [150.0, 120.0, 170.0, 140.0],
            "ball_conf": 0.88,
            "rim": [280.0, 40.0, 310.0, 60.0],
            "rim_conf": 0.92,
        }
        mock_tracker.on_shot_ended.return_value = {
            "outcome": "make",
            "outcome_conf": 0.85,
            "outcome_reason": "ball_under_rim",
            "trajectory_fit_r2": 0.91,
            "entry_angle": 46.2,
            "ball_coverage_ratio": 0.80,
            "flight_centers": [[150, 120], [200, 80], [280, 50]],
        }
        mock_bt_cls.return_value = mock_tracker

        cache_file = os.path.join(self.pose_cache_dir, "test_flight_session.json.gz")
        res = analyze_video(
            video_path=self.clip_path,
            db_path=self.db_path,
            session_id="test_flight_session",
            player_id="test_player",
            camera_view="side",
            shot_type="jump_shot",
            shot_style="jump_shot",
            pose_cache_path=cache_file,
        )

        from basketball.persistence.shot_lab_db import ShotLabDB
        db = ShotLabDB(self.db_path)
        shots = db.get_shots(session_id="test_flight_session")
        self.assertGreaterEqual(len(shots), 1, "A shot proposal must be persisted")
        shot = shots[0]

        # Verify automated outcome fields
        self.assertEqual(shot["automated_outcome"], "make")
        self.assertAlmostEqual(shot["automated_outcome_conf"], 0.85, places=2)
        self.assertAlmostEqual(shot["trajectory_fit_r2"], 0.91, places=2)
        self.assertEqual(shot["outcome"], "make")
        self.assertEqual(shot["outcome_source"], "automated_trajectory")
        self.assertEqual(shot["review_status"], "quarantined")
        self.assertIn("1 makes", res["outcomes"]["automated"])

    @patch("basketball.tracking.ball_tracker.BallTracker")
    @patch("basketball.services.video_analysis_service.PoseEngine")
    @patch("basketball.services.video_analysis_service.ShotPhaseDetector")
    @patch("basketball.services.video_analysis_service.SessionRecorder")
    def test_flight_tracking_and_auto_miss_proposal(self, mock_rec_cls, mock_fsm_cls, mock_pose_cls, mock_bt_cls):
        """When ball tracker detects a qualified miss (R2>=0.70, conf>=0.70), automated_outcome is miss."""
        mock_rec = MagicMock()
        mock_rec.recording = False
        def start_shot():
            mock_rec.recording = True
        mock_rec.start_shot.side_effect = start_shot
        mock_rec.end_shot.return_value = {
            "sequence_lag_ms": 115.0,
            "elbow_at_release": 162.0,
            "elbow_angle_release_3d": 162.0,
            "avg_elbow_shooting_2d": 158.0,
            "knee_at_dip": 112.0,
            "std_hip_shooting": 2.1,
        }
        mock_rec_cls.return_value = mock_rec

        mock_fsm = MagicMock()
        phase_sequence = ["idle"] * 5 + ["preparing"] * 4 + ["set_point"] * 3 + ["releasing"] * 5 + ["follow_through"] * 5 + ["idle"] * 23
        call_count = [0]
        def detector_step(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            phase = phase_sequence[idx] if idx < len(phase_sequence) else "idle"
            return (phase, 0.0, False)

        mock_fsm.update.side_effect = detector_step
        mock_fsm_cls.return_value = mock_fsm

        mock_pose = MagicMock()
        mock_pose.process.return_value = {
            "valid": _mock_valid(),
            "landmarks": _mock_pose_dict(),
            "smoothed_landmarks": _mock_pose_dict(),
            "world_landmarks": _mock_pose_dict(),
        }
        mock_pose_cls.return_value = mock_pose

        mock_tracker = MagicMock()
        mock_tracker.mode = "custom"
        mock_tracker.detect.return_value = {
            "ball": [150.0, 120.0, 170.0, 140.0],
            "ball_conf": 0.88,
            "rim": [280.0, 40.0, 310.0, 60.0],
            "rim_conf": 0.92,
        }
        mock_tracker.on_shot_ended.return_value = {
            "outcome": "miss",
            "outcome_conf": 0.82,
            "outcome_reason": "MISSED_TRAJECTORY_ALIGNMENT",
            "trajectory_fit_r2": 0.89,
            "entry_angle": 42.0,
            "ball_coverage_ratio": 0.80,
            "flight_centers": [[150, 120], [200, 80], [280, 50]],
        }
        mock_bt_cls.return_value = mock_tracker

        res = analyze_video(
            video_path=self.clip_path,
            db_path=self.db_path,
            session_id="test_miss_session",
            player_id="test_player",
            camera_view="side",
            shot_type="jump_shot",
            shot_style="jump_shot",
        )

        from basketball.persistence.shot_lab_db import ShotLabDB
        db = ShotLabDB(self.db_path)
        shots = db.get_shots(session_id="test_miss_session")
        self.assertGreaterEqual(len(shots), 1)
        shot = shots[0]

        self.assertEqual(shot["automated_outcome"], "miss")
        self.assertAlmostEqual(shot["automated_outcome_conf"], 0.82, places=2)
        self.assertAlmostEqual(shot["trajectory_fit_r2"], 0.89, places=2)
        self.assertEqual(shot["outcome"], "miss")
        self.assertEqual(shot["outcome_source"], "automated_trajectory")
        self.assertEqual(shot["review_status"], "quarantined")
        self.assertIn("1 misses", res["outcomes"]["automated"])

    @patch("basketball.tracking.ball_tracker.BallTracker")
    @patch("basketball.services.video_analysis_service.PoseEngine")
    @patch("basketball.services.video_analysis_service.ShotPhaseDetector")
    @patch("basketball.services.video_analysis_service.SessionRecorder")
    def test_low_conf_preserves_unknown_outcome(self, mock_rec_cls, mock_fsm_cls, mock_pose_cls, mock_bt_cls):
        """When trajectory R^2 or confidence is low, shot outcome stays unknown."""
        mock_rec = MagicMock()
        mock_rec.recording = False
        def start_shot():
            mock_rec.recording = True
        mock_rec.start_shot.side_effect = start_shot
        mock_rec.end_shot.return_value = {
            "sequence_lag_ms": 120.0,
            "elbow_at_release": 165.0,
            "elbow_angle_release_3d": 165.0,
            "avg_elbow_shooting_2d": 160.0,
            "knee_at_dip": 110.0,
            "std_hip_shooting": 2.0,
        }
        mock_rec_cls.return_value = mock_rec

        mock_fsm = MagicMock()
        phase_sequence = ["idle"] * 5 + ["preparing"] * 4 + ["set_point"] * 3 + ["releasing"] * 5 + ["follow_through"] * 5 + ["idle"] * 23
        call_count = [0]
        def detector_step(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            phase = phase_sequence[idx] if idx < len(phase_sequence) else "idle"
            return (phase, 0.0, False)

        mock_fsm.update.side_effect = detector_step
        mock_fsm_cls.return_value = mock_fsm

        mock_pose = MagicMock()
        mock_pose.process.return_value = {
            "valid": _mock_valid(),
            "landmarks": _mock_pose_dict(),
            "smoothed_landmarks": _mock_pose_dict(),
            "world_landmarks": _mock_pose_dict(),
        }
        mock_pose_cls.return_value = mock_pose

        mock_tracker = MagicMock()
        mock_tracker.mode = "custom"
        mock_tracker.detect.return_value = {"ball": None, "rim": None, "ball_conf": 0.0, "rim_conf": 0.0}
        mock_tracker.on_shot_ended.return_value = {
            "outcome": "unknown",
            "outcome_conf": 0.40,
            "outcome_reason": "POOR_TRAJECTORY_FIT",
            "trajectory_fit_r2": 0.45,
            "entry_angle": None,
            "ball_coverage_ratio": 0.20,
            "flight_centers": [],
        }
        mock_bt_cls.return_value = mock_tracker

        res = analyze_video(
            video_path=self.clip_path,
            db_path=self.db_path,
            session_id="test_low_conf_session",
            player_id="test_player",
            camera_view="side",
            shot_type="jump_shot",
            shot_style="jump_shot",
        )

        from basketball.persistence.shot_lab_db import ShotLabDB
        db = ShotLabDB(self.db_path)
        shots = db.get_shots(session_id="test_low_conf_session")
        self.assertGreaterEqual(len(shots), 1)
        shot = shots[0]

        self.assertEqual(shot["automated_outcome"], "unknown")
        self.assertEqual(shot["outcome"], "unknown")
        self.assertEqual(shot["outcome_source"], "unlabeled")
        self.assertEqual(shot["review_status"], "quarantined")


if __name__ == "__main__":
    unittest.main()
