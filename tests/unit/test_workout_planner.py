"""Unit tests for the Personalized Workout Coach: catalog, planner, voice count rule, progress summary."""

import copy
import itertools
import json
import math
import tempfile
import unittest
from pathlib import Path

import basketball.workout.catalog as wc
import basketball.workout.planner as wp
import basketball.workout.progress as wpr

FIXTURE = Path(__file__).resolve().parents[1] / "support" / "workout_report_fixture.json"


def load_report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def finding(fid, confidence="high", kind="improvement", title=None):
    return {"id": fid, "kind": kind, "category": fid, "confidence": confidence, "title": title or f"{fid} finding",
            "observed": f"{fid} observed", "affected": "3 of 4 attempts", "timestamps": [], "limitations": [],
            "confidence_reason": "test"}


def report_with(*findings):
    report = load_report()
    report["findings"] = list(findings)
    return report


ALL_VIDEOS = lambda _eid: True  # noqa: E731 - treat every mapped video as present


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = wc.load_catalog()

    def test_catalog_is_valid_and_covers_all_equipment(self):
        wc.validate_catalog(self.catalog)
        self.assertEqual(set(self.catalog["equipment"]),
                         {"barbell", "bodyweight", "cable", "dumbbell", "machine", "band", "smith", "stretching", "trx"})
        for key in self.catalog["equipment"]:
            self.assertTrue(any(e["equipment"] == key for e in self.catalog["exercises"]), key)

    def test_every_exercise_has_coaching_text(self):
        for exercise in self.catalog["exercises"]:
            for key in ("name", "instructions", "cues", "mistakes", "regression", "progression"):
                self.assertTrue(exercise.get(key), f"{exercise['id']} missing {key}")

    def test_mapped_videos_exist_when_workout_folder_present(self):
        if not wc.DEFAULT_WORKOUT_DIR.is_dir():
            self.skipTest("workout/ folder is not present in this checkout")
        status = wc.video_status(self.catalog, wc.DEFAULT_WORKOUT_DIR)
        self.assertEqual(status["missing"], [], "catalog points at videos that are not on disk")

    def test_rejects_unsafe_video_paths(self):
        for bad in ("/etc/passwd.mp4", "../secret.mp4", "Dumbbell/../../x.mp4", "Dumbbell/clip.mov"):
            broken = copy.deepcopy({k: v for k, v in self.catalog.items() if k != "_by_id"})
            broken["exercises"][0]["video"] = bad
            with self.assertRaises(wc.CatalogError, msg=bad):
                wc.validate_catalog(broken)

    def test_media_path_only_resolves_catalog_ids_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workout"
            exercise = next(e for e in self.catalog["exercises"] if e.get("video"))
            target = root / exercise["video"]
            target.parent.mkdir(parents=True)
            target.write_bytes(b"\x00" * 16)
            self.assertEqual(wc.media_path(self.catalog, exercise["id"], root), target.resolve())
            for bad_id in ("../etc/passwd", "UPPER", "", "no_such_exercise", "a/b", "x" * 65):
                self.assertIsNone(wc.media_path(self.catalog, bad_id, root), bad_id)
            text_only = next(e for e in self.catalog["exercises"] if not e.get("video"))
            self.assertIsNone(wc.media_path(self.catalog, text_only["id"], root))
            # A catalog entry tampered to escape the root is refused even if the file exists.
            outside = Path(tmp) / "outside.mp4"
            outside.write_bytes(b"\x00")
            tampered = dict(self.catalog)
            tampered["_by_id"] = dict(self.catalog["_by_id"])
            tampered["_by_id"][exercise["id"]] = dict(exercise, video="../outside.mp4")
            self.assertIsNone(wc.media_path(tampered, exercise["id"], root))
            # Missing file on disk -> None (the UI shows the written guide).
            target.unlink()
            self.assertIsNone(wc.media_path(self.catalog, exercise["id"], root))


class PreferencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = wc.load_catalog()

    def prefs(self, **overrides):
        raw = {"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20}
        raw.update(overrides)
        return wp.validate_preferences(raw, self.catalog)

    def test_requires_equipment(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.prefs(equipment=[])
        with self.assertRaisesRegex(ValueError, "Unknown equipment"):
            self.prefs(equipment=["kettlebell"])

    def test_duration_bounds(self):
        with self.assertRaisesRegex(ValueError, "at least 20"):
            self.prefs(duration_min=15)
        with self.assertRaises(ValueError):
            self.prefs(duration_min=90)
        with self.assertRaises(ValueError):
            self.prefs(duration_min="abc")
        self.assertEqual(self.prefs(duration_min="30")["duration_min"], 30)

    def test_rejects_unknown_level_goal_and_limitation(self):
        for bad in ({"fitness_level": "pro"}, {"goals": ["fly"]}, {"avoid": ["everything"]}):
            with self.assertRaises(ValueError):
                self.prefs(**bad)


class PlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = wc.load_catalog()

    def plan(self, report=None, **raw):
        base = {"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20}
        base.update(raw)
        prefs = wp.validate_preferences(base, self.catalog)
        return wp.build_plan(report or load_report(), prefs, self.catalog, video_available=ALL_VIDEOS)

    def exercises(self, plan):
        return [self.catalog["_by_id"][item["exercise_id"]] for item in plan["items"]]

    def test_equipment_filter_is_respected(self):
        for equipment in (["dumbbell"], ["band"], ["trx"], ["barbell", "smith"], ["machine", "cable"]):
            plan = self.plan(equipment=equipment, fitness_level="intermediate")
            allowed = set(equipment) | {"stretching"}
            for item, exercise in zip(plan["items"], self.exercises(plan)):
                if exercise["equipment"] in allowed:
                    continue
                # Warm-up / cool-down may use equipment-free movements only.
                self.assertTrue(exercise.get("equipment_free"), f"{equipment}: {exercise['id']} not allowed")
                self.assertIn(item["phase"], ("warmup", "cooldown", "main"))

    def test_bodyweight_only_uses_no_equipment(self):
        plan = self.plan(equipment=["bodyweight"])
        for exercise in self.exercises(plan):
            self.assertTrue(exercise["equipment"] in ("bodyweight", "stretching") or exercise.get("equipment_free"),
                            exercise["id"])
            self.assertFalse(exercise.get("needs"), f"{exercise['id']} needs {exercise.get('needs')}")

    def test_beginner_never_gets_advanced_or_high_impact(self):
        plan = self.plan(equipment=list(self.catalog["equipment"]), fitness_level="beginner", duration_min=45)
        for exercise in self.exercises(plan):
            self.assertEqual(exercise["min_level"], "beginner", exercise["id"])
            self.assertNotEqual(exercise["impact"], "high", exercise["id"])

    def test_pain_and_avoid_rules(self):
        plan = self.plan(equipment=list(self.catalog["equipment"]), fitness_level="advanced", duration_min=40,
                         pain=True, avoid=["knee", "jumping", "overhead"])
        self.assertTrue(plan["pain_note"])
        for item, exercise in zip(plan["items"], self.exercises(plan)):
            self.assertNotIn("knee", exercise["stresses"], exercise["id"])
            self.assertNotIn("overhead", exercise["stresses"], exercise["id"])
            self.assertIn(exercise["impact"], ("none", "low"), exercise["id"])
            self.assertNotEqual(exercise["kind"], "power_low", exercise["id"])
            self.assertLessEqual(item["sets"], 3, exercise["id"])

    def test_plan_is_linked_to_real_findings(self):
        plan = self.plan()
        used = {f["id"] for f in plan["findings_used"]}
        self.assertEqual(used, {"torso", "consistency", "landing"})
        landing = next(f for f in plan["findings_used"] if f["id"] == "landing")
        self.assertTrue(landing["possible"], "low-confidence finding must be marked as possible")
        self.assertFalse(plan["general"])
        main = [i for i in plan["items"] if i["phase"] == "main"]
        linked = [i for i in main if i["rationale"]["source"]["type"] == "finding"]
        self.assertTrue(linked)
        for item in linked:
            rationale = item["rationale"]
            self.assertIn(rationale["source"]["id"], used)
            for key in ("reason", "benefit", "evidence_limit"):
                self.assertTrue(rationale.get(key), f"{item['exercise_id']} missing {key}")
        self.assertIn("core", {area for i in main for area in [i.get("area")] if area})

    def test_strength_findings_are_not_targets(self):
        plan = self.plan()
        self.assertNotIn("sequencing_good", {f["id"] for f in plan["findings_used"]})
        self.assertIn("sequencing_good", {s["id"] for s in plan["strengths"]})

    def test_unrelated_report_findings_do_not_leak_between_reports(self):
        legs = self.plan(report_with(finding("leg_load")))
        arms = self.plan(report_with(finding("elbow_alignment")), equipment=["dumbbell", "band"],
                         fitness_level="intermediate")
        self.assertEqual({f["id"] for f in legs["findings_used"]}, {"leg_load"})
        self.assertEqual({f["id"] for f in arms["findings_used"]}, {"elbow_alignment"})
        self.assertIn("lower_strength", {i.get("area") for i in legs["items"] if i["phase"] == "main"})
        self.assertIn("shoulder", {i.get("area") for i in arms["items"] if i["phase"] == "main"})

    def test_general_fallback_when_no_usable_findings(self):
        plan = self.plan(report_with(finding("leg_load_good", kind="strength")))
        self.assertTrue(plan["general"])
        self.assertEqual(plan["findings_used"], [])
        self.assertIn("general", plan["summary"].lower())
        self.assertTrue([i for i in plan["items"] if i["phase"] == "main"])

    def test_follow_through_is_technique_only(self):
        plan = self.plan(report_with(finding("follow_through")))
        self.assertEqual([f["id"] for f in plan["technique_only"]], ["follow_through"])
        self.assertEqual(plan["findings_used"], [])

    def test_not_assessed_is_listed(self):
        text = " ".join(self.plan()["not_assessed"]).lower()
        self.assertIn("jump height", text)

    def test_warmup_main_cooldown_present_and_ordered(self):
        phases = [i["phase"] for i in self.plan()["items"]]
        self.assertEqual(phases[0], "warmup")
        self.assertEqual(phases[-1], "cooldown")
        self.assertEqual(phases, sorted(phases, key=["warmup", "main", "cooldown"].index))

    def test_duration_meets_minimum_and_request_across_combinations(self):
        equipment_sets = (["bodyweight"], ["dumbbell"], ["band", "trx"], list(self.catalog["equipment"]))
        for equipment, level, minutes, pain in itertools.product(
                equipment_sets, wc.LEVELS, (20, 30, 45, 60), (False, True)):
            plan = self.plan(equipment=equipment, fitness_level=level, duration_min=minutes, pain=pain)
            total = plan["duration"]["total_s"]
            label = f"{equipment} {level} {minutes} pain={pain}"
            self.assertGreaterEqual(total, wp.MIN_DURATION_S, label)
            self.assertGreaterEqual(total, minutes * 60, label)
            self.assertLessEqual(total, minutes * 60 + wp.OVERSHOOT_TOLERANCE_S, f"{label}: overshoots by {total - minutes * 60}s")

    def test_duration_is_computed_from_items_not_hard_coded(self):
        plan = self.plan(duration_min=30)
        expected = 0
        for item in plan["items"]:
            per_item = item["sets"] * item["work_s"] + (item["sets"] - 1) * item["rest_between_sets_s"] + item["rest_after_s"]
            self.assertEqual(wp.item_duration(item), per_item)
            self.assertEqual(item["planned_s"], per_item)
            expected += per_item
        self.assertEqual(plan["duration"]["total_s"], expected)
        self.assertEqual(plan["duration"]["work_s"] + plan["duration"]["rest_s"], expected)
        # Changing a set changes the total: nothing is a fixed number.
        items = copy.deepcopy(plan["items"])
        items[1]["sets"] += 1
        self.assertGreater(wp.plan_duration(items)["total_s"], expected)

    def test_work_time_follows_cadence_and_side(self):
        cadence = self.catalog["cadence_seconds_per_rep"]
        for item in self.plan(equipment=list(self.catalog["equipment"]), fitness_level="intermediate",
                              duration_min=45)["items"]:
            if item["mode"] == "reps":
                sides = 2 if item["per_side"] else 1
                self.assertEqual(item["work_s"], math.ceil(item["target"] * sides * cadence.get(item["kind"], 3.0)))
            else:
                self.assertEqual(item["work_s"], item["target"] * (2 if item["per_side"] else 1))

    def test_rest_differs_by_exercise_type(self):
        plan = self.plan(equipment=list(self.catalog["equipment"]), fitness_level="intermediate", duration_min=45)
        by_kind = {}
        for item in plan["items"]:
            if item["sets"] > 1:
                by_kind.setdefault(item["kind"], set()).add(item["rest_between_sets_s"])
        self.assertGreater(len({r for rests in by_kind.values() for r in rests}), 1, by_kind)
        if "strength_compound" in by_kind and "mobility" in by_kind:
            self.assertGreater(min(by_kind["strength_compound"]), max(by_kind["mobility"]))
        self.assertEqual(plan["items"][-1]["rest_after_s"], 0)

    def test_only_video_demonstrated_exercises_are_prescribed(self):
        text_only = {e["id"] for e in self.catalog["exercises"] if not e.get("video")}
        self.assertTrue({"plank", "side_plank", "bird_dog", "pallof_press_band", "step_up", "march_in_place"} <= text_only)
        for equipment, level, minutes, pain, avoid in itertools.product(
                (["bodyweight"], ["band", "cable"], list(self.catalog["equipment"])), wc.LEVELS, (20, 45),
                (False, True), ([], ["knee", "jumping"])):
            plan = self.plan(equipment=equipment, fitness_level=level, duration_min=minutes, pain=pain, avoid=avoid)
            used = {i["exercise_id"] for i in plan["items"]}
            self.assertFalse(used & text_only, f"text-only exercises prescribed: {used & text_only}")
            self.assertTrue(all(i["video"] and i["media_url"] for i in plan["items"]))
            self.assertGreater(plan["video_policy"]["excluded_count"], 0)

    def test_files_missing_on_disk_are_never_prescribed(self):
        prefs = wp.validate_preferences({"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20},
                                        self.catalog)
        plan = wp.build_plan(load_report(), prefs, self.catalog, video_available=lambda _eid: False)
        self.assertEqual(plan["items"], [])
        missing = {"split_squat_bw", "running_in_place", "dead_bug"}
        plan = wp.build_plan(load_report(), prefs, self.catalog, video_available=lambda eid: eid not in missing)
        self.assertFalse({i["exercise_id"] for i in plan["items"]} & missing)

    def test_shortfall_is_reported_not_padded(self):
        # Very restrictive choices: fewer video exercises fit than the request needs. The plan stays
        # short (the server refuses it with a clear message) instead of adding text-only filler.
        plan = self.plan(duration_min=60, pain=True, avoid=["ankle", "floor", "wrist"])
        self.assertLess(plan["duration"]["total_s"], plan["duration"]["target_s"])
        self.assertTrue(all(i["media_url"] for i in plan["items"]))

    def test_media_url_uses_exercise_id(self):
        plan = self.plan()
        for item in plan["items"]:
            if item["media_url"]:
                self.assertEqual(item["media_url"], f"/api/workout-media/{item['exercise_id']}")
                self.assertNotIn("workout/", item["media_url"])

    def test_plan_is_deterministic(self):
        self.assertEqual(self.plan(duration_min=35), self.plan(duration_min=35))

    def test_uids_unique(self):
        uids = [i["uid"] for i in self.plan(duration_min=60, fitness_level="advanced",
                                            equipment=list(self.catalog["equipment"]))["items"]]
        self.assertEqual(len(uids), len(set(uids)))


class VoiceRuleTest(unittest.TestCase):
    def test_final_ten_percent(self):
        cases = {50: [5, 4, 3, 2, 1], 40: [4, 3, 2, 1], 30: [3, 2, 1], 20: [2, 1], 10: [1], 5: [1], 1: [1],
                 12: [2, 1], 45: [5, 4, 3, 2, 1]}
        for n, expected in cases.items():
            self.assertEqual(wpr.spoken_numbers(n), expected, n)
            self.assertEqual(len(expected), max(1, math.ceil(n * 0.10)))

    def test_per_side_doubles_the_count(self):
        self.assertEqual(wpr.set_count_target({"target": 8, "per_side": True}), 16)
        self.assertEqual(wpr.set_count_target({"target": 30, "per_side": False}), 30)


class ProgressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = wc.load_catalog()
        prefs = wp.validate_preferences({"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20},
                                        catalog)
        cls.plan = wp.build_plan(load_report(), prefs, catalog, video_available=ALL_VIDEOS)

    def test_rejects_foreign_steps_and_bad_status(self):
        with self.assertRaises(ValueError):
            wpr.validate_progress(self.plan, {"items": {"s99-evil": {"sets": []}}})
        uid = self.plan["items"][0]["uid"]
        with self.assertRaises(ValueError):
            wpr.validate_progress(self.plan, {"items": {uid: {"sets": [{"status": "done"}]}}})
        with self.assertRaises(ValueError):
            wpr.validate_progress(self.plan, {"items": {uid: {"sets": [{"status": "completed"}] * 20}}})
        with self.assertRaises(ValueError):
            wpr.validate_state(self.plan, {"phase": "flying"})
        with self.assertRaises(ValueError):
            wpr.validate_state(self.plan, {"announced": ["not-a-step"]})

    def test_counts_are_normalised(self):
        item = self.plan["items"][1]
        target = wpr.set_count_target(item)
        clean = wpr.validate_progress(self.plan, {"items": {item["uid"]: {"sets": [
            {"status": "completed", "count": 0}, {"status": "skipped", "count": 9}][:item["sets"]]}}})
        sets = clean["items"][item["uid"]]["sets"]
        self.assertEqual(sets[0], {"status": "completed", "count": target})
        if len(sets) > 1:
            self.assertEqual(sets[1], {"status": "skipped", "count": 0})

    def test_summary_never_counts_skipped_or_unreached_as_done(self):
        items = self.plan["items"]
        first, second = items[0], items[1]
        progress = wpr.validate_progress(self.plan, {"items": {
            first["uid"]: {"sets": [{"status": "completed"}] * first["sets"]},
            second["uid"]: {"sets": [{"status": "partial", "count": 1}], "skipped": True},
        }, "active_s": 120})
        summary = wpr.build_summary(self.plan, progress, {"difficulty": "too_hard", "felt_pain": False},
                                    "ended_early", "2026-10-27T10:00:00+00:00", "2026-10-27T10:05:00+00:00")
        statuses = {e["uid"]: e["status"] for e in summary["exercises"]}
        self.assertEqual(statuses[first["uid"]], "completed")
        self.assertEqual(statuses[second["uid"]], "partial")
        self.assertTrue(all(statuses[i["uid"]] == "not_reached" for i in items[2:]))
        self.assertEqual(summary["counts"]["completed"], 1)
        self.assertEqual(summary["elapsed_s"], 300)
        self.assertEqual(summary["active_s"], 120)
        self.assertLess(summary["completed_work_s"], summary["planned_work_s"])
        text = " ".join(summary["next_session"]).lower()
        self.assertIn("ended early", text)
        self.assertIn("not reached", text)
        self.assertIn("did not detect", summary["counting_note"])

    def test_pain_feedback_advises_assessment(self):
        progress = wpr.validate_progress(self.plan, {"items": {}})
        summary = wpr.build_summary(self.plan, progress, {"felt_pain": True}, "ended_early")
        self.assertIn("physiotherapist", summary["next_session"][0])


if __name__ == "__main__":
    unittest.main()
