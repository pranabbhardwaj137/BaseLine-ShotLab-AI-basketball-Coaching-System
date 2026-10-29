"""Unit tests for DrillBounceTracker, DrillPostureTracker, and DrillTrackingEngine."""

import unittest
from pathlib import Path
import numpy as np

from basketball.coaching.drills_catalog import get_drill_by_id
from basketball.services.drill_service import (
    DrillBounceTracker,
    DrillPostureTracker,
    DrillStyleTracker,
    DrillTrackingEngine,
)


class TestDrillBounceTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = DrillBounceTracker(min_cooldown_ms=220, min_excursion=0.12)

    def test_initial_state(self):
        self.assertEqual(self.tracker.reps, 0)
        self.assertEqual(len(self.tracker.rep_timestamps), 0)
        self.assertIsNone(self.tracker.get_rhythm_score())

    def test_single_ground_bounce_inflection(self):
        # Simulate ball moving downward from knee release (0.50) to floor (0.74) near ankles (0.75)
        # Frame 1: at waist/knee release height
        b, r = self.tracker.update(norm_y=0.50, norm_x=0.5, ts_ms=100, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0)

        # Frame 2: moving down
        b, r = self.tracker.update(norm_y=0.62, norm_x=0.5, ts_ms=150, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0)

        # Frame 3: reaches floor (peak y = 0.74)
        b, r = self.tracker.update(norm_y=0.74, norm_x=0.5, ts_ms=200, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0)

        # Frame 4: rebounds upward to 0.65 (reversal detected!)
        b, r = self.tracker.update(norm_y=0.65, norm_x=0.5, ts_ms=250, knee_y=0.60, ankle_y=0.75)
        self.assertTrue(b)
        self.assertEqual(r, 1)
        self.assertEqual(len(self.tracker.rep_timestamps), 1)

    def test_rejection_of_slight_hand_jiggle_at_waist(self):
        # Simulate minor twitch/hand movement at waist (y=0.48 -> 0.53 -> 0.49)
        self.tracker.update(norm_y=0.48, norm_x=0.5, ts_ms=100, knee_y=0.60, ankle_y=0.75)
        self.tracker.update(norm_y=0.53, norm_x=0.5, ts_ms=150, knee_y=0.60, ankle_y=0.75)
        b, r = self.tracker.update(norm_y=0.49, norm_x=0.5, ts_ms=200, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0, "Waist hand jiggle must NOT count as a rep")

    def test_rejection_of_small_knee_level_jitter(self):
        # Movement from 0.58 -> 0.63 -> 0.59 (only 0.05 excursion, never reaches floor)
        self.tracker.update(norm_y=0.58, norm_x=0.5, ts_ms=100, knee_y=0.60, ankle_y=0.75)
        self.tracker.update(norm_y=0.63, norm_x=0.5, ts_ms=150, knee_y=0.60, ankle_y=0.75)
        b, r = self.tracker.update(norm_y=0.59, norm_x=0.5, ts_ms=200, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0, "Incomplete vertical descent must NOT count as a rep")

    def test_cooldown_prevents_double_counting(self):
        # First bounce
        self.tracker.update(norm_y=0.50, norm_x=0.5, ts_ms=100, knee_y=0.60, ankle_y=0.75)
        self.tracker.update(norm_y=0.72, norm_x=0.5, ts_ms=150, knee_y=0.60, ankle_y=0.75)
        b1, _ = self.tracker.update(norm_y=0.64, norm_x=0.5, ts_ms=200, knee_y=0.60, ankle_y=0.75)
        self.assertTrue(b1)
        self.assertEqual(self.tracker.reps, 1)

        # Immediate micro-jitter 40ms later (less than 220ms cooldown)
        self.tracker.update(norm_y=0.71, norm_x=0.5, ts_ms=220, knee_y=0.60, ankle_y=0.75)
        b2, r2 = self.tracker.update(norm_y=0.65, norm_x=0.5, ts_ms=240, knee_y=0.60, ankle_y=0.75)
        self.assertFalse(b2)
        self.assertEqual(r2, 1)

    def test_rejection_above_knee_plane(self):
        # Inflection at chest level (y = 0.35, knee = 0.65) should NOT trigger floor bounce
        self.tracker.update(norm_y=0.20, norm_x=0.5, ts_ms=100, knee_y=0.65, ankle_y=0.75)
        self.tracker.update(norm_y=0.35, norm_x=0.5, ts_ms=150, knee_y=0.65, ankle_y=0.75)
        b, r = self.tracker.update(norm_y=0.28, norm_x=0.5, ts_ms=200, knee_y=0.65, ankle_y=0.75)
        self.assertFalse(b)
        self.assertEqual(r, 0)

    def test_rhythm_score_calculation(self):
        # 5 evenly spaced bounces at 400ms intervals
        self.tracker.rep_timestamps = [400, 800, 1200, 1600, 2000]
        score = self.tracker.get_rhythm_score()
        self.assertIsNotNone(score)
        self.assertGreater(score, 0.95)

    def test_reset_clears_all(self):
        self.tracker.reps = 10
        self.tracker.rep_timestamps = [100, 200]
        self.tracker.reset()
        self.assertEqual(self.tracker.reps, 0)
        self.assertEqual(len(self.tracker.rep_timestamps), 0)


class TestDrillStyleTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = DrillStyleTracker(
            target_sequence=["POUND", "POUND", "CROSSOVER"],
            sequence_desc="2 Pounds + 1 Crossover",
        )

    def test_crossover_classification(self):
        # Body midline is at 0.50
        # Bounce 1: Left side pound (x=0.25)
        ev1 = self.tracker.on_bounce(norm_x=0.25, norm_y=0.74, ts_ms=500, midline_x=0.50)
        self.assertEqual(ev1["move_type"], "POUND")
        self.assertEqual(ev1["combos_completed"], 0)
        self.assertEqual(ev1["combo_step"], 1)

        # Bounce 2: Second Left side pound (x=0.26, delta_x=0.01)
        ev2 = self.tracker.on_bounce(norm_x=0.26, norm_y=0.74, ts_ms=900, midline_x=0.50)
        self.assertEqual(ev2["move_type"], "POUND")
        self.assertEqual(ev2["combo_step"], 2)

        # Bounce 3: Crossover to Right side (x=0.70, crossed midline)
        ev3 = self.tracker.on_bounce(norm_x=0.70, norm_y=0.74, ts_ms=1300, midline_x=0.50)
        self.assertEqual(ev3["move_type"], "CROSSOVER")
        self.assertIn("L -> R", ev3["move_label"])
        self.assertTrue(ev3["combo_completed"])
        self.assertEqual(ev3["combos_completed"], 1)
        self.assertEqual(ev3["combo_step"], 0)
        self.assertEqual(ev3["style_match_pct"], 100.0)

    def test_v_dribble_classification(self):
        tracker = DrillStyleTracker(target_sequence=["POUND", "V_DRIBBLE"])
        # Bounce 1: Right side pound at 0.72
        tracker.on_bounce(norm_x=0.72, norm_y=0.74, ts_ms=500, midline_x=0.50)

        # Bounce 2: In-and-out sweep on same right side (0.72 -> 0.60, dx=0.12, stays right of 0.50)
        ev2 = tracker.on_bounce(norm_x=0.60, norm_y=0.74, ts_ms=900, midline_x=0.50)
        self.assertEqual(ev2["move_type"], "V_DRIBBLE")
        self.assertTrue(ev2["combo_completed"])
        self.assertEqual(ev2["combos_completed"], 1)

    def test_mismatched_sequence_breaks_combo(self):
        # Expecting POUND -> POUND -> CROSSOVER
        # Bounce 1: Pound
        self.tracker.on_bounce(norm_x=0.25, norm_y=0.74, ts_ms=500, midline_x=0.50)
        # Bounce 2: Immediate crossover (premature cross)
        ev2 = self.tracker.on_bounce(norm_x=0.70, norm_y=0.74, ts_ms=900, midline_x=0.50)
        self.assertEqual(ev2["move_type"], "CROSSOVER")
        self.assertFalse(ev2["combo_completed"])
        self.assertEqual(ev2["combos_completed"], 0)
        self.assertEqual(ev2["combo_step"], 0)
        self.assertEqual(ev2["style_match_pct"], 50.0)


class TestDrillPostureTracker(unittest.TestCase):
    def setUp(self):
        ref_bio = {
            "knee_angle_mean": 153.5,
            "knee_angle_range": [145.0, 163.0],
            "hip_angle_mean": 121.6,
            "hip_angle_range": [110.0, 130.0],
            "head_pitch_threshold": 0.04,
        }
        self.tracker = DrillPostureTracker(ref_bio)

    def _make_landmarks(self, knee_bend=True, eyes_up=True, back_straight=True):
        """Construct synthetic 33-point landmarks."""
        lm = {}
        for i in range(33):
            lm[i] = {"norm_x": 0.5, "norm_y": 0.5, "norm_z": 0.0, "visibility": 0.9, "presence": 0.9}

        # Head / Ears / Nose
        lm[0] = {"norm_x": 0.5, "norm_y": 0.20 if eyes_up else 0.26, "visibility": 0.9, "presence": 0.9}
        lm[7] = {"norm_x": 0.45, "norm_y": 0.20, "visibility": 0.9, "presence": 0.9}
        lm[8] = {"norm_x": 0.55, "norm_y": 0.20, "visibility": 0.9, "presence": 0.9}

        # Shoulders
        lm[11] = {"norm_x": 0.42, "norm_y": 0.32, "visibility": 0.9, "presence": 0.9}
        lm[12] = {"norm_x": 0.58, "norm_y": 0.32, "visibility": 0.9, "presence": 0.9}

        # Hips (23, 24)
        lm[23] = {"norm_x": 0.45, "norm_y": 0.50, "visibility": 0.9, "presence": 0.9}
        lm[24] = {"norm_x": 0.55, "norm_y": 0.50, "visibility": 0.9, "presence": 0.9}

        # Knees (25, 26) & Ankles (27, 28)
        if knee_bend:
            # Bent knees in athletic stance: knee slightly forward (x offset)
            lm[25] = {"norm_x": 0.49, "norm_y": 0.65, "visibility": 0.9, "presence": 0.9}
            lm[26] = {"norm_x": 0.59, "norm_y": 0.65, "visibility": 0.9, "presence": 0.9}
            lm[27] = {"norm_x": 0.45, "norm_y": 0.85, "visibility": 0.9, "presence": 0.9}
            lm[28] = {"norm_x": 0.55, "norm_y": 0.85, "visibility": 0.9, "presence": 0.9}
        else:
            # Perfectly straight knees (standing upright)
            lm[25] = {"norm_x": 0.45, "norm_y": 0.67, "visibility": 0.9, "presence": 0.9}
            lm[26] = {"norm_x": 0.55, "norm_y": 0.67, "visibility": 0.9, "presence": 0.9}
            lm[27] = {"norm_x": 0.45, "norm_y": 0.85, "visibility": 0.9, "presence": 0.9}
            lm[28] = {"norm_x": 0.55, "norm_y": 0.85, "visibility": 0.9, "presence": 0.9}

        return lm

    def test_evaluate_bent_knees_in_stance(self):
        lm = self._make_landmarks(knee_bend=True, eyes_up=True)
        res = self.tracker.evaluate_frame(lm)
        self.assertTrue(res["pose_detected"])
        self.assertIsNotNone(res["knee_angle"])
        self.assertTrue(res["knees_bent"])
        self.assertTrue(res["eyes_up"])
        self.assertIn("athletic", res["live_cue"].lower())

    def test_evaluate_straight_knees_prompts_bend_cue(self):
        lm = self._make_landmarks(knee_bend=False, eyes_up=True)
        res = self.tracker.evaluate_frame(lm)
        self.assertTrue(res["pose_detected"])
        self.assertGreater(res["knee_angle"], 170.0)
        self.assertFalse(res["knees_bent"])
        self.assertIn("bend", res["live_cue"].lower())

    def test_evaluate_head_down_prompts_eyes_up_cue(self):
        lm = self._make_landmarks(knee_bend=True, eyes_up=False)
        res = self.tracker.evaluate_frame(lm)
        self.assertFalse(res["eyes_up"])
        self.assertIn("eyes", res["live_cue"].lower())

    def test_summary_accumulation(self):
        # 3 bent knee frames, 1 straight knee frame
        for _ in range(3):
            self.tracker.evaluate_frame(self._make_landmarks(knee_bend=True, eyes_up=True))
        self.tracker.evaluate_frame(self._make_landmarks(knee_bend=False, eyes_up=True))

        summary = self.tracker.get_summary()
        self.assertEqual(summary["total_frames"], 4)
        self.assertEqual(summary["pose_frames"], 4)
        self.assertEqual(summary["knees_bent_pct"], 75.0)
        self.assertEqual(summary["eyes_up_pct"], 100.0)


class TestDrillTrackingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = DrillTrackingEngine(weights_path="models/best.pt")

    def test_start_session(self):
        res = self.engine.start_session("pound_plus_cross")
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["drill_id"], "pound_plus_cross")
        self.assertEqual(res["drill_name"], "Pound + Crossover")
        self.assertEqual(res["target_sequence"], ["POUND", "POUND", "CROSSOVER"])
        self.assertIn("knee_angle_mean", res["reference_biomechanics"])
        self.assertTrue(self.engine.is_active)

    def test_process_synthetic_frame(self):
        self.engine.start_session("pound_plus_cross")
        frame = np.zeros((360, 480, 3), dtype=np.uint8)
        res = self.engine.process_frame(frame, client_timestamp_ms=100)

        self.assertEqual(res["status"], "ok")
        self.assertIn("ball", res)
        self.assertIn("bounce_event", res)
        self.assertIn("rep_count", res)
        self.assertIn("current_move", res)
        self.assertIn("combos_completed", res)
        self.assertIn("combo_progress", res)
        self.assertIn("style_match_pct", res)
        self.assertIn("angles", res)
        self.assertIn("posture", res)
        self.assertIn("live_cue", res)
        self.assertIn("reference_target", res)

    def test_stop_session_returns_honest_feedback(self):
        self.engine.start_session("pound_plus_cross")
        frame = np.zeros((360, 480, 3), dtype=np.uint8)
        self.engine.process_frame(frame, client_timestamp_ms=100)
        self.engine.process_frame(frame, client_timestamp_ms=200)

        summary = self.engine.stop_session()
        self.assertFalse(self.engine.is_active)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["drill_id"], "pound_plus_cross")
        self.assertIn("rep_count", summary)
        self.assertIn("combos_completed", summary)
        self.assertIn("style_match_pct", summary)
        self.assertIn("sequence_description", summary)
        self.assertIn("duration_seconds", summary)
        self.assertIn("posture_summary", summary)
        self.assertIn("feedback_items", summary)
        self.assertIsInstance(summary["feedback_items"], list)
        self.assertGreater(len(summary["feedback_items"]), 0)


if __name__ == "__main__":
    unittest.main()
