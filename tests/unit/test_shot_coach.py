"""Tests for shot_coach.py: findings must rest on usable measured evidence (SYNTHETIC inputs)."""

import json
import re
import unittest

import basketball.analysis.shooting_analysis as sa
import basketball.coaching.shot_coach as coach
try:
    from tests.support.tests_support_synthetic_pose import make_cache, shot_row, shot_sequence
except ImportError:
    from tests_support_synthetic_pose import make_cache, shot_row, shot_sequence


def session(n=4, status="approved", **seq):
    poses, shots = [], []
    for i in range(n):
        offset = len(poses)
        poses.extend(shot_sequence(**seq))
        shots.append(shot_row(shot_id=f"s{i}", start=offset + 8, release=offset + 24, end=offset + 40, status=status))
    return sa.analyze_session(make_cache(poses), shots, "side_90")


def metric(value, confidence="high", key="elbow_extension_peak_deg", time_s=1.0, frame=30):
    definition = sa.METRIC_DEFINITIONS[key]
    return {"key": key, "label": definition["label"], "unit": definition["unit"], "basis": definition["basis"],
            "value": value, "confidence": confidence, "frame": frame, "time_s": time_s, "detail": None}


def fake_analysis(values, key="elbow_extension_peak_deg", confidence="high", status="approved"):
    attempts = []
    for i, value in enumerate(values):
        metrics = {k: {"key": k, "label": d["label"], "unit": d["unit"], "basis": d["basis"], "value": None,
                       "confidence": "not_measurable", "frame": None, "time_s": None, "detail": None}
                   for k, d in sa.METRIC_DEFINITIONS.items()}
        metrics[key] = metric(value, confidence, key, time_s=i + 0.5, frame=i * 15)
        attempts.append({"attempt_index": i + 1, "shot_id": f"s{i}", "review_status": status, "outcome": "unknown",
                         "metrics": metrics})
    return {"attempts": attempts, "consistency": sa.summarize_consistency(attempts), "camera_view": "side_90"}


PROFILE = {"skill_level": "beginner", "shot_style": "jump_shot"}
FORBIDDEN = [r"\bwill (cause|lead to|result in) (an )?injur", r"\bdiagnos(is|ed|e)\b(?! an injury or)", r"\brisk score of\b",
             r"\bguarantee", r"\bdangerous\b", r"\byou have (an )?injur"]


class FindingTests(unittest.TestCase):
    def test_good_synthetic_shot_produces_strengths_with_evidence(self):
        result = coach.build_findings(session(), PROFILE)
        ids = {f["id"] for f in result["findings"]}
        self.assertIn("arm_extension_good", ids)
        self.assertIn("leg_load_good", ids)
        for finding in result["findings"]:
            self.assertTrue(finding["evidence"], finding["id"])
            self.assertIn(finding["confidence"], {"high", "medium", "low"})
            for question in ("what", "evidence", "why", "change", "practice"):
                self.assertTrue(finding["questions"][question], (finding["id"], question))
            self.assertTrue(finding["limitations"])

    def test_problem_patterns_produce_improvements_and_drills(self):
        result = coach.build_findings(session(knee_min=168, drift_px=260, lean_change=22), PROFILE)
        ids = {f["id"] for f in result["improvements"]}
        self.assertIn("leg_load", ids)
        self.assertIn("landing", ids)
        self.assertIn("torso", ids)
        landing = next(f for f in result["improvements"] if f["id"] == "landing")
        self.assertTrue(landing["drills"])
        self.assertEqual(landing["drills"][0]["dose"], coach.DRILLS[landing["drills"][0]["id"]]["dose"]["beginner"])
        self.assertTrue(all(e["time_s"] is not None for e in landing["evidence"]))
        focus = coach.first_focus(result)
        self.assertEqual(focus["finding_id"], "landing")  # balance outranks the others
        self.assertIn("balance", focus["reason"])

    def test_low_confidence_measurements_never_create_findings(self):
        analysis = fake_analysis([120, 125, 130, 128], confidence="low")
        self.assertEqual(coach.build_findings(analysis, PROFILE)["findings"], [])

    def test_no_data_means_no_findings_and_no_focus(self):
        result = coach.build_findings({"attempts": [], "consistency": {}, "camera_view": "side_90"}, PROFILE)
        self.assertEqual(result["findings"], [])
        self.assertIsNone(coach.first_focus(result))

    def test_majority_rule(self):
        mixed = fake_analysis([120, 170, 172, 175])  # only 1 of 4 bent
        self.assertNotIn("arm_extension", {f["id"] for f in coach.build_findings(mixed, PROFILE)["findings"]})
        bent = fake_analysis([120, 130, 140, 175])
        self.assertIn("arm_extension", {f["id"] for f in coach.build_findings(bent, PROFILE)["findings"]})

    def test_unconfirmed_attempts_reduce_confidence(self):
        confirmed = coach.build_findings(fake_analysis([120, 130, 140]), PROFILE)["findings"][0]
        unconfirmed = coach.build_findings(fake_analysis([120, 130, 140], status="quarantined"), PROFILE)["findings"][0]
        self.assertEqual(confirmed["confidence"], "high")
        self.assertEqual(unconfirmed["confidence"], "medium")
        self.assertIn("confirmed", unconfirmed["confidence_reason"])

    def test_discarded_attempts_are_ignored(self):
        analysis = fake_analysis([120, 130, 140], status="discarded")
        self.assertEqual(coach.build_findings(analysis, PROFILE)["findings"], [])


class PlanAndInjuryTests(unittest.TestCase):
    def setUp(self):
        self.analysis = session(knee_min=168, drift_px=260, lean_change=22)
        self.coaching = coach.build_findings(self.analysis, PROFILE)

    def test_practice_plan_scales_with_experience(self):
        beginner = coach.build_practice_plan(self.coaching, self.analysis, {"skill_level": "beginner"})
        advanced = coach.build_practice_plan(self.coaching, self.analysis, {"skill_level": "advanced"})
        self.assertIn("100", beginner["volume_guidance"])
        self.assertIn("300", advanced["volume_guidance"])
        names = [b["name"] for b in beginner["blocks"]]
        self.assertEqual(names[0], "Warm-up")
        all_content = " ".join(b["content"] for b in beginner["blocks"])
        self.assertIn("Land-and-freeze", all_content)  # balance drill appears in a block
        self.assertTrue(beginner["checklist"])
        self.assertTrue(beginner["baseline_metrics"])
        self.assertTrue(any("same spot" in step for step in beginner["comparison_method"]))

    def test_injury_section_structure_and_wording(self):
        section = coach.build_injury_section(self.analysis, self.coaching, {"pain_reported": False})
        self.assertEqual(section["title"], "Technique, Load Management, and Injury-Risk Reduction")
        self.assertTrue(section["observations"])
        for obs in section["observations"]:
            for part in ("shows", "why", "modification", "cannot_conclude"):
                self.assertTrue(obs[part], part)
            self.assertTrue(obs["evidence"])
        self.assertGreaterEqual(len(section["general_guidance"]), 6)
        text = json.dumps(section).lower()
        for pattern in FORBIDDEN:
            for match in re.finditer(pattern, text):
                # Allowed only inside an explicit negation ("cannot show whether ... will lead to injury").
                context = text[max(0, match.start() - 80):match.start()]
                self.assertTrue("cannot" in context or "not " in context or "never" in context,
                                f"{pattern}: ...{text[max(0, match.start() - 80):match.end()]}")
        self.assertIn("not a medical assessment", text)
        self.assertIn("cannot measure joint forces", text)

    def test_injury_section_without_observations_still_has_guidance(self):
        quiet = session()
        section = coach.build_injury_section(quiet, coach.build_findings(quiet, PROFILE), {})
        self.assertEqual(section["observations"], [])
        self.assertTrue(section["no_observation_note"])
        self.assertTrue(section["general_guidance"])

    def test_pain_report_is_flagged(self):
        section = coach.build_injury_section(self.analysis, self.coaching, {"pain_reported": True})
        self.assertTrue(section["pain_reported"])
        self.assertIn("healthcare professional", section["pain_advice"])

    def test_per_attempt_evaluation(self):
        evaluation = coach.evaluate_attempt(self.analysis["attempts"][0])
        self.assertTrue(any("knee bend" in x.lower() for x in evaluation["opportunities"]))


if __name__ == "__main__":
    unittest.main()
