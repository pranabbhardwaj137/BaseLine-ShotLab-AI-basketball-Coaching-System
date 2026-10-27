"""Unit tests for dip-frame localization and knee-dip angle model."""

import unittest
from basketball.services.video_analysis_service import _extract_dip_frame
import basketball.analysis.shooting_analysis as sa
from tests.support.tests_support_synthetic_pose import make_cache, shot_row, shot_sequence, side_view_pose


class DipFrameLocalizationTests(unittest.TestCase):
    def test_extract_dip_frame_valid_gather(self):
        """A normal shot gather with a distinct dip between start and set."""
        knee_samples = [
            {"frame": 10, "knee_primary": 170.0, "knee_3d": 168.0, "knee_2d": 170.0},
            {"frame": 12, "knee_primary": 150.0, "knee_3d": 149.0, "knee_2d": 150.0},
            {"frame": 14, "knee_primary": 125.0, "knee_3d": 124.0, "knee_2d": 125.0},
            {"frame": 16, "knee_primary": 110.0, "knee_3d": 108.5, "knee_2d": 110.0},  # True dip
            {"frame": 18, "knee_primary": 130.0, "knee_3d": 129.0, "knee_2d": 130.0},
            {"frame": 20, "knee_primary": 160.0, "knee_3d": 159.0, "knee_2d": 160.0},
        ]
        dip_f, k3d, k2d = _extract_dip_frame(knee_samples, start_frame=10, set_frame=20, release_frame=24)
        self.assertEqual(dip_f, 16)
        self.assertEqual(k3d, 108.5)
        self.assertEqual(k2d, 110.0)

    def test_extract_dip_frame_rejects_single_frame_sensor_jitter(self):
        """Single-frame tracking glitches (e.g. tracking jumps to 25 deg for 1 frame) are rejected."""
        knee_samples = [
            {"frame": 10, "knee_primary": 150.0, "knee_3d": 150.0, "knee_2d": 150.0},
            {"frame": 12, "knee_primary": 25.0,  "knee_3d": 25.0,  "knee_2d": 25.0},   # Tracking glitch / impulse spike
            {"frame": 14, "knee_primary": 148.0, "knee_3d": 148.0, "knee_2d": 148.0},
            {"frame": 16, "knee_primary": 115.0, "knee_3d": 114.0, "knee_2d": 115.0},  # Genuine dip
            {"frame": 18, "knee_primary": 145.0, "knee_3d": 145.0, "knee_2d": 145.0},
        ]
        dip_f, k3d, k2d = _extract_dip_frame(knee_samples, start_frame=10, set_frame=18, release_frame=20)
        self.assertEqual(dip_f, 16)
        self.assertEqual(k3d, 114.0)

    def test_extract_dip_frame_flat_footed_omitted(self):
        """If player never dips (knees remain > 165 deg), dip frame must be omitted (None)."""
        knee_samples = [
            {"frame": 10, "knee_primary": 175.0, "knee_3d": 174.0, "knee_2d": 175.0},
            {"frame": 12, "knee_primary": 170.0, "knee_3d": 169.0, "knee_2d": 170.0},
            {"frame": 14, "knee_primary": 168.0, "knee_3d": 167.0, "knee_2d": 168.0},
            {"frame": 16, "knee_primary": 172.0, "knee_3d": 171.0, "knee_2d": 172.0},
        ]
        dip_f, k3d, k2d = _extract_dip_frame(knee_samples, start_frame=10, set_frame=18, release_frame=20)
        self.assertIsNone(dip_f)
        self.assertIsNone(k3d)
        self.assertIsNone(k2d)

    def test_extract_dip_frame_enforces_chronological_ordering(self):
        """Samples occurring outside [start_frame, set/release_frame] are rejected."""
        knee_samples = [
            {"frame": 5, "knee_primary": 100.0, "knee_3d": 99.0, "knee_2d": 100.0},   # Before start
            {"frame": 10, "knee_primary": 170.0, "knee_3d": 170.0, "knee_2d": 170.0},
            {"frame": 12, "knee_primary": 172.0, "knee_3d": 172.0, "knee_2d": 172.0},
            {"frame": 25, "knee_primary": 95.0, "knee_3d": 94.0, "knee_2d": 95.0},    # After release
        ]
        dip_f, k3d, k2d = _extract_dip_frame(knee_samples, start_frame=10, set_frame=18, release_frame=20)
        self.assertIsNone(dip_f)


class DipBiomechanicalAnalysisTests(unittest.TestCase):
    def test_metric_definitions_has_3d_knee_dip(self):
        self.assertIn("knee_angle_dip_3d_deg", sa.METRIC_DEFINITIONS)
        defn = sa.METRIC_DEFINITIONS["knee_angle_dip_3d_deg"]
        self.assertEqual(defn["basis"], "world_3d_estimate")
        self.assertEqual(defn["unit"], "°")

    def test_flat_footed_shot_omits_3d_dip_measurement(self):
        """When knees do not dip (knee_min = 168), dip_frame is None and knee_angle_dip_3d is omitted."""
        poses = shot_sequence(knee_min=168.0)
        cache = make_cache(poses)
        result = sa.analyze_session(cache, [shot_row()], "side_90")
        attempt = result["attempts"][0]
        self.assertIsNone(attempt["dip_frame"])
        dip_3d = attempt["metrics"]["knee_angle_dip_3d_deg"]
        self.assertIsNone(dip_3d["value"])
        self.assertIn("No distinct knee dip detected", dip_3d["reason"])


if __name__ == "__main__":
    unittest.main()
