"""Unit tests for shooting_analysis.py on SYNTHETIC stick-figure pose data with known angles."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import basketball.analysis.shooting_analysis as sa
try:
    from tests.support.tests_support_synthetic_pose import (front_view_pose, make_cache, shot_row, shot_sequence,
                                                  side_view_pose)
except ImportError:
    from tests_support_synthetic_pose import (front_view_pose, make_cache, shot_row, shot_sequence,
                                              side_view_pose)


def analyse(poses, view="side_90", shots=None, **cache_kwargs):
    cache = make_cache(poses, **cache_kwargs)
    return sa.analyze_session(cache, shots or [shot_row()], view)


class GeometryTests(unittest.TestCase):
    def test_angle_2d_and_3d(self):
        self.assertAlmostEqual(sa.angle_2d((0, 1), (0, 0), (1, 0)), 90.0)
        self.assertAlmostEqual(sa.angle_2d((-1, 0), (0, 0), (1, 0)), 180.0)
        self.assertIsNone(sa.angle_2d((0, 0), (0, 0), (1, 0)))
        self.assertAlmostEqual(sa.angle_3d((1, 0, 0), (0, 0, 0), (0, 0, 1)), 90.0)

    def test_synthetic_pose_has_requested_angles(self):
        pose = side_view_pose(120.0, 95.0)
        self.assertAlmostEqual(sa.angle_2d(pose[24], pose[26], pose[28]), 120.0, places=4)
        self.assertAlmostEqual(sa.angle_2d(pose[12], pose[14], pose[16]), 95.0, places=4)

    def test_lean_from_vertical(self):
        self.assertAlmostEqual(sa.lean_from_vertical((0, 10, 1), (0, 0, 1)), 0.0)
        self.assertAlmostEqual(sa.lean_from_vertical((0, 10, 1), (10, 0, 1)), 45.0)


class AttemptMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.result = analyse(shot_sequence())
        self.attempt = self.result["attempts"][0]
        self.m = self.attempt["metrics"]

    def test_knee_and_leg_drive(self):
        knee = self.m["knee_flexion_min_deg"]
        self.assertEqual(knee["confidence"], "high")
        self.assertAlmostEqual(knee["value"], 110.0, delta=1.0)
        self.assertEqual(self.attempt["dip_frame"], 20)
        self.assertGreater(self.m["knee_extension_range_deg"]["value"], 40)

    def test_release_is_estimated_from_arm_extension(self):
        self.assertEqual(self.attempt["release_source"], "estimated from arm extension")
        self.assertEqual(self.attempt["detector_release_frame"], 24)
        self.assertGreater(self.attempt["release_frame"], 24)
        self.assertGreaterEqual(self.m["elbow_angle_release_deg"]["value"], 165)
        self.assertGreaterEqual(self.m["elbow_extension_peak_deg"]["value"], 175)

    def test_your_release_correction_wins(self):
        shot = shot_row(release=24)
        shot["annotated_release_frame"] = 26
        attempt = analyse(shot_sequence(), shots=[shot])["attempts"][0]
        self.assertEqual(attempt["release_source"], "you")
        self.assertEqual(attempt["release_frame"], 26)

    def test_legs_lead_timing_is_positive(self):
        lag = self.m["sequencing_lag_ms"]
        self.assertIsNotNone(lag["value"])
        self.assertGreater(lag["value"], 0)
        early = analyse(shot_sequence(legs_first=False))["attempts"][0]["metrics"]["sequencing_lag_ms"]
        if early["value"] is not None:
            self.assertLess(early["value"], lag["value"])

    def test_units_bases_and_timestamps(self):
        for key, record in self.m.items():
            definition = sa.METRIC_DEFINITIONS[key]
            self.assertEqual(record["unit"], definition["unit"])
            self.assertEqual(record["basis"], definition["basis"])
            if record["value"] is not None and record["frame"] is not None:
                self.assertAlmostEqual(record["time_s"], record["frame"] / 30.0, places=3)

    def test_front_only_metrics_not_measurable_from_side(self):
        for key in ("stance_width_ratio", "elbow_flare_ratio", "knee_inward_ratio"):
            self.assertEqual(self.m[key]["confidence"], "not_measurable", key)
            self.assertIsNone(self.m[key]["value"])
            self.assertIn("side view", self.m[key]["reason"])

    def test_drift_and_torso_movement(self):
        moving = analyse(shot_sequence(drift_px=200, lean_change=20))["attempts"][0]["metrics"]
        self.assertGreater(moving["hip_drift_ratio"]["value"], 0.5)
        self.assertEqual(moving["hip_drift_ratio"]["detail"], "forward")
        self.assertGreater(moving["torso_lean_change_deg"]["value"], 15)
        still = self.m
        self.assertLess(still["hip_drift_ratio"]["value"], 0.1)

    def test_smoothing_bias_on_a_sharp_dip_is_bounded(self):
        # A V-shaped dip with a 6°-per-frame corner is sharper than real motion; the centred
        # 1-2-1 smoothing may round it off but by no more than a few degrees.
        poses = [side_view_pose(170 - 6 * min(f, 10) if f <= 10 else 110 + 6 * (f - 10), 90) for f in range(21)]
        series = sa.PoseSeries(make_cache(poses))
        smoothed_min = min(sa.angle_2d(series.point(f, 24), series.point(f, 26), series.point(f, 28)) for f in range(21))
        self.assertLess(smoothed_min - 110.0, 4.0)

    def test_follow_through_hold(self):
        hold = self.m["follow_through_hold_ms"]["value"]
        self.assertGreater(hold, 500)


class ConfidenceAndMissingDataTests(unittest.TestCase):
    def test_low_visibility_is_flagged_and_not_usable(self):
        attempt = analyse(shot_sequence(), visibility={14: 0.4, 16: 0.4, 13: 0.4, 15: 0.4})["attempts"][0]
        self.assertEqual(attempt["metrics"]["elbow_angle_release_deg"]["confidence"], "low")
        self.assertIn("not used for coaching", attempt["metrics"]["elbow_angle_release_deg"]["reason"])

    def test_missing_joints_are_not_filled_in(self):
        missing = {(f, j) for f in range(75) for j in (25, 26, 27, 28)}
        attempt = analyse(shot_sequence(), missing=missing)["attempts"][0]
        self.assertIsNone(attempt["metrics"]["knee_flexion_min_deg"]["value"])
        self.assertEqual(attempt["metrics"]["knee_flexion_min_deg"]["confidence"], "not_measurable")

    def test_frames_without_pose(self):
        poses = shot_sequence()
        for f in range(18, 23):
            poses[f] = None
        result = analyse(poses)
        self.assertLess(result["quality"]["pose_detected_ratio"], 1.0)
        self.assertLess(result["attempts"][0]["pose_coverage"], 1.0)

    def test_implausible_angle_is_downgraded(self):
        record = sa._metric("elbow_angle_release_deg", "side_90", sa.PoseSeries(make_cache(shot_sequence())),
                            10.0, 25, [25], [12, 14, 16])
        self.assertEqual(record["confidence"], "low")
        self.assertIn("plausible", record["reason"])

    def test_no_release_means_nothing_measured(self):
        shot = shot_row(release=None)
        attempt = analyse(shot_sequence(), shots=[shot])["attempts"][0]
        self.assertTrue(all(r["value"] is None for r in attempt["metrics"].values()))


class ViewAndQualityTests(unittest.TestCase):
    def test_estimates_side_view(self):
        quality = analyse(shot_sequence())["quality"]
        self.assertEqual(quality["estimated_view"], "side_90")
        self.assertTrue(quality["view_matches"])
        self.assertEqual(quality["grade"], "good")

    def test_view_mismatch_blocks_view_specific_metrics(self):
        result = analyse(shot_sequence(), view="frontal")
        self.assertFalse(result["quality"]["view_matches"])
        self.assertTrue(any("looks closer to a side view" in issue for issue in result["quality"]["issues"]))
        stance = result["attempts"][0]["metrics"]["stance_width_ratio"]
        self.assertEqual(stance["confidence"], "not_measurable")
        self.assertIn("footage looks like a side view", stance["reason"])

    def test_front_view_alignment_metrics(self):
        poses = [front_view_pose(stance_ratio=1.2, elbow_offset_ratio=0.4, knee_inward_ratio=0.3) for _ in range(45)]
        attempt = analyse(poses, view="frontal", shots=[shot_row(start=5, release=20, end=35)])["attempts"][0]
        m = attempt["metrics"]
        self.assertAlmostEqual(m["stance_width_ratio"]["value"], 1.2, delta=0.05)
        self.assertAlmostEqual(m["elbow_flare_ratio"]["value"], 0.4, delta=0.05)
        self.assertAlmostEqual(m["knee_inward_ratio"]["value"], 0.3, delta=0.05)
        self.assertEqual(m["knee_flexion_min_deg"]["confidence"], "not_measurable")

    def test_old_cache_format_is_reported(self):
        cache = make_cache(shot_sequence())
        cache["format"] = 1
        cache.pop("world")
        result = sa.analyze_session(cache, [shot_row()], "side_90")
        self.assertTrue(result["quality"]["pose_lagged"])
        self.assertIsNone(result["attempts"][0]["metrics"]["elbow_angle_release_3d_deg"]["value"])

    def test_load_pose_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(make_cache(shot_sequence(n_frames=10)), handle)
            self.assertEqual(len(sa.load_pose_cache(path)["frames"]), 10)
            bad = Path(tmp) / "bad.json.gz"
            with gzip.open(bad, "wt", encoding="utf-8") as handle:
                json.dump({"fps": 30}, handle)
            with self.assertRaises(ValueError):
                sa.load_pose_cache(bad)


class ConsistencyTests(unittest.TestCase):
    def _session(self, knee_values):
        poses, shots = [], []
        for i, knee in enumerate(knee_values):
            offset = len(poses)
            poses.extend(shot_sequence(knee_min=knee))
            shots.append(shot_row(shot_id=f"s{i}", start=offset + 8, release=offset + 24, end=offset + 40))
        return analyse(poses, shots=shots)

    def test_needs_three_attempts(self):
        result = self._session([110, 112])
        self.assertNotIn("sd", result["consistency"]["knee_flexion_min_deg"])

    def test_consistent_and_variable(self):
        steady = self._session([110, 111, 112, 110])["consistency"]["knee_flexion_min_deg"]
        self.assertEqual(steady["rating"], "consistent")
        varied = self._session([100, 130, 150, 115])["consistency"]["knee_flexion_min_deg"]
        self.assertEqual(varied["rating"], "variable")

    def test_discarded_attempts_are_excluded(self):
        result = self._session([110, 111, 112, 150])
        result["attempts"][3]["review_status"] = "discarded"
        summary = sa.summarize_consistency(result["attempts"])["knee_flexion_min_deg"]
        self.assertEqual(summary["n"], 3)

    def test_outcome_split_needs_two_labelled_of_each(self):
        result = self._session([110, 112, 114, 116])
        attempts = result["attempts"]
        self.assertIsNone(sa.summarize_by_outcome(attempts))
        for a, outcome in zip(attempts, ["make", "make", "miss", "miss"]):
            a["review_status"], a["outcome"] = "approved", outcome
        split = sa.summarize_by_outcome(attempts)
        self.assertEqual((split["makes"], split["misses"]), (2, 2))
        self.assertIn("does not show", split["note"])


if __name__ == "__main__":
    unittest.main()
