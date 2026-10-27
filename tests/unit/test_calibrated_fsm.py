"""
test_calibrated_fsm.py - Unit tests for CalibratedFSMDetector and calibration utility.
"""

import unittest
from basketball.tracking.calibrated_fsm import CalibratedFSMDetector, optimize_fsm_parameters


class TestCalibratedFSMDetector(unittest.TestCase):
    def setUp(self):
        self.detector = CalibratedFSMDetector()

    def test_shot_state_progression_and_proposal(self):
        # Simulate a clean shooting sequence across 20 frames
        # Frames 0..4: idle
        # Frames 5..8: knee dip (prep)
        # Frames 9..12: set point
        # Frames 13..16: releasing upward burst (peak at frame 15)
        # Frames 17..19: follow through
        proposal_generated = None

        for f in range(20):
            if f < 5:
                k = {"is_valid": True, "knee_angle": 175.0, "wrist_v_y": 0.0, "rel_shoulder": 0.2, "elbow_angle": 90.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}
            elif f < 9:
                k = {"is_valid": True, "knee_angle": 145.0, "wrist_v_y": 0.1, "rel_shoulder": 0.1, "elbow_angle": 85.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}
            elif f < 13:
                k = {"is_valid": True, "knee_angle": 155.0, "wrist_v_y": -0.3, "rel_shoulder": -0.05, "elbow_angle": 100.0, "elbow_v_ang": 50.0, "knee_v_ang": 45.0}
            elif f < 17:
                # Upward release burst with peak velocity at frame 15 (v_y = -1.2)
                v_burst = -1.2 if f == 15 else -0.8
                k = {"is_valid": True, "knee_angle": 170.0, "wrist_v_y": v_burst, "rel_shoulder": -0.25, "elbow_angle": 130.0, "elbow_v_ang": 90.0, "knee_v_ang": 50.0}
            else:
                k = {"is_valid": True, "knee_angle": 175.0, "wrist_v_y": -0.1, "rel_shoulder": -0.30, "elbow_angle": 160.0, "elbow_v_ang": 10.0, "knee_v_ang": 0.0}

            state, prop = self.detector.update(f, k)
            if prop:
                proposal_generated = prop

        self.assertIsNotNone(proposal_generated, "Expected proposal to be generated")
        self.assertEqual(proposal_generated["detector_name"], "calibrated_fsm_detector")
        # Release frame should be localized at peak velocity frame 15
        self.assertEqual(proposal_generated["release_frame"], 15)

        # Monotonic bounds
        self.assertLessEqual(proposal_generated["start_frame"], proposal_generated["dip_frame"])
        self.assertLessEqual(proposal_generated["dip_frame"], proposal_generated["set_frame"])
        self.assertLessEqual(proposal_generated["set_frame"], proposal_generated["release_frame"])
        self.assertLessEqual(proposal_generated["release_frame"], proposal_generated["end_frame"])

    def test_gather_abort_suppresses_false_shot(self):
        # A gather/pump fake that dips knee but never elevates wrist or accelerates
        detector = CalibratedFSMDetector()
        props = []

        for f in range(25):
            k = {
                "is_valid": True,
                "knee_angle": 150.0,       # bent knee
                "wrist_v_y": 0.0,          # zero upward speed
                "rel_shoulder": 0.2,       # wrist below shoulder
                "elbow_angle": 80.0,
                "elbow_v_ang": 0.0,
                "knee_v_ang": 0.0
            }
            _, prop = detector.update(f, k)
            if prop:
                props.append(prop)

        self.assertEqual(len(props), 0, "Gather without release must not generate proposal")

    def test_optimize_fsm_parameters(self):
        # Synthetic sequence
        synthetic_clip = {
            "kinematics": [
                {"is_valid": True, "knee_angle": 150.0, "wrist_v_y": 0.0, "rel_shoulder": 0.1, "elbow_angle": 80.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0},
                {"is_valid": True, "knee_angle": 155.0, "wrist_v_y": -0.2, "rel_shoulder": -0.05, "elbow_angle": 100.0, "elbow_v_ang": 40.0, "knee_v_ang": 50.0},
                {"is_valid": True, "knee_angle": 170.0, "wrist_v_y": -0.9, "rel_shoulder": -0.25, "elbow_angle": 130.0, "elbow_v_ang": 80.0, "knee_v_ang": 50.0},
                {"is_valid": True, "knee_angle": 175.0, "wrist_v_y": -0.1, "rel_shoulder": -0.30, "elbow_angle": 160.0, "elbow_v_ang": 10.0, "knee_v_ang": 0.0}
            ],
            "gt_release_frame": 2
        }

        best = optimize_fsm_parameters([synthetic_clip])
        self.assertIn("min_upward_velocity", best)
        self.assertIn("wrist_rel_shoulder_thresh", best)
        self.assertIn("min_knee_dip_angle", best)


if __name__ == "__main__":
    unittest.main()
