"""Unit tests for LiveAudioCoach in live_audio_coach.py."""

import unittest
from unittest.mock import MagicMock, patch
from basketball.coaching.live_audio_coach import (
    LiveAudioCoach,
    HISTORICAL_CUE_TEMPLATES,
    GENERIC_SETUP_CUE,
)


class LiveAudioCoachTests(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        # Default mock: no active remediation, 0 approved shots
        self.mock_db.get_active_remediation.return_value = None
        self.mock_db.get_shots.return_value = []

    def test_generic_setup_cue_when_no_history_or_remediation(self):
        """When player has < 5 approved shots and no remediation, coach falls back to generic setup reminder."""
        coach = LiveAudioCoach(db=self.mock_db, player_id="new_player")
        self.assertEqual(coach.current_focus, "setup")
        self.assertEqual(coach.current_caption, GENERIC_SETUP_CUE["caption"])

        # First pre-rep event in idle state
        event = coach.on_frame(
            current_phase="idle",
            previous_phase="idle",
            angles={},
            landmarks={},
            valid=None,
            timestamp_ms=1000,
        )
        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "setup_cue")
        self.assertEqual(event["text"], GENERIC_SETUP_CUE["speech"])
        self.assertTrue(event["speak"])

    def test_historical_active_remediation_sets_focus(self):
        """Active remediation with evidence sets pre-rep focus cue."""
        self.mock_db.get_active_remediation.return_value = {
            "player_id": "player",
            "targeted_flaw": "Incomplete Release Extension",
            "status": "active",
        }
        coach = LiveAudioCoach(db=self.mock_db, player_id="player")
        self.assertEqual(coach.current_focus, "arm_extension")
        self.assertIn("elbow", coach.current_caption.lower())

        event = coach.on_frame(
            current_phase="idle",
            previous_phase="idle",
            angles={},
            landmarks={},
            valid=None,
            timestamp_ms=1000,
        )
        self.assertIsNotNone(event)
        self.assertTrue(event["speak"])
        self.assertEqual(
            event["text"],
            "Try finishing with your elbow higher through release.",
        )

    @patch("basketball.coaching.live_audio_coach.BaselineEngine")
    @patch("basketball.coaching.live_audio_coach.CoachEngine")
    def test_historical_baseline_sets_focus_when_sample_sufficient(
        self, mock_coach_cls, mock_baseline_cls
    ):
        """When >= 5 approved shots exist, coach computes baseline and sets focus."""
        # 6 approved shots
        self.mock_db.get_shots.return_value = [{"shot_id": f"s{i}"} for i in range(6)]
        mock_baseline_engine = MagicMock()
        mock_baseline_cls.return_value = mock_baseline_engine
        mock_baseline_engine.compute_baseline.return_value = {
            "status": "VALID_BASELINE",
            "sample_size_total": 6,
        }

        mock_coach = MagicMock()
        mock_coach_cls.return_value = mock_coach
        mock_coach.generate_primary_cue.return_value = {
            "priority_tier": 1,
            "targeted_flaw": "Kinetic Sequencing Delay",
        }

        coach = LiveAudioCoach(db=self.mock_db, player_id="player")
        self.assertEqual(coach.current_focus, "kinetic_sequencing")
        self.assertIn("legs", coach.current_caption.lower())

        event = coach.on_frame(
            current_phase="idle",
            previous_phase="idle",
            angles={},
            landmarks={},
            valid=None,
            timestamp_ms=1000,
        )
        self.assertIsNotNone(event)
        self.assertEqual(
            event["text"],
            "Try letting your legs start the shot before your arm extends.",
        )

    def test_session_observation_detects_low_elbow_extension(self):
        """When history is insufficient, live observations with sufficient confidence trigger feedback."""
        coach = LiveAudioCoach(db=self.mock_db, player_id="test_player")

        # Initial idle setup cue
        coach.on_frame("idle", "idle", {}, {}, None, 1000)

        # Shot in flight with low release elbow (135 deg < 150 deg threshold) and high landmark visibility (0.9)
        landmarks = {12: {"visibility": 0.9}, 14: {"visibility": 0.9}, 16: {"visibility": 0.9}}
        angles = {"elbow_shooting": 135.0, "knee_shooting": 140.0}

        coach.on_frame("preparing", "idle", angles, landmarks, None, 1050)
        coach.on_frame("releasing", "preparing", angles, landmarks, None, 1100)
        coach.on_frame("follow_through", "releasing", angles, landmarks, None, 1150)

        # Transition back to idle (shot completed)
        event = coach.on_frame("idle", "follow_through", angles, landmarks, None, 1200)

        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "shot_feedback")
        self.assertTrue(event["speak"])
        self.assertEqual(coach.current_focus, "arm_extension")
        self.assertEqual(
            event["text"],
            "Try extending your shooting arm fully through release.",
        )

    def test_confidence_gating_suppresses_mechanics_cues_when_low_visibility(self):
        """When landmark visibility is < 0.45, mechanics feedback is suppressed."""
        coach = LiveAudioCoach(db=self.mock_db, player_id="test_player")
        coach.on_frame("idle", "idle", {}, {}, None, 1000)

        # Low visibility (0.2)
        landmarks = {12: {"visibility": 0.2}, 14: {"visibility": 0.1}, 16: {"visibility": 0.2}}
        angles = {"elbow_shooting": 130.0}

        coach.on_frame("releasing", "idle", angles, landmarks, None, 1100)
        event = coach.on_frame("idle", "releasing", angles, landmarks, None, 1200)

        self.assertIsNotNone(event)
        self.assertEqual(event["confidence"], "insufficient")
        self.assertFalse(event["speak"])
        self.assertEqual(event["text"], "")

    def test_event_deduplication_does_not_repeat_same_focus(self):
        """Coach does not repeat the identical cue on subsequent shots unless focus changes."""
        coach = LiveAudioCoach(db=self.mock_db, player_id="test_player")
        coach.on_frame("idle", "idle", {}, {}, None, 1000)

        landmarks = {12: {"visibility": 0.9}, 14: {"visibility": 0.9}, 16: {"visibility": 0.9}}
        angles = {"elbow_shooting": 135.0}

        # Shot 1: triggers arm extension feedback
        coach.on_frame("releasing", "idle", angles, landmarks, None, 1100)
        evt1 = coach.on_frame("idle", "releasing", angles, landmarks, None, 1200)
        self.assertTrue(evt1["speak"])

        # Shot 2: same flaw, same focus -> should NOT speak again
        coach.on_frame("releasing", "idle", angles, landmarks, None, 2100)
        evt2 = coach.on_frame("idle", "releasing", angles, landmarks, None, 2200)
        self.assertFalse(evt2["speak"])
        self.assertEqual(evt2["text"], "")

    def test_session_recap_never_announces_makes_or_misses(self):
        """End of set recap summarizes reps and focus without speaking makes or misses."""
        coach = LiveAudioCoach(db=self.mock_db, player_id="test_player")
        recap = coach.get_session_recap(total_shots=10)

        self.assertEqual(recap["event_type"], "recap")
        self.assertTrue(recap["speak"])
        self.assertIn("10 shots tracked", recap["text"])

        # Strictly never announce makes or misses
        lower_text = recap["text"].lower()
        self.assertNotIn("make", lower_text)
        self.assertNotIn("miss", lower_text)
        self.assertNotIn("made", lower_text)
        self.assertNotIn("missed", lower_text)
        self.assertNotIn("%", lower_text)

    def test_suggestive_tone_enforced_across_all_templates(self):
        """All cue templates must use suggestive language, never guarantees or causal promises."""
        guarantee_words = ["guarantee", "will make", "ensures", "perfect", "fault"]
        for key, template in HISTORICAL_CUE_TEMPLATES.items():
            speech = template["speech"].lower()
            for word in guarantee_words:
                self.assertNotIn(word, speech, f"Found non-suggestive word '{word}' in {key}")

        setup_speech = GENERIC_SETUP_CUE["speech"].lower()
        for word in guarantee_words:
            self.assertNotIn(word, setup_speech)


if __name__ == "__main__":
    unittest.main()

