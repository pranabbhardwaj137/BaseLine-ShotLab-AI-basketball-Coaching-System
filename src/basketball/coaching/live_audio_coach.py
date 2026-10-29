"""Live Practice audio coach.

Provides evidence-gated, rules-based audio cues and text captions during live camera
Practice sessions without external network requests or heavy speech models.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from basketball.analysis.baseline_engine import BaselineEngine, MIN_BASELINE_SAMPLE_SIZE
from basketball.coaching.coach_engine import CoachEngine
from basketball.persistence.shot_lab_db import ShotLabDB

logger = logging.getLogger("basketball.live_audio_coach")

# Suggestive, evidence-grounded phrasing templates (strictly suggestions, zero guarantees)
HISTORICAL_CUE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "Kinetic Sequencing Delay": {
        "focus": "kinetic_sequencing",
        "speech": "Try letting your legs start the shot before your arm extends.",
        "caption": "Focus: Let legs drive before arm extends",
    },
    "Incomplete Release Extension": {
        "focus": "arm_extension",
        "speech": "Try finishing with your elbow higher through release.",
        "caption": "Focus: Finish with elbow high and arm extended",
    },
    "Torso Sway / Base Instability": {
        "focus": "torso_sway",
        "speech": "Try keeping your torso balanced and your base solid through the dip.",
        "caption": "Focus: Keep torso balanced through the dip",
    },
    "None": {
        "focus": "maintenance",
        "speech": "Maintain your smooth shooting rhythm.",
        "caption": "Focus: Maintain smooth shooting rhythm",
    },
}

GENERIC_SETUP_CUE: Dict[str, str] = {
    "focus": "setup",
    "speech": "Set your feet and balance before shooting.",
    "caption": "Focus: Set feet and balance before shooting",
}


class LiveAudioCoach:
    """Manages audio cues, text captions, and event gating for live Practice."""

    def __init__(
        self,
        db: Optional[ShotLabDB] = None,
        player_id: str = "player",
        shot_style: str = "jump_shot",
        camera_view: str = "side_90",
        shot_type: str = "catch_and_shoot",
    ):
        self.db = db or ShotLabDB()
        self.player_id = player_id
        self.shot_style = shot_style
        self.camera_view = camera_view
        self.shot_type = shot_type

        # Current coaching focus & caption
        self.current_focus: str = "setup"
        self.current_caption: str = GENERIC_SETUP_CUE["caption"]
        self.last_spoken_focus: Optional[str] = None
        self.last_spoken_text: Optional[str] = None
        self.has_spoken_setup: bool = False

        # Live session tracking
        self.session_shots_count: int = 0
        self.in_flight_metrics: Dict[str, Any] = {}
        self.recent_shot_flaws: List[str] = []

        # Load player history focus if valid evidence exists
        self._init_historical_focus()

    def _init_historical_focus(self) -> None:
        """Query DB for active remediation or valid baseline meeting sample size requirements."""
        try:
            # 1. Check active remediation first
            active = self.db.get_active_remediation(self.player_id)
            if active and active.get("targeted_flaw") in HISTORICAL_CUE_TEMPLATES:
                template = HISTORICAL_CUE_TEMPLATES[active["targeted_flaw"]]
                self.current_focus = template["focus"]
                self.current_caption = template["caption"]
                return

            # 2. Check baseline if player has >= MIN_BASELINE_SAMPLE_SIZE approved shots
            approved_shots = self.db.get_shots(
                player_id=self.player_id,
                camera_view=self.camera_view,
                shot_type=self.shot_type,
                shot_style=self.shot_style,
                review_status="approved",
                min_confidence="SUFFICIENT",
            )
            if len(approved_shots) >= MIN_BASELINE_SAMPLE_SIZE:
                engine = BaselineEngine(self.db)
                baseline = engine.compute_baseline(
                    player_id=self.player_id,
                    camera_view=self.camera_view,
                    shot_type=self.shot_type,
                    shot_style=self.shot_style,
                    require_human_confirmed=True,
                    save_to_db=False,
                )
                if baseline.get("status") == "VALID_BASELINE":
                    coach = CoachEngine(self.db)
                    cue = coach.generate_primary_cue(baseline, save_to_db=False)
                    flaw = cue.get("targeted_flaw", "None")
                    template = HISTORICAL_CUE_TEMPLATES.get(flaw, HISTORICAL_CUE_TEMPLATES["None"])
                    self.current_focus = template["focus"]
                    self.current_caption = template["caption"]
                    return
        except Exception as exc:
            logger.debug("LiveAudioCoach history lookup error: %s", exc)

        # Fallback if insufficient history
        self.current_focus = "setup"
        self.current_caption = GENERIC_SETUP_CUE["caption"]

    def reset(
        self,
        player_id: Optional[str] = None,
        shot_style: Optional[str] = None,
        camera_view: Optional[str] = None,
        shot_type: Optional[str] = None,
    ) -> None:
        """Reset session counters and re-evaluate focus."""
        if player_id:
            self.player_id = player_id
        if shot_style:
            self.shot_style = shot_style
        if camera_view:
            self.camera_view = camera_view
        if shot_type:
            self.shot_type = shot_type

        self.session_shots_count = 0
        self.in_flight_metrics.clear()
        self.recent_shot_flaws.clear()
        self.last_spoken_focus = None
        self.last_spoken_text = None
        self.has_spoken_setup = False
        self._init_historical_focus()

    def on_frame(
        self,
        current_phase: str,
        previous_phase: str,
        angles: Dict[str, float],
        landmarks: Dict[int, Dict[str, float]],
        valid: Optional[Dict[int, bool]],
        timestamp_ms: int,
    ) -> Optional[Dict[str, Any]]:
        """Process live frame phase state and return an audio cue event if a transition warrants speech."""
        event: Optional[Dict[str, Any]] = None

        # 1. During an active shot, accumulate kinematic measurements
        if current_phase in ("preparing", "set_point", "releasing", "follow_through"):
            if not self.in_flight_metrics:
                self.in_flight_metrics = {
                    "start_ts": timestamp_ms,
                    "min_knee_flexion": 180.0,
                    "release_elbow_angle": None,
                    "landmark_visibilities": [],
                }

            knee_ang = angles.get("knee_shooting") or angles.get("knee_shooting_3d")
            if knee_ang is not None and knee_ang < self.in_flight_metrics["min_knee_flexion"]:
                self.in_flight_metrics["min_knee_flexion"] = float(knee_ang)

            elbow_ang = angles.get("elbow_shooting") or angles.get("elbow_shooting_3d")
            if current_phase in ("releasing", "follow_through") and elbow_ang is not None:
                curr_release = self.in_flight_metrics.get("release_elbow_angle")
                if curr_release is None or elbow_ang > curr_release:
                    self.in_flight_metrics["release_elbow_angle"] = float(elbow_ang)

            # Sample landmark visibility for confidence gating
            if landmarks:
                side = angles.get("shooting_side", "right")
                key_indices = [12, 14, 16, 24, 26] if side == "right" else [11, 13, 15, 23, 25]
                vis_vals = [landmarks[idx].get("visibility", 0.0) for idx in key_indices if idx in landmarks]
                if vis_vals:
                    self.in_flight_metrics["landmark_visibilities"].extend(vis_vals)

        # 2. Shot completed event (transition from release/follow-through back to idle)
        if previous_phase in ("releasing", "follow_through") and current_phase == "idle":
            self.session_shots_count += 1
            event = self._evaluate_completed_shot(timestamp_ms)
            self.in_flight_metrics.clear()
            return event

        # 3. Pre-rep setup cue (when in idle before or between shots)
        if current_phase == "idle" and not self.has_spoken_setup:
            self.has_spoken_setup = True
            event = self._get_setup_cue()
            return event

        return None

    def _evaluate_completed_shot(self, timestamp_ms: int) -> Optional[Dict[str, Any]]:
        """Evaluate completed shot kinematics and produce brief feedback if supported by measurements."""
        if not self.in_flight_metrics:
            return None

        # Check tracking confidence: mean visibility must be >= 0.45
        vis_list = self.in_flight_metrics.get("landmark_visibilities", [])
        avg_vis = sum(vis_list) / len(vis_list) if vis_list else 0.0

        if avg_vis < 0.45:
            # Low tracking confidence: DO NOT speak mechanics cues!
            return {
                "event_type": "shot_feedback",
                "text": "",
                "caption": self.current_caption,
                "focus": self.current_focus,
                "speak": False,
                "confidence": "insufficient",
                "reason": "Pose confidence insufficient to evaluate mechanics.",
            }

        # Reliable measurements available
        elbow_rel = self.in_flight_metrics.get("release_elbow_angle")
        min_knee = self.in_flight_metrics.get("min_knee_flexion")

        new_focus = self.current_focus
        feedback_speech = ""
        feedback_caption = self.current_caption

        # Coaching heuristic evaluation
        if elbow_rel is not None and elbow_rel < 150.0:
            new_focus = "arm_extension"
            feedback_speech = "Try extending your shooting arm fully through release."
            feedback_caption = "Focus: Extend arm fully through release"
        elif min_knee is not None and min_knee > 165.0:
            new_focus = "knee_dip"
            feedback_speech = "Try dipping deeper with your knees for rhythm."
            feedback_caption = "Focus: Dip deeper with knees for rhythm"
        elif elbow_rel is not None and elbow_rel >= 160.0 and self.current_focus == "arm_extension":
            new_focus = "maintenance"
            feedback_speech = "Great extension on that finish."
            feedback_caption = "Form: Great arm extension on that shot"

        # Update caption immediately
        self.current_caption = feedback_caption

        # Deduplication: speak ONLY if the focus changed and text is new
        should_speak = (new_focus != self.last_spoken_focus) and bool(feedback_speech)
        if should_speak:
            self.last_spoken_focus = new_focus
            self.last_spoken_text = feedback_speech
            self.current_focus = new_focus

        return {
            "event_type": "shot_feedback",
            "text": feedback_speech if should_speak else "",
            "caption": self.current_caption,
            "focus": self.current_focus,
            "speak": should_speak,
            "confidence": "sufficient",
            "measurements": {
                "release_elbow_angle": elbow_rel,
                "min_knee_flexion": min_knee,
                "avg_visibility": round(avg_vis, 2),
            },
        }

    def _get_setup_cue(self) -> Dict[str, Any]:
        """Generate brief pre-rep setup cue."""
        text = ""
        for flaw, template in HISTORICAL_CUE_TEMPLATES.items():
            if template["focus"] == self.current_focus:
                text = template["speech"]
                self.current_caption = template["caption"]
                break

        if not text:
            text = GENERIC_SETUP_CUE["speech"]
            self.current_caption = GENERIC_SETUP_CUE["caption"]

        should_speak = (self.current_focus != self.last_spoken_focus)
        if should_speak:
            self.last_spoken_focus = self.current_focus
            self.last_spoken_text = text

        return {
            "event_type": "setup_cue",
            "text": text if should_speak else "",
            "caption": self.current_caption,
            "focus": self.current_focus,
            "speak": should_speak,
            "confidence": "sufficient",
        }

    def get_session_recap(self, total_shots: int) -> Dict[str, Any]:
        """Generate a short recap when the user ends a set or session.
        
        Strictly never announces makes or misses in speech.
        """
        if total_shots <= 0:
            text = "Practice session ended. Good session."
            caption = "Practice session ended"
        else:
            focus_reminders = {
                "arm_extension": "Focus on high arm extension in your next set.",
                "knee_dip": "Focus on fluid knee dip in your next set.",
                "kinetic_sequencing": "Focus on legs-first timing in your next set.",
                "torso_sway": "Focus on balanced posture in your next set.",
                "maintenance": "Maintain your repeatable rhythm in your next set.",
                "setup": "Focus on balanced footwork in your next set.",
            }
            reminder = focus_reminders.get(self.current_focus, "Keep building repeatable mechanics.")
            text = f"Set complete: {total_shots} shot{'s' if total_shots != 1 else ''} tracked. {reminder}"
            caption = f"Set complete: {total_shots} shots tracked"

        return {
            "event_type": "recap",
            "text": text,
            "caption": caption,
            "focus": self.current_focus,
            "speak": True,
            "total_shots": total_shots,
        }

