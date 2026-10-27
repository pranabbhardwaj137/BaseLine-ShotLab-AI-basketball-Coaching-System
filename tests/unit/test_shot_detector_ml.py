"""
test_shot_detector_ml.py - Unit tests for MLSequenceDetector.
"""

import os
import tempfile
import unittest
import numpy as np

from basketball.tracking.shot_detector_ml import MLSequenceDetector


class TestMLSequenceDetector(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.detector = MLSequenceDetector(prob_threshold=0.50, min_activation_frames=3)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_train_and_predict(self):
        # Create synthetic training set: 10 positive shot windows, 20 negative non-shot windows
        np.random.seed(42)
        X_pos = np.random.randn(10, 24).astype(np.float32)
        X_pos[:, 0] -= 2.0  # high upward velocity (negative v_y)
        X_pos[:, 2] -= 1.0  # high elevation above shoulder

        X_neg = np.random.randn(20, 24).astype(np.float32)
        X_neg[:, 0] += 1.0  # downward or stationary velocity
        X_neg[:, 2] += 1.0  # low elevation below shoulder

        X = np.vstack([X_pos, X_neg])
        y = np.array([1] * 10 + [0] * 20, dtype=np.int32)

        res = self.detector.train(X, y)
        self.assertEqual(res["status"], "TRAINED")
        self.assertTrue(self.detector.is_trained)

        # Predictions on positive samples should have higher probability than negatives
        p_pos = self.detector.predict_proba(X_pos)
        p_neg = self.detector.predict_proba(X_neg)
        self.assertGreater(float(np.mean(p_pos)), float(np.mean(p_neg)))

    def test_streaming_proposal_generation(self):
        # Build matching feature vectors using feature extractor
        active_frame = {"is_valid": True, "wrist_v_y": -2.0, "wrist_a_y": -0.5, "rel_shoulder": -0.5, "rel_nose": -0.2, "elbow_angle": 120.0, "knee_angle": 160.0, "elbow_v_ang": 80.0, "knee_v_ang": 50.0}
        idle_frame = {"is_valid": True, "wrist_v_y": 0.0, "wrist_a_y": 0.0, "rel_shoulder": 0.2, "rel_nose": 0.4, "elbow_angle": 90.0, "knee_angle": 170.0, "elbow_v_ang": 0.0, "knee_v_ang": 0.0}

        vec_active = self.detector.feature_extractor.extract_window_vector([active_frame] * 5)
        vec_idle = self.detector.feature_extractor.extract_window_vector([idle_frame] * 5)

        X = np.vstack([vec_active] * 5 + [vec_idle] * 10)
        y = np.array([1] * 5 + [0] * 10, dtype=np.int32)
        self.detector.train(X, y)

        # Stream 15 frames:
        # frames 0..4: idle/zero
        # frames 5..9: high activation burst
        # frames 10..14: idle/zero
        proposals = []
        for f in range(15):
            k = active_frame if (5 <= f <= 9) else idle_frame
            prop = self.detector.update(f, k)
            if prop:
                proposals.append(prop)

        # There should be at least one proposal emitted after the burst terminates
        self.assertGreaterEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual(p["detector_name"], "ml_sequence_detector")
        self.assertLessEqual(p["start_frame"], p["dip_frame"])
        self.assertLessEqual(p["dip_frame"], p["set_frame"])
        self.assertLessEqual(p["set_frame"], p["release_frame"])
        self.assertLessEqual(p["release_frame"], p["end_frame"])

    def test_save_and_load_model(self):
        X = np.random.randn(15, 24).astype(np.float32)
        y = np.array([1] * 5 + [0] * 10, dtype=np.int32)
        self.detector.train(X, y)

        save_path = os.path.join(self.tmp_dir.name, "model.joblib")
        self.detector.save_model(save_path)
        self.assertTrue(os.path.exists(save_path))

        new_detector = MLSequenceDetector()
        new_detector.load_model(save_path)
        self.assertTrue(new_detector.is_trained)

        # Probabilities should match
        probs1 = self.detector.predict_proba(X)
        probs2 = new_detector.predict_proba(X)
        np.testing.assert_allclose(probs1, probs2, atol=1e-4)


if __name__ == "__main__":
    unittest.main()
