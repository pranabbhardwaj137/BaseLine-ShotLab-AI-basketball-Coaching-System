"""
test_shot_feature_extractor.py - Unit tests for ShotFeatureExtractor.
"""

import unittest
import numpy as np

from basketball.core.shot_feature_extractor import ShotFeatureExtractor


class TestShotFeatureExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ShotFeatureExtractor(window_size=15, default_fps=30.0)

    def test_torso_scale_computation(self):
        # Shoulder at (0.5, 0.3), Hip at (0.5, 0.7) -> dy = 0.4
        landmarks = {
            12: {"norm_x": 0.5, "norm_y": 0.3},
            24: {"norm_x": 0.5, "norm_y": 0.7}
        }
        scale = ShotFeatureExtractor.compute_torso_scale(landmarks, side="right")
        self.assertAlmostEqual(scale, 0.4, places=2)

        # Empty landmarks fallback
        fallback = ShotFeatureExtractor.compute_torso_scale({}, side="right")
        self.assertEqual(fallback, 0.35)

    def test_frame_kinematics_extraction(self):
        # Create two consecutive frames
        frame1 = {
            "landmarks": {
                12: {"norm_x": 0.5, "norm_y": 0.4},
                24: {"norm_x": 0.5, "norm_y": 0.8},
                16: {"norm_x": 0.55, "norm_y": 0.50},  # wrist
                0: {"norm_x": 0.5, "norm_y": 0.25}     # nose
            },
            "angles": {
                "shooting_side": "right",
                "elbow_shooting": 90.0,
                "knee_shooting": 140.0
            }
        }
        # Frame 2: wrist moved upward (norm_y decreased to 0.45 in 1/30 s)
        frame2 = {
            "landmarks": {
                12: {"norm_x": 0.5, "norm_y": 0.4},
                24: {"norm_x": 0.5, "norm_y": 0.8},
                16: {"norm_x": 0.55, "norm_y": 0.45},  # wrist moved UP
                0: {"norm_x": 0.5, "norm_y": 0.25}
            },
            "angles": {
                "shooting_side": "right",
                "elbow_shooting": 110.0,  # extending
                "knee_shooting": 150.0   # extending
            }
        }

        kinematics = self.extractor.extract_frame_kinematics([frame1, frame2], fps=30.0)
        self.assertTrue(kinematics["is_valid"])
        # Vertical velocity should be negative (upward)
        self.assertLess(kinematics["wrist_v_y"], 0.0)
        # Elbow angular velocity should be positive (extending)
        self.assertGreater(kinematics["elbow_v_ang"], 0.0)

    def test_window_vector_extraction(self):
        # Feed 15 dummy kinematic frames
        history = []
        for i in range(15):
            history.append({
                "torso_scale": 0.4,
                "wrist_v_y": -0.5 - (i * 0.1),
                "wrist_a_y": -0.1,
                "rel_shoulder": 0.1 - (i * 0.05),
                "rel_nose": 0.3 - (i * 0.05),
                "hip_v_y": -0.2,
                "elbow_angle": 90.0 + i * 4.0,
                "knee_angle": 130.0 + i * 2.0,
                "shoulder_angle": 50.0,
                "hip_angle": 160.0,
                "wrist_angle": 170.0,
                "elbow_v_ang": 120.0,
                "knee_v_ang": 60.0,
                "is_valid": True,
                "shooting_side": "right"
            })

        vec = self.extractor.extract_window_vector(history)
        self.assertEqual(len(vec), 24)
        self.assertIsInstance(vec, np.ndarray)
        self.assertFalse(np.isnan(vec).any())

    def test_align_intervals_to_labels(self):
        total_frames = 100
        intervals = [
            {
                "interval_type": "shot",
                "action_class": "shot_event",
                "start_frame": 10,
                "end_frame": 50,
                "dip_frame": 15,
                "release_frame": 35
            },
            {
                "interval_type": "negative",
                "action_class": "pump_fake",
                "start_frame": 60,
                "end_frame": 80
            }
        ]

        binary, classes = ShotFeatureExtractor.align_intervals_to_labels(total_frames, intervals)
        self.assertEqual(len(binary), 100)
        self.assertEqual(len(classes), 100)
        # Binary should be 1 around release frame (15..40)
        self.assertEqual(binary[25], 1)
        self.assertEqual(binary[70], 0)
        # Class for pump fake should be 5
        self.assertEqual(classes[70], 5)


if __name__ == "__main__":
    unittest.main()
