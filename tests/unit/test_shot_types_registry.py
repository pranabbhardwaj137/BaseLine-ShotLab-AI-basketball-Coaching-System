"""Unit tests for the canonical shot type registry, config layer, and integration."""

import math
import os
import unittest

from basketball.configs.shot_types import (
    SHOT_TYPE_REGISTRY,
    SHOT_TYPE_ALIASES,
    CONFIG_VERSION,
    get_shot_type,
    resolve_shot_type,
    resolve_shot_type_alias,
    validate_shot_types_config,
)
from basketball.persistence.shot_lab_db import ShotLabDB
from basketball.tracking.calibrated_fsm import CalibratedFSMDetector
from basketball.coaching.shot_coach import build_findings, COACH_VERSION
from basketball.analysis.baseline_engine import BaselineEngine


class ShotTypesRegistryTests(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_shot_types_tmp.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.db = ShotLabDB(self.test_db)
        self.baseline_engine = BaselineEngine(self.db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_registry_contains_all_12_types(self):
        expected_types = {
            "catch_and_shoot", "free_throw", "form_shooting",
            "pull_up", "step_back", "fadeaway", "turnaround", "off_screen",
            "mid_range", "three_pointer", "bank_shot", "other"
        }
        self.assertEqual(set(SHOT_TYPE_REGISTRY.keys()), expected_types)
        self.assertEqual(len(SHOT_TYPE_REGISTRY), 12)

    def test_metric_weights_sum_to_one(self):
        for shot_id, cfg in SHOT_TYPE_REGISTRY.items():
            weights = cfg["metric_profile"]["weights"]
            self.assertTrue(weights, f"Shot type {shot_id} has no weights defined")
            total = sum(weights.values())
            self.assertTrue(
                math.isclose(total, 1.0, abs_tol=1e-5),
                f"Weights for {shot_id} sum to {total}, expected 1.0"
            )

    def test_validation_function_passes(self):
        errors = validate_shot_types_config()
        self.assertEqual(errors, [], f"Config validation failed: {errors}")

    def test_alias_resolution(self):
        self.assertEqual(resolve_shot_type("off_the_dribble"), "pull_up")
        self.assertEqual(resolve_shot_type("off_dribble"), "pull_up")
        self.assertEqual(resolve_shot_type("pull_up"), "pull_up")
        self.assertEqual(resolve_shot_type("catch_and_shoot"), "catch_and_shoot")
        self.assertEqual(resolve_shot_type("step_back"), "step_back")
        self.assertEqual(resolve_shot_type("unknown_type"), "other")
        self.assertEqual(resolve_shot_type(None), "other")
        self.assertEqual(resolve_shot_type_alias("off_dribble"), "pull_up")

    def test_detector_fallback_for_uncalibrated_profiles(self):
        # step_back has needs_calibration: True for load detection
        detector = CalibratedFSMDetector(shot_type="step_back", shot_style="jump_shot")
        self.assertEqual(detector.shot_type_id, "step_back")
        self.assertEqual(detector.detector_profile_id, "detector_step_back")
        # Falls back to default dip threshold (160.0)
        self.assertEqual(detector.min_knee_dip_angle, 160.0)
        self.assertEqual(detector.elbow_v_thresh, 60.0)
        # Note contains fallback notice
        self.assertTrue(any("default thresholds" in note for note in detector.notes))

    def test_baseline_isolation_by_shot_type(self):
        # A pull-up session must not contaminate a catch-and-shoot baseline
        sess_catch = self.db.create_session(
            player_id="test_player",
            camera_view="side_90",
            shot_type="catch_and_shoot",
            shot_style="jump_shot",
        )
        for _ in range(5):
            self.db.save_shot({
                "session_id": sess_catch,
                "player_id": "test_player",
                "camera_view": "side_90",
                "shot_type": "catch_and_shoot",
                "shot_style": "jump_shot",
                "tracking_confidence": "SUFFICIENT",
                "outcome": "make",
                "outcome_source": "live_hotkey",
                "elbow_angle_release_3d": 160.0,
            })

        # Query pull_up baseline: must find 0 shots and abstain
        res_pull = self.baseline_engine.compute_baseline("test_player", "side_90", "pull_up", shot_style="jump_shot")
        self.assertEqual(res_pull["status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(res_pull["sample_size"], 0)

        # Query catch_and_shoot baseline: finds 5 shots and succeeds
        res_catch = self.baseline_engine.compute_baseline("test_player", "side_90", "catch_and_shoot", shot_style="jump_shot")
        self.assertEqual(res_catch["status"], "VALID_BASELINE")
        self.assertEqual(res_catch["sample_size_total"], 5)

    def test_coaching_engine_boosts_priority_by_weights(self):
        fake_attempt = {
            "attempt_index": 1,
            "shot_id": "shot_1",
            "review_status": "approved",
            "metrics": {
                "knee_flexion_min_deg": {
                    "key": "knee_flexion_min_deg", "label": "Knee dip", "unit": "deg",
                    "value": 172.0, "confidence": "high", "frame": 10, "time_s": 0.5, "detail": None,
                }
            }
        }
        analysis = {
            "attempts": [fake_attempt],
            "consistency": {},
            "camera_view": "side_90",
            "shot_type_id": "catch_and_shoot",
        }
        profile = {"skill_level": "intermediate", "shot_style": "jump_shot"}
        res = build_findings(analysis, profile)
        leg_findings = [f for f in res["findings"] if f["id"] == "leg_load"]
        self.assertTrue(leg_findings)
        # Catch and shoot weight for knee_flexion_min_deg is 0.20
        # Base priority is 80 -> boosted to 80 * (1.0 + 0.20 * 2.0) = 80 * 1.40 = 112.0
        self.assertEqual(leg_findings[0]["priority"], 112.0)
        self.assertAlmostEqual(leg_findings[0]["weight"], 0.20)

    def test_coaching_engine_not_enough_evidence_state(self):
        empty_analysis = {
            "attempts": [],
            "consistency": {},
            "camera_view": "side_90",
            "shot_type_id": "step_back",
        }
        res = build_findings(empty_analysis, {"skill_level": "beginner"})
        self.assertEqual(res["findings"], [])
        self.assertTrue(res["not_evaluated"])
        self.assertIn("not enough evidence", res["not_evaluated"][0]["reason"])

    def test_no_em_dashes_in_registry_or_config(self):
        import basketball.configs.shot_types as st_mod
        with open(st_mod.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("\u2014", src, "Em dash found in shot_types.py")


if __name__ == "__main__":
    unittest.main()
