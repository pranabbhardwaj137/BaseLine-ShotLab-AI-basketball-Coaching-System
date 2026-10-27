"""Unit tests for LiveCameraEngine in live_service.py."""

import unittest
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


if __name__ == "__main__":
    unittest.main()
