"""
test_shot_models_flow.py - Integration tests for the full Shot-Event Model & Verification pipeline.
Validates end-to-end synchronization, feature extraction, calibration, ML sequence modeling,
benchmarking evaluation, and proposal generation flow.
"""

import os
import json
import tempfile
import unittest
import numpy as np

from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from scripts.sync_split_annotations import sync_annotations_to_db
except ImportError:
    from sync_split_annotations import sync_annotations_to_db
from basketball.core.shot_feature_extractor import ShotFeatureExtractor
from basketball.tracking.calibrated_fsm import CalibratedFSMDetector, optimize_fsm_parameters
from basketball.tracking.shot_detector_ml import MLSequenceDetector
try:
    from evaluation.evaluate_shot_models import match_events, evaluate_detector_on_kinematics
except ImportError:
    from evaluate_shot_models import match_events, evaluate_detector_on_kinematics


class TestShotModelsFlow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "flow_shot_lab.db")
        self.db = ShotLabDB(self.db_path)

        # Create dummy video clip
        self.raw_dir = os.path.join(self.tmp_dir.name, "raw_clips")
        os.makedirs(self.raw_dir, exist_ok=True)
        self.video_path = os.path.join(self.raw_dir, "sid_1.mp4")
        with open(self.video_path, "wb") as f:
            f.write(b"\x00" * 4096)

        # Create ground truth annotations JSON
        self.ann_path = os.path.join(self.tmp_dir.name, "test_annotations.json")
        self.gt_data = {
            "version": "1.0.0",
            "clips": [
                {
                    "clip_id": "sid_1",
                    "file": self.video_path,
                    "metadata": {
                        "player_id": "sid",
                        "camera_view": "side_90",
                        "fps": 30.0
                    },
                    "shots": [
                        {
                            "shot_id": "shot_sid_1_0",
                            "events": {
                                "shot_start_frame": 10,
                                "peak_dip_frame": 20,
                                "set_point_frame": 35,
                                "release_frame": 45,
                                "follow_through_frame": 55
                            },
                            "outcome": {
                                "result": "made",
                                "rim_contact": "swish"
                            }
                        }
                    ]
                }
            ]
        }
        with open(self.ann_path, "w", encoding="utf-8") as f:
            json.dump(self.gt_data, f)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _generate_synthetic_kinematic_frames(self, total_frames=70, fps=30.0):
        frames = []
        for f in range(total_frames):
            if f < 10:
                k = {"wrist_v_y": 0.0, "wrist_a_y": 0.0, "rel_shoulder": 0.20, "rel_nose": 0.0, "elbow_angle": 90.0, "knee_angle": 175.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}
            elif f < 20:
                k = {"wrist_v_y": 0.1, "wrist_a_y": 0.0, "rel_shoulder": 0.10, "rel_nose": -0.1, "elbow_angle": 85.0, "knee_angle": 145.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}
            elif f < 30:
                k = {"wrist_v_y": -0.3, "wrist_a_y": -0.1, "rel_shoulder": -0.05, "rel_nose": -0.25, "elbow_angle": 100.0, "knee_angle": 155.0, "elbow_v_ang": 50.0, "knee_v_ang": 45.0}
            elif f < 46:
                v_burst = -1.2 if f == 45 else -0.8
                k = {"wrist_v_y": v_burst, "wrist_a_y": -0.2, "rel_shoulder": -0.25, "rel_nose": -0.45, "elbow_angle": 130.0, "knee_angle": 170.0, "elbow_v_ang": 90.0, "knee_v_ang": 50.0}
            elif f < 55:
                k = {"wrist_v_y": -0.1, "wrist_a_y": 0.0, "rel_shoulder": -0.30, "rel_nose": -0.50, "elbow_angle": 160.0, "knee_angle": 175.0, "elbow_v_ang": 10.0, "knee_v_ang": 0.0}
            else:
                k = {"wrist_v_y": 0.0, "wrist_a_y": 0.0, "rel_shoulder": 0.20, "rel_nose": 0.0, "elbow_angle": 90.0, "knee_angle": 175.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}

            k["frame_idx"] = f
            k["timestamp_ms"] = int(f * (1000.0 / fps))
            k["is_valid"] = True
            frames.append(k)
        return frames

    def test_end_to_end_pipeline_flow(self):
        # 1. Synchronize ground truth to SQLite DB
        synced = sync_annotations_to_db(self.ann_path, self.db_path, export_after_sync=False)
        self.assertEqual(synced["clips_synced"], 1)

        # Verify expert annotation exists in DB
        clip_anns = self.db.get_clip_annotations("sid_1")["intervals"]
        self.assertEqual(len(clip_anns), 1)
        self.assertEqual(clip_anns[0]["release_frame"], 45)

        # 2. Extract features using ShotFeatureExtractor
        extractor = ShotFeatureExtractor(default_fps=30.0)
        dummy_history = [
            {
                "frame_idx": f,
                "landmarks": {
                    "right_wrist": {"x": 0.5, "y": 0.5 - f * 0.01, "z": 0.0, "visibility": 0.9},
                    "right_shoulder": {"x": 0.5, "y": 0.4, "z": 0.0, "visibility": 0.9},
                    "right_hip": {"x": 0.5, "y": 0.7, "z": 0.0, "visibility": 0.9},
                    "nose": {"x": 0.5, "y": 0.3, "z": 0.0, "visibility": 0.9}
                },
                "angles": {"right_elbow": 90.0, "right_knee": 120.0}
            }
            for f in range(5)
        ]
        kinematics = extractor.extract_frame_kinematics(dummy_history, fps=30.0)
        self.assertIn("wrist_v_y", kinematics)
        self.assertIn("torso_scale", kinematics)

        # 3. Optimize Calibrated FSM Detector
        synthetic_frames = self._generate_synthetic_kinematic_frames(total_frames=80)
        training_data = [{
            "kinematics": synthetic_frames,
            "gt_release_frame": 45
        }]
        best_cfg = optimize_fsm_parameters(training_data)
        self.assertIn("min_upward_velocity", best_cfg)
        self.assertIn("wrist_rel_shoulder_thresh", best_cfg)

        # Instantiate FSM with calibrated thresholds
        fsm_detector = CalibratedFSMDetector(
            min_upward_velocity=best_cfg["min_upward_velocity"],
            wrist_rel_shoulder_thresh=best_cfg["wrist_rel_shoulder_thresh"],
            min_knee_dip_angle=best_cfg["min_knee_dip_angle"]
        )

        fsm_releases = []
        fsm_proposals = []
        for k_frame in synthetic_frames:
            _, prop = fsm_detector.update(k_frame["frame_idx"], k_frame)
            if prop:
                fsm_proposals.append(prop)
                fsm_releases.append(prop["release_frame"])

        self.assertGreaterEqual(len(fsm_proposals), 1)
        self.assertEqual(fsm_proposals[0]["detector_name"], "calibrated_fsm_detector")

        # 4. Fit and Predict ML Sequence Detector
        ml_detector = MLSequenceDetector(default_fps=30.0)
        # Create sliding window vectors for ML training
        X_samples = []
        y_samples = []
        for i in range(15, len(synthetic_frames)):
            w = synthetic_frames[i-15:i]
            feat_vec = extractor.extract_window_vector(w)
            # Positive if window contains release (frame 45)
            is_shot = 1 if (30 <= i <= 50) else 0
            X_samples.append(feat_vec)
            y_samples.append(is_shot)

        X_mat = np.array(X_samples, dtype=np.float32)
        y_vec = np.array(y_samples, dtype=np.int32)
        train_res = ml_detector.train(X_mat, y_vec)
        self.assertEqual(train_res["status"], "TRAINED")

        ml_releases = evaluate_detector_on_kinematics("ml_sequence", synthetic_frames, trained_ml=ml_detector)
        self.assertIsInstance(ml_releases, list)

        # 5. Evaluate Performance with Event Matching
        gt_releases = [clip_anns[0]["release_frame"]]
        tp, fp, fn, errors = match_events(fsm_releases, gt_releases, tolerance=15)
        self.assertEqual(tp, 1)
        self.assertEqual(len(errors), 1)
        self.assertLessEqual(errors[0], 15)

        # 6. Save and Verify Machine Proposals in DB
        self.db.save_machine_proposals("sid_1", fsm_proposals, detector_name="calibrated_fsm_detector", detector_version="2.0.0")
        stored_props = self.db.get_machine_proposals("sid_1")
        self.assertGreaterEqual(len(stored_props), 1)
        self.assertEqual(stored_props[0]["detector_name"], "calibrated_fsm_detector")


if __name__ == "__main__":
    unittest.main()
