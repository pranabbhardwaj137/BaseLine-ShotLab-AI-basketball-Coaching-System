"""Live camera tracking engine for real-time web HUD overlay.

Processes camera frames from the browser, running MediaPipe pose estimation,
YOLO ball and rim tracking, shot-phase detection, real-time shot statistics,
and evidence-gated live Practice audio coaching.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from basketball.coaching.live_audio_coach import LiveAudioCoach
from basketball.core.analyzer import ShotPhaseDetector, compute_all_angles
from basketball.core.pose_engine import PoseEngine
from basketball.tracking.ball_tracker import BallTracker

logger = logging.getLogger("basketball.live_service")


class LiveCameraEngine:
    """Manages real-time live camera analysis for the browser HUD overlay."""

    def __init__(self, weights_path: Optional[str] = None):
        self.lock = threading.Lock()
        self.weights_path = weights_path
        self.pose_engine: Optional[PoseEngine] = None
        self.ball_tracker: Optional[BallTracker] = None
        self.phase_detector: Optional[ShotPhaseDetector] = None
        self.audio_coach: Optional[LiveAudioCoach] = None

        self.frame_index = 0
        self.last_timestamp_ms = 0
        self.current_phase = "idle"
        self.previous_phase = "idle"
        self.active_shot_uid: Optional[str] = None

        self.session_makes = 0
        self.session_misses = 0
        self.session_total = 0
        self.last_shot_outcome: Optional[str] = None
        self.last_shot_conf: float = 0.0

        self._init_engines()

    def _init_engines(self) -> None:
        try:
            self.pose_engine = PoseEngine()
        except Exception as exc:
            logger.warning("LiveCameraEngine: PoseEngine init note: %s", exc)
            self.pose_engine = None

        try:
            w_path = self.weights_path
            if not w_path:
                if Path("models/best.pt").is_file():
                    w_path = "models/best.pt"
                elif Path("models/ballRim.pt").is_file():
                    w_path = "models/ballRim.pt"
            self.ball_tracker = BallTracker(weights_path=w_path, conf=0.25, detect_every=1)
        except Exception as exc:
            logger.warning("LiveCameraEngine: BallTracker init note: %s", exc)
            self.ball_tracker = None

        try:
            self.phase_detector = ShotPhaseDetector()
        except Exception as exc:
            logger.warning("LiveCameraEngine: ShotPhaseDetector init note: %s", exc)
            self.phase_detector = None

        try:
            self.audio_coach = LiveAudioCoach()
        except Exception as exc:
            logger.warning("LiveCameraEngine: LiveAudioCoach init note: %s", exc)
            self.audio_coach = None

    def reset_session(
        self,
        player_id: Optional[str] = None,
        shot_style: Optional[str] = None,
        camera_view: Optional[str] = None,
        shot_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reset live statistics, active shot state, ball trajectory trails, and coach focus."""
        with self.lock:
            self.session_makes = 0
            self.session_misses = 0
            self.session_total = 0
            self.active_shot_uid = None
            self.current_phase = "idle"
            self.previous_phase = "idle"
            self.last_shot_outcome = None
            self.last_shot_conf = 0.0
            if self.ball_tracker is not None:
                self.ball_tracker.reset()
            if self.audio_coach is not None:
                self.audio_coach.reset(
                    player_id=player_id,
                    shot_style=shot_style,
                    camera_view=camera_view,
                    shot_type=shot_type,
                )
            return {
                "makes": 0,
                "misses": 0,
                "total": 0,
                "accuracy": 0.0,
                "caption": self.audio_coach.current_caption if self.audio_coach else "",
                "focus": self.audio_coach.current_focus if self.audio_coach else "setup",
            }

    def get_session_recap(self) -> Dict[str, Any]:
        """Generate a short recap when the user completes a set or session."""
        with self.lock:
            if self.audio_coach is not None:
                return self.audio_coach.get_session_recap(self.session_total)
            return {
                "event_type": "recap",
                "text": "Practice session ended.",
                "caption": "Practice session ended",
                "focus": "setup",
                "speak": True,
                "total_shots": self.session_total,
            }

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        client_timestamp_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Process a single BGR frame from the live web camera.
        Returns live HUD data including pose landmarks, joint angles, ball/rim boxes,
        trajectory trail, shot phase, advisory make/miss stats, and audio coach cues.
        """
        with self.lock:
            self.frame_index += 1
            if client_timestamp_ms is None or client_timestamp_ms <= self.last_timestamp_ms:
                self.last_timestamp_ms += 33
            else:
                self.last_timestamp_ms = int(client_timestamp_ms)
            timestamp_ms = self.last_timestamp_ms

            h, w = frame_bgr.shape[:2]

            # 1. Pose Inference
            pose_output = None
            landmarks_list: List[List[float]] = []
            angles: Dict[str, float] = {}
            if self.pose_engine is not None:
                try:
                    pose_output = self.pose_engine.process(frame_bgr, timestamp_ms)
                    if pose_output and "landmarks" in pose_output:
                        raw_lm = pose_output["landmarks"]
                        for idx in range(33):
                            if idx in raw_lm:
                                pt = raw_lm[idx]
                                landmarks_list.append([
                                    round(pt["norm_x"], 4),
                                    round(pt["norm_y"], 4),
                                    round(pt.get("visibility", 0.8), 2),
                                ])
                            else:
                                landmarks_list.append([0.0, 0.0, 0.0])
                        angles = compute_all_angles(
                            landmarks=pose_output.get("smoothed_landmarks") or pose_output.get("landmarks") or {},
                            valid=pose_output.get("valid"),
                            world_landmarks=pose_output.get("world_landmarks"),
                            min_visibility=0.45,
                        ) or {}
                except Exception as exc:
                    logger.debug("Live pose error: %s", exc)

            # 2. Shot Phase Detection
            if self.phase_detector is not None and pose_output and pose_output.get("landmarks"):
                try:
                    phase_str, _, _ = self.phase_detector.update(
                        landmarks=pose_output.get("smoothed_landmarks") or pose_output.get("landmarks") or {},
                        angles=angles,
                        timestamp_ms=timestamp_ms,
                    )
                    self.current_phase = phase_str
                except Exception as exc:
                    logger.debug("Live phase detection error: %s", exc)
            else:
                self.current_phase = "idle"

            # 3. Ball & Rim Tracking
            ball_box = None
            rim_box = None
            ball_conf = 0.0
            rim_conf = 0.0
            rim_status = "UNAVAILABLE_NO_WEIGHTS"
            flight_trail: List[Tuple[float, float]] = []
            ball_status = "idle"
            release_angle = None
            entry_angle = None
            arc_peak = None

            if self.ball_tracker is not None:
                try:
                    detections = self.ball_tracker.detect(frame_bgr)
                    ball_box = detections.get("ball")
                    rim_box = detections.get("rim")
                    ball_conf = detections.get("ball_conf", 0.0)
                    rim_conf = detections.get("rim_conf", 0.0)
                    rim_status = detections.get("rim_status", "UNAVAILABLE_NO_WEIGHTS")

                    # Handle shot lifecycle transitions
                    if self.current_phase in ("gathering", "dip", "set_point", "preparing") and self.active_shot_uid is None:
                        self.active_shot_uid = f"live_{timestamp_ms}"
                        self.ball_tracker.on_shot_started(self.active_shot_uid, self.frame_index, timestamp_ms)

                    if self.current_phase == "releasing" and self.previous_phase != "releasing" and self.active_shot_uid:
                        self.ball_tracker.on_shot_release(self.active_shot_uid, self.frame_index, timestamp_ms)

                    update_info = self.ball_tracker.update(
                        detections,
                        pose_output.get("smoothed_landmarks") if pose_output else None,
                        pose_output.get("valid") if pose_output else None,
                        timestamp_ms=timestamp_ms,
                    )
                    ball_status = update_info.get("status", "idle")
                    flight_trail = update_info.get("flight_centers", [])

                    if self.previous_phase in ("releasing", "follow_through") and self.current_phase == "idle" and self.active_shot_uid:
                        summary = self.ball_tracker.on_shot_ended(self.active_shot_uid, self.frame_index, timestamp_ms)
                        if summary:
                            outcome = summary.get("outcome")
                            conf = summary.get("outcome_conf", 0.0)
                            if outcome in ("make", "miss") and conf >= 0.70:
                                self.last_shot_outcome = outcome
                                self.last_shot_conf = conf
                                self.session_total += 1
                                if outcome == "make":
                                    self.session_makes += 1
                                else:
                                    self.session_misses += 1
                            entry_angle = summary.get("entry_angle")
                            arc_peak = summary.get("arc_peak")
                        self.active_shot_uid = None

                except Exception as exc:
                    logger.debug("Live ball tracking error: %s", exc)

            # 4. Audio Coaching Evaluation (runs synchronously, 0ms overhead, no external LLM)
            coach_event = None
            if self.audio_coach is not None:
                try:
                    coach_event = self.audio_coach.on_frame(
                        current_phase=self.current_phase,
                        previous_phase=self.previous_phase,
                        angles=angles,
                        landmarks=pose_output.get("smoothed_landmarks") or pose_output.get("landmarks") or {} if pose_output else {},
                        valid=pose_output.get("valid") if pose_output else None,
                        timestamp_ms=timestamp_ms,
                    )
                except Exception as exc:
                    logger.debug("Live audio coach error: %s", exc)

            self.previous_phase = self.current_phase

            accuracy = (
                round((self.session_makes / self.session_total) * 100.0, 1)
                if self.session_total > 0
                else 0.0
            )

            knee_ang = angles.get("knee_shooting") or angles.get("knee_shooting_3d")
            elbow_ang = angles.get("elbow_shooting") or angles.get("elbow_shooting_3d")

            return {
                "status": "ok",
                "frame_size": [w, h],
                "pose": {
                    "detected": len(landmarks_list) > 0,
                    "landmarks": landmarks_list,
                    "phase": str(self.current_phase),
                    "knee_angle": round(float(knee_ang), 1) if knee_ang is not None else None,
                    "elbow_angle": round(float(elbow_ang), 1) if elbow_ang is not None else None,
                },
                "ball": {
                    "detected": ball_box is not None,
                    "box": ball_box,
                    "conf": round(float(ball_conf), 2),
                    "flight_trail": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in flight_trail],
                },
                "rim": {
                    "detected": rim_box is not None,
                    "box": rim_box,
                    "conf": round(float(rim_conf), 2),
                    "status": rim_status,
                },
                "shot": {
                    "phase": self.current_phase,
                    "status": ball_status,
                    "release_angle": release_angle,
                    "entry_angle": entry_angle,
                    "arc_peak": arc_peak,
                    "outcome": self.last_shot_outcome,
                    "outcome_conf": round(float(self.last_shot_conf), 2),
                    "makes": self.session_makes,
                    "misses": self.session_misses,
                    "total": self.session_total,
                    "accuracy": accuracy,
                },
                "audio_coach": {
                    "event": coach_event,
                    "caption": self.audio_coach.current_caption if self.audio_coach else "",
                    "focus": self.audio_coach.current_focus if self.audio_coach else "setup",
                },
            }
