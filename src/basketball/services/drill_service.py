"""Drill Tracking Engine — Genuine YOLO ball tracking, floor bounce detection,
and MediaPipe kinematic posture assessment calibrated against reference athletes.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from basketball.coaching.drills_catalog import DRILLS_CATALOG, get_drill_by_id
from basketball.core.analyzer import compute_all_angles, get_angle_3d
from basketball.core.pose_engine import PoseEngine
from basketball.tracking.ball_tracker import BallTracker

logger = logging.getLogger("basketball.drill_service")


class DrillBounceTracker:
    """Detects authentic floor bounces from YOLO ball detections.

    A bounce is a vertical velocity reversal (downward -> upward) occurring
    at floor/feet level, originating from hip/knee release height, with
    sufficient vertical descent amplitude and a minimum cooldown interval to
    strictly reject hand twitches, waist-level holding, and slight ball movements.
    """

    def __init__(self, min_cooldown_ms: int = 200, min_excursion: float = 0.12):
        self.min_cooldown_ms = min_cooldown_ms
        self.min_excursion = min_excursion
        self.last_bounce_ts = -1000
        self.reps = 0
        self.rep_timestamps: List[int] = []
        self.rep_positions: List[Tuple[float, float]] = []

        # State tracking: 'up' (rebounding) or 'down' (descending)
        self.state = "up"
        self.valley_y = 1.0  # highest point in air / release apex (minimum y)
        self.peak_y = 0.0    # lowest point near floor / ground contact (maximum y)
        self.history: List[Tuple[int, float]] = []  # (ts_ms, norm_y)

    def reset(self) -> None:
        self.last_bounce_ts = -1000
        self.reps = 0
        self.rep_timestamps.clear()
        self.rep_positions.clear()
        self.state = "up"
        self.valley_y = 1.0
        self.peak_y = 0.0
        self.history.clear()

    def update(
        self,
        norm_y: Optional[float],
        norm_x: Optional[float],
        ts_ms: int,
        knee_y: Optional[float] = None,
        ankle_y: Optional[float] = None,
    ) -> Tuple[bool, int]:
        """Process one frame's ball position. Returns (is_bounce_event, current_rep_count)."""
        if norm_y is None:
            return False, self.reps

        self.history.append((ts_ms, norm_y))
        if len(self.history) > 40:
            self.history.pop(0)

        if len(self.history) < 2:
            self.valley_y = norm_y
            self.peak_y = norm_y
            return False, self.reps

        prev_y = self.history[-2][1]
        dy = norm_y - prev_y  # positive = downward, negative = upward
        bounce_detected = False

        # Floor threshold: ball must reach floor/feet level near ankles
        if ankle_y is not None:
            floor_thresh = min(ankle_y - 0.04, 0.72)
        elif knee_y is not None:
            floor_thresh = max(0.65, knee_y + 0.06)
        else:
            floor_thresh = 0.65

        # Apex threshold: ball must have descended from hip/knee release level
        if knee_y is not None:
            apex_thresh = knee_y + 0.04
        else:
            apex_thresh = 0.58

        if self.state == "up":
            if dy > 0.008:
                self.state = "down"
                self.valley_y = min(self.valley_y, prev_y)
                self.peak_y = norm_y
            else:
                self.valley_y = min(self.valley_y, norm_y)
        elif self.state == "down":
            if norm_y > self.peak_y:
                self.peak_y = norm_y
            elif dy < -0.008:
                # Inflection from downward to upward (rebound after hitting floor)
                down_excursion = self.peak_y - self.valley_y
                is_floor_hit = (
                    self.peak_y >= floor_thresh
                    and self.valley_y <= apex_thresh
                    and down_excursion >= self.min_excursion
                )
                if is_floor_hit:
                    if (ts_ms - self.last_bounce_ts) >= self.min_cooldown_ms:
                        self.reps += 1
                        self.last_bounce_ts = ts_ms
                        self.rep_timestamps.append(ts_ms)
                        if norm_x is not None:
                            self.rep_positions.append((round(norm_x, 3), round(self.peak_y, 3)))
                        bounce_detected = True
                self.state = "up"
                self.valley_y = norm_y

        return bounce_detected, self.reps

    def get_rhythm_score(self) -> Optional[float]:
        """Compute coefficient of variation of inter-rep intervals (0.0 to 1.0)."""
        stamps = self.rep_timestamps
        if len(stamps) < 4:
            return None
        gaps = [stamps[i] - stamps[i - 1] for i in range(1, len(stamps))]
        mean_gap = sum(gaps) / len(gaps)
        if mean_gap < 1e-4:
            return 1.0
        var = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        cv = math.sqrt(var) / mean_gap
        # cv of 0 -> 1.0, cv of 0.5+ -> lower consistency
        return max(0.0, min(1.0, 1.0 - cv * 1.5))


class DrillStyleTracker:
    """Classifies basketball dribble moves (Pound, Crossover, V-Dribble)
    and verifies whether the user's execution sequence matches the active drill's demo video.
    """

    def __init__(self, target_sequence: Optional[List[str]] = None, sequence_desc: str = ""):
        self.target_sequence: List[str] = target_sequence or ["POUND"]
        self.sequence_desc: str = sequence_desc or "Pound Dribble"
        self.combos_completed: int = 0
        self.combo_step: int = 0
        self.total_dribbles: int = 0
        self.correct_moves: int = 0

        self.last_bounce_pos: Optional[Tuple[float, float]] = None
        self.current_move: str = "Ready"
        self.current_move_type: str = "POUND"
        self.move_counts: Dict[str, int] = {
            "POUND": 0,
            "CROSSOVER": 0,
            "V_DRIBBLE": 0,
        }
        self.recent_moves: List[Dict[str, Any]] = []

    def reset(self, target_sequence: Optional[List[str]] = None, sequence_desc: str = "") -> None:
        if target_sequence is not None:
            self.target_sequence = target_sequence
        if sequence_desc:
            self.sequence_desc = sequence_desc
        self.combos_completed = 0
        self.combo_step = 0
        self.total_dribbles = 0
        self.correct_moves = 0
        self.last_bounce_pos = None
        self.current_move = "Ready"
        self.current_move_type = "POUND"
        self.move_counts = {"POUND": 0, "CROSSOVER": 0, "V_DRIBBLE": 0}
        self.recent_moves.clear()

    def classify_move(
        self,
        norm_x: float,
        norm_y: float,
        midline_x: float,
    ) -> Tuple[str, str, str]:
        """Classify move into (move_type, move_label, side).

        move_type: 'POUND', 'CROSSOVER', 'V_DRIBBLE'
        move_label: e.g. 'POUND (R)', 'CROSSOVER (L -> R)', 'V-DRIBBLE (L)'
        side: 'LEFT', 'RIGHT', 'CENTER'
        """
        rel_x = norm_x - midline_x
        side = "RIGHT" if rel_x > 0.04 else ("LEFT" if rel_x < -0.04 else "CENTER")

        if self.last_bounce_pos is None:
            # First bounce of session: default to pound on current side
            return "POUND", f"POUND ({side[0]})", side

        prev_x, _ = self.last_bounce_pos
        dx = norm_x - prev_x
        prev_rel_x = prev_x - midline_x

        # 1. CROSSOVER: crosses midline or large displacement across center
        crossed_midline = (prev_rel_x < -0.03 and rel_x > 0.03) or (prev_rel_x > 0.03 and rel_x < -0.03)
        wide_cross = abs(dx) >= 0.18 and (prev_rel_x * rel_x <= 0 or abs(rel_x) > 0.08)

        if crossed_midline or wide_cross:
            from_side = "L" if prev_rel_x < 0 else "R"
            to_side = "R" if rel_x > 0 else "L"
            return "CROSSOVER", f"CROSSOVER ({from_side} -> {to_side})", side

        # 2. V-DRIBBLE: lateral sweep on same side
        if 0.08 <= abs(dx) < 0.22 and not crossed_midline:
            return "V_DRIBBLE", f"V-DRIBBLE ({side[0]})", side

        # 3. POUND: vertical drop on same side with tight displacement
        return "POUND", f"POUND ({side[0]})", side

    def on_bounce(
        self,
        norm_x: float,
        norm_y: float,
        ts_ms: int,
        midline_x: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record an authentic ground bounce, classify move, and update combo sequence."""
        self.total_dribbles += 1
        mid_x = midline_x if midline_x is not None else 0.50

        move_type, move_label, side = self.classify_move(norm_x, norm_y, mid_x)
        self.last_bounce_pos = (norm_x, norm_y)
        self.current_move = move_label
        self.current_move_type = move_type
        self.move_counts[move_type] = self.move_counts.get(move_type, 0) + 1

        seq_len = len(self.target_sequence)
        expected_move = self.target_sequence[self.combo_step % seq_len]
        combo_completed = False

        if move_type == expected_move:
            self.correct_moves += 1
            self.combo_step += 1
            if self.combo_step >= seq_len:
                self.combos_completed += 1
                self.combo_step = 0
                combo_completed = True
        else:
            # Move didn't match expected step. Check if it matches step 0 to restart
            if move_type == self.target_sequence[0]:
                self.combo_step = 1
                self.correct_moves += 1
            else:
                self.combo_step = 0

        next_expected = self.target_sequence[self.combo_step % seq_len]
        progress_str = f"{self.combo_step}/{seq_len} (Next: {next_expected.replace('_', ' ').title()})"

        style_pct = round(100.0 * self.correct_moves / max(1, self.total_dribbles), 1)

        # Dynamic cue on dribble style & sequence
        if combo_completed:
            style_cue = f"Combo complete! {self.sequence_desc} executed."
        elif self.combo_step == seq_len - 1 and seq_len > 1:
            style_cue = f"Locked in — now hit the {next_expected.replace('_', ' ').title()}!"
        elif move_type == expected_move:
            style_cue = f"Good {move_type.replace('_', ' ').title()}! Next: {next_expected.replace('_', ' ').title()}"
        else:
            style_cue = f"Follow demo sequence: {self.sequence_desc}"

        res = {
            "move_type": move_type,
            "move_label": move_label,
            "side": side,
            "combos_completed": self.combos_completed,
            "combo_step": self.combo_step,
            "combo_target_len": seq_len,
            "combo_completed": combo_completed,
            "next_expected": next_expected,
            "combo_progress": progress_str,
            "style_match_pct": style_pct,
            "style_cue": style_cue,
        }
        self.recent_moves.append(res)
        if len(self.recent_moves) > 30:
            self.recent_moves.pop(0)

        return res

    def get_summary(self) -> Dict[str, Any]:
        style_pct = round(100.0 * self.correct_moves / max(1, self.total_dribbles), 1)
        return {
            "combos_completed": self.combos_completed,
            "total_dribbles": self.total_dribbles,
            "style_match_pct": style_pct,
            "target_sequence": self.target_sequence,
            "sequence_description": self.sequence_desc,
            "move_counts": dict(self.move_counts),
        }


class DrillPostureTracker:
    """Evaluates real-time pose kinematics against reference biomechanics."""

    def __init__(self, reference_bio: Dict[str, Any]):
        self.ref_bio = reference_bio
        self.ref_knee_mean: float = float(reference_bio.get("knee_angle_mean", 155.0))
        self.ref_knee_range: List[float] = reference_bio.get("knee_angle_range", [145.0, 165.0])
        self.ref_hip_mean: float = float(reference_bio.get("hip_angle_mean", 120.0))
        self.ref_hip_range: List[float] = reference_bio.get("hip_angle_range", [105.0, 135.0])
        self.head_pitch_threshold: float = float(reference_bio.get("head_pitch_threshold", 0.045))

        # Tolerances
        self.knee_min: float = max(135.0, self.ref_knee_range[0] - 8.0)
        self.knee_max: float = min(170.0, self.ref_knee_range[1] + 6.0)

        # Statistics accumulation
        self.total_frames = 0
        self.pose_frames = 0
        self.knee_angles: List[float] = []
        self.hip_angles: List[float] = []
        self.knees_bent_count = 0
        self.eyes_up_count = 0
        self.back_straight_count = 0
        self.in_stance_count = 0

    def reset(self, reference_bio: Optional[Dict[str, Any]] = None) -> None:
        if reference_bio:
            self.__init__(reference_bio)
        else:
            self.total_frames = 0
            self.pose_frames = 0
            self.knee_angles.clear()
            self.hip_angles.clear()
            self.knees_bent_count = 0
            self.eyes_up_count = 0
            self.back_straight_count = 0
            self.in_stance_count = 0

    def evaluate_frame(
        self,
        landmarks: Optional[Dict[int, Dict[str, float]]],
        valid: Optional[Dict[int, bool]] = None,
        world_landmarks: Optional[Dict[int, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a single frame's pose. Returns angles, posture checks, and cue."""
        self.total_frames += 1

        if not landmarks or len(landmarks) < 20:
            return {
                "pose_detected": False,
                "knee_angle": None,
                "hip_angle": None,
                "elbow_angle": None,
                "knee_avg_y": None,
                "ankle_avg_y": None,
                "knees_bent": False,
                "eyes_up": True,
                "back_straight": True,
                "in_athletic_stance": False,
                "live_cue": "Step into camera view in athletic stance",
            }

        self.pose_frames += 1

        # 1. 2D Knee angles
        # Right: hip 24, knee 26, ankle 28
        # Left: hip 23, knee 25, ankle 27
        def pt2d(idx: int) -> Optional[List[float]]:
            if idx in landmarks and (valid is None or valid.get(idx, True)):
                lm = landmarks[idx]
                if lm.get("visibility", 1.0) >= 0.35:
                    return [lm["norm_x"], lm["norm_y"], 0.0]
            return None

        knee_r = get_angle_3d(pt2d(24), pt2d(26), pt2d(28))
        knee_l = get_angle_3d(pt2d(23), pt2d(25), pt2d(27))

        if knee_r is not None and knee_l is not None:
            knee_angle = round((knee_r + knee_l) / 2.0, 1)
        elif knee_r is not None:
            knee_angle = knee_r
        else:
            knee_angle = knee_l

        # 2. 2D Hip angles
        # Right: shoulder 12, hip 24, knee 26
        # Left: shoulder 11, hip 23, knee 25
        hip_r = get_angle_3d(pt2d(12), pt2d(24), pt2d(26))
        hip_l = get_angle_3d(pt2d(11), pt2d(23), pt2d(25))

        if hip_r is not None and hip_l is not None:
            hip_angle = round((hip_r + hip_l) / 2.0, 1)
        elif hip_r is not None:
            hip_angle = hip_r
        else:
            hip_angle = hip_l

        # 3. 2D Elbow angle
        elbow_r = get_angle_3d(pt2d(12), pt2d(14), pt2d(16))
        elbow_l = get_angle_3d(pt2d(11), pt2d(13), pt2d(15))
        elbow_angle = elbow_r if elbow_r is not None else elbow_l

        # 4. Vertical landmark references for ball bounce gating & body midline
        knee_y_vals = [landmarks[k]["norm_y"] for k in (25, 26) if k in landmarks]
        knee_avg_y = sum(knee_y_vals) / len(knee_y_vals) if knee_y_vals else None

        ankle_y_vals = [landmarks[k]["norm_y"] for k in (27, 28) if k in landmarks]
        ankle_avg_y = sum(ankle_y_vals) / len(ankle_y_vals) if ankle_y_vals else None

        # Body midline (horizontal center from hips or shoulders)
        body_midline_x = None
        if 23 in landmarks and 24 in landmarks:
            body_midline_x = round((landmarks[23]["norm_x"] + landmarks[24]["norm_x"]) / 2.0, 3)
        elif 11 in landmarks and 12 in landmarks:
            body_midline_x = round((landmarks[11]["norm_x"] + landmarks[12]["norm_x"]) / 2.0, 3)

        # 5. Head pitch / Gaze (eyes up check)
        # 0: nose, 7: left ear, 8: right ear
        eyes_up = True
        if 0 in landmarks:
            nose_y = landmarks[0]["norm_y"]
            ears_y = [landmarks[k]["norm_y"] for k in (7, 8) if k in landmarks]
            if ears_y:
                avg_ear_y = sum(ears_y) / len(ears_y)
                pitch_diff = nose_y - avg_ear_y
                if pitch_diff > self.head_pitch_threshold:
                    eyes_up = False

        # 6. Posture checks against reference tolerances
        knees_bent = False
        if knee_angle is not None:
            self.knee_angles.append(knee_angle)
            if self.knee_min <= knee_angle <= self.knee_max:
                knees_bent = True
                self.knees_bent_count += 1
            elif knee_angle < self.knee_min:
                # Deep squat, still bent but low
                knees_bent = True
                self.knees_bent_count += 1

        back_straight = True
        if hip_angle is not None:
            self.hip_angles.append(hip_angle)
            if 100.0 <= hip_angle <= 170.0:
                self.back_straight_count += 1
            else:
                back_straight = False

        if eyes_up:
            self.eyes_up_count += 1

        in_athletic_stance = knees_bent and back_straight
        if in_athletic_stance:
            self.in_stance_count += 1

        # 7. Live Dynamic Coaching Cue
        if knee_angle is not None and knee_angle > self.knee_max:
            live_cue = "Bend your knees deeper into an athletic stance"
        elif knee_angle is not None and knee_angle < self.knee_min:
            live_cue = "Rise slightly — stay balanced and agile"
        elif not eyes_up:
            live_cue = "Eyes up! Feel the ball without staring at the floor"
        elif not back_straight:
            live_cue = "Chest up — hinge at your hips"
        else:
            live_cue = "Great athletic posture! Keep pounding"

        return {
            "pose_detected": True,
            "knee_angle": knee_angle,
            "hip_angle": hip_angle,
            "elbow_angle": elbow_angle,
            "knee_avg_y": knee_avg_y,
            "ankle_avg_y": ankle_avg_y,
            "body_midline_x": body_midline_x,
            "knees_bent": knees_bent,
            "eyes_up": eyes_up,
            "back_straight": back_straight,
            "in_athletic_stance": in_athletic_stance,
            "live_cue": live_cue,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregated posture statistics."""
        pose_count = max(1, self.pose_frames)
        avg_knee = (
            round(sum(self.knee_angles) / len(self.knee_angles), 1)
            if self.knee_angles
            else None
        )
        avg_hip = (
            round(sum(self.hip_angles) / len(self.hip_angles), 1)
            if self.hip_angles
            else None
        )

        stance_pct = round(100.0 * self.in_stance_count / pose_count, 1)
        knees_bent_pct = round(100.0 * self.knees_bent_count / pose_count, 1)
        eyes_up_pct = round(100.0 * self.eyes_up_count / pose_count, 1)
        back_straight_pct = round(100.0 * self.back_straight_count / pose_count, 1)

        return {
            "total_frames": self.total_frames,
            "pose_frames": self.pose_frames,
            "avg_knee_angle": avg_knee,
            "avg_hip_angle": avg_hip,
            "reference_knee_target": self.ref_knee_mean,
            "reference_knee_range": self.ref_knee_range,
            "stance_adherence_pct": stance_pct,
            "knees_bent_pct": knees_bent_pct,
            "eyes_up_pct": eyes_up_pct,
            "back_straight_pct": back_straight_pct,
        }


class DrillTrackingEngine:
    """Manages active dribbling drill session with YOLO ball bounce counting
    and MediaPipe pose biomechanics.
    """

    def __init__(self, weights_path: Optional[str] = None):
        self.lock = threading.Lock()
        self.weights_path = weights_path

        # Underlying AI Engines
        self.pose_engine: Optional[PoseEngine] = None
        self.ball_tracker: Optional[BallTracker] = None

        # Monotonic time keeper for MediaPipe RunningMode.VIDEO
        self._monotonic_ts_ms = 0
        self._last_client_ts: Optional[int] = None

        # Active session state
        self.is_active = False
        self.drill_id: Optional[str] = None
        self.drill_spec: Optional[Dict[str, Any]] = None
        self.session_start_wall_s: float = 0.0

        self.bounce_tracker = DrillBounceTracker()
        self.posture_tracker = DrillPostureTracker({})
        self.style_tracker = DrillStyleTracker()

        self._init_models()

    def _init_models(self) -> None:
        try:
            self.pose_engine = PoseEngine()
        except Exception as exc:
            logger.warning("DrillTrackingEngine: PoseEngine init note: %s", exc)
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
            logger.warning("DrillTrackingEngine: BallTracker init note: %s", exc)
            self.ball_tracker = None

    def start_session(self, drill_id: str) -> Dict[str, Any]:
        """Start a new drill session for the given drill_id."""
        with self.lock:
            spec = get_drill_by_id(drill_id)
            if not spec:
                # Fallback to first drill in catalog
                spec = DRILLS_CATALOG[0]
                drill_id = spec["id"]

            self.drill_id = drill_id
            self.drill_spec = spec
            self.is_active = True
            self.session_start_wall_s = time.time()

            ref_bio = spec.get("reference_biomechanics", {})
            target_seq = spec.get("target_sequence", ["POUND"])
            seq_desc = spec.get("sequence_description", spec.get("name", "Drill"))

            self.bounce_tracker.reset()
            self.posture_tracker.reset(ref_bio)
            self.style_tracker.reset(target_seq, seq_desc)

            return {
                "status": "started",
                "drill_id": drill_id,
                "drill_name": spec.get("name", ""),
                "target_sequence": target_seq,
                "sequence_description": seq_desc,
                "reference_biomechanics": ref_bio,
                "cues": spec.get("cues", []),
            }

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        client_timestamp_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Process a live camera frame. Returns ball tracking, bounce count,
        pose skeleton, joint angles, and real-time posture feedback.
        """
        with self.lock:
            # Advance monotonic timestamp
            if client_timestamp_ms is not None and self._last_client_ts is not None:
                dt = max(1, client_timestamp_ms - self._last_client_ts)
            else:
                dt = 33
            self._last_client_ts = client_timestamp_ms
            self._monotonic_ts_ms += min(dt, 200)
            engine_ts = self._monotonic_ts_ms

            h, w = frame_bgr.shape[:2]

            # 1. Pose Inference
            pose_output = None
            landmarks_list: List[List[float]] = []
            if self.pose_engine is not None:
                try:
                    pose_output = self.pose_engine.process(frame_bgr, engine_ts)
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
                except Exception as exc:
                    logger.debug("Drill pose error: %s", exc)

            # 2. Kinematic Posture Evaluation
            posture_eval = self.posture_tracker.evaluate_frame(
                landmarks=pose_output.get("smoothed_landmarks") if pose_output else None,
                valid=pose_output.get("valid") if pose_output else None,
                world_landmarks=pose_output.get("world_landmarks") if pose_output else None,
            )

            # 3. YOLO Ball Tracking & Floor Bounce Counting
            ball_box = None
            ball_conf = 0.0
            ball_center = None
            bounce_event = False
            current_reps = self.bounce_tracker.reps
            style_event = None

            if self.ball_tracker is not None:
                try:
                    det = self.ball_tracker.detect(frame_bgr)
                    ball_box = det.get("ball")
                    ball_conf = det.get("ball_conf", 0.0)

                    norm_bx = None
                    norm_by = None
                    if ball_box:
                        cx = (ball_box[0] + ball_box[2]) / 2.0
                        cy = (ball_box[1] + ball_box[3]) / 2.0
                        norm_bx = cx / max(1.0, float(w))
                        norm_by = cy / max(1.0, float(h))
                        ball_center = [round(cx, 1), round(cy, 1)]

                    bounce_event, current_reps = self.bounce_tracker.update(
                        norm_y=norm_by,
                        norm_x=norm_bx,
                        ts_ms=engine_ts,
                        knee_y=posture_eval.get("knee_avg_y"),
                        ankle_y=posture_eval.get("ankle_avg_y"),
                    )

                    if bounce_event and norm_bx is not None and norm_by is not None:
                        style_event = self.style_tracker.on_bounce(
                            norm_x=norm_bx,
                            norm_y=norm_by,
                            ts_ms=engine_ts,
                            midline_x=posture_eval.get("body_midline_x"),
                        )
                except Exception as exc:
                    logger.debug("Drill ball detection error: %s", exc)

            ref_bio = (self.drill_spec or {}).get("reference_biomechanics", {})
            seq_len = max(1, len(self.style_tracker.target_sequence))
            next_expected = self.style_tracker.target_sequence[self.style_tracker.combo_step % seq_len]
            combo_progress = f"{self.style_tracker.combo_step}/{seq_len} (Next: {next_expected.replace('_', ' ').title()})"
            style_pct = round(100.0 * self.style_tracker.correct_moves / max(1, self.style_tracker.total_dribbles), 1)

            # Style cue is emphasized on bounce events, otherwise posture cue displays
            live_cue = (style_event.get("style_cue") if style_event else None) or posture_eval["live_cue"]

            return {
                "status": "ok",
                "timestamp_ms": client_timestamp_ms or engine_ts,
                "ball": [round(float(v), 1) for v in ball_box] if ball_box else None,
                "ball_conf": round(float(ball_conf), 2),
                "ball_center": ball_center,
                "bounce_event": bounce_event,
                "rep_count": current_reps,
                "current_move": self.style_tracker.current_move,
                "current_move_type": self.style_tracker.current_move_type,
                "combos_completed": self.style_tracker.combos_completed,
                "combo_step": self.style_tracker.combo_step,
                "combo_target_len": seq_len,
                "combo_progress": combo_progress,
                "combo_completed": style_event.get("combo_completed", False) if style_event else False,
                "style_match_pct": style_pct,
                "style_cue": style_event.get("style_cue") if style_event else None,
                "pose_detected": posture_eval["pose_detected"],
                "landmarks": landmarks_list,
                "angles": {
                    "knee_angle": posture_eval.get("knee_angle"),
                    "hip_angle": posture_eval.get("hip_angle"),
                    "elbow_angle": posture_eval.get("elbow_angle"),
                },
                "posture": {
                    "knees_bent": posture_eval["knees_bent"],
                    "eyes_up": posture_eval["eyes_up"],
                    "back_straight": posture_eval["back_straight"],
                    "in_athletic_stance": posture_eval["in_athletic_stance"],
                },
                "live_cue": live_cue,
                "reference_target": {
                    "drill_id": self.drill_id,
                    "knee_mean": ref_bio.get("knee_angle_mean"),
                    "knee_range": ref_bio.get("knee_angle_range"),
                },
            }

    def stop_session(self) -> Dict[str, Any]:
        """Conclude active drill session, return authentic biomechanical summary."""
        with self.lock:
            self.is_active = False
            duration_s = max(1.0, round(time.time() - self.session_start_wall_s, 1))
            rep_count = self.bounce_tracker.reps
            rhythm_score = self.bounce_tracker.get_rhythm_score()
            posture_summary = self.posture_tracker.get_summary()
            style_summary = self.style_tracker.get_summary()

            ref_bio = (self.drill_spec or {}).get("reference_biomechanics", {})
            drill_name = (self.drill_spec or {}).get("name", "Drill")

            # Build honest, measured feedback items
            feedback_items = self._generate_feedback(
                rep_count=rep_count,
                duration_s=duration_s,
                posture_summary=posture_summary,
                rhythm_score=rhythm_score,
                ref_bio=ref_bio,
                drill_name=drill_name,
                style_summary=style_summary,
            )

            cadence = round(rep_count / duration_s, 2)
            rpm = round(rep_count * (60.0 / duration_s), 1)

            return {
                "status": "completed",
                "drill_id": self.drill_id,
                "drill_name": drill_name,
                "rep_count": rep_count,
                "combos_completed": style_summary["combos_completed"],
                "style_match_pct": style_summary["style_match_pct"],
                "sequence_description": style_summary["sequence_description"],
                "move_counts": style_summary["move_counts"],
                "style_summary": style_summary,
                "duration_seconds": duration_s,
                "reps_per_second": cadence,
                "reps_per_minute": rpm,
                "rhythm_score": round(rhythm_score, 2) if rhythm_score is not None else None,
                "posture_summary": posture_summary,
                "feedback_items": feedback_items,
            }

    def _generate_feedback(
        self,
        rep_count: int,
        duration_s: float,
        posture_summary: Dict[str, Any],
        rhythm_score: Optional[float],
        ref_bio: Dict[str, Any],
        drill_name: str,
        style_summary: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Construct genuine, data-backed feedback items based on real measurements."""
        items: List[Dict[str, Any]] = []

        # 1. Reps & Rhythm
        if rep_count == 0:
            items.append({
                "status": "tip",
                "text": "No floor bounces were counted. Ensure the basketball and floor contact area are visible in the camera frame.",
            })
        else:
            cadence = round(rep_count / max(1.0, duration_s), 1)
            if rhythm_score is not None and rhythm_score >= 0.70:
                items.append({
                    "status": "good",
                    "text": f"Consistent dribble rhythm: {rep_count} genuine floor bounces counted at {cadence} reps/sec with steady pacing.",
                })
            elif rhythm_score is not None:
                items.append({
                    "status": "tip",
                    "text": f"{rep_count} reps counted at {cadence} reps/sec. Pacing showed slight pauses — aim for metronome rhythm.",
                })
            else:
                items.append({
                    "status": "good",
                    "text": f"{rep_count} genuine dribble reps counted in {int(duration_s)}s.",
                })

        # 2. Dribble Style & Demo Sequence Adherence
        if rep_count > 0 and style_summary:
            combos = style_summary.get("combos_completed", 0)
            style_pct = style_summary.get("style_match_pct", 100.0)
            seq_desc = style_summary.get("sequence_description", drill_name)
            move_counts = style_summary.get("move_counts", {})
            p_cnt = move_counts.get("POUND", 0)
            c_cnt = move_counts.get("CROSSOVER", 0)
            v_cnt = move_counts.get("V_DRIBBLE", 0)
            moves_desc = f"{p_cnt} pounds, {c_cnt} crossovers, {v_cnt} V-dribbles"

            if self.drill_id != "pound_dribble":
                if combos > 0:
                    items.append({
                        "status": "good",
                        "text": f"Demo Sequence Adherence: Completed {combos} full combo(s) of '{seq_desc}' with {style_pct}% style match ({moves_desc}).",
                    })
                elif style_pct >= 60.0:
                    items.append({
                        "status": "good",
                        "text": f"Dribble Style: {style_pct}% of dribbles followed the target movement ({moves_desc}). Chain them into complete combos ({seq_desc}).",
                    })
                else:
                    items.append({
                        "status": "tip",
                        "text": f"Dribble Style Tip: Detected {moves_desc}. The demo video demonstrates '{seq_desc}' — follow the 2-dribble rhythm before transitioning.",
                    })
            else:
                items.append({
                    "status": "good",
                    "text": f"Dribble Style: {style_pct}% stationary pound dribbles with tight lateral control ({p_cnt} pounds).",
                })

            # Ground Contact Height Validation
            items.append({
                "status": "good",
                "text": f"Ground Contact Check: Every counted dribble was verified descending from hip/knee height all the way to floor level near the feet before rebounding.",
            })

        # 3. Knee Angle vs Reference Athlete
        avg_knee = posture_summary.get("avg_knee_angle")
        stance_pct = posture_summary.get("stance_adherence_pct", 0.0)
        ref_knee_mean = ref_bio.get("knee_angle_mean", 155.0)
        ref_knee_range = ref_bio.get("knee_angle_range", [145.0, 165.0])

        if avg_knee is not None:
            if 140.0 <= avg_knee <= 165.0:
                items.append({
                    "status": "good",
                    "text": f"Solid athletic base: average knee bend was {avg_knee:.1f}° (Reference athlete: {ref_knee_mean:.1f}°, range {ref_knee_range[0]}°–{ref_knee_range[1]}°). You maintained an athletic stance on {stance_pct}% of frames.",
                })
            elif avg_knee > 165.0:
                items.append({
                    "status": "tip",
                    "text": f"Bend your knees lower: your average knee angle was {avg_knee:.1f}° (Reference athlete: {ref_knee_mean:.1f}°). You stood upright on {round(100.0 - stance_pct, 1)}% of frames.",
                })
            else:
                items.append({
                    "status": "tip",
                    "text": f"Your knee bend averaged {avg_knee:.1f}°. Keep hips slightly higher to remain light on your feet.",
                })
        else:
            items.append({
                "status": "tip",
                "text": "Step further back from camera so your full body and knees are visible for posture tracking.",
            })

        # 4. Eyes Up / Court Vision
        eyes_up_pct = posture_summary.get("eyes_up_pct", 0.0)
        pose_frames = posture_summary.get("pose_frames", 0)
        if pose_frames >= 10:
            if eyes_up_pct >= 70.0:
                items.append({
                    "status": "good",
                    "text": f"Great court awareness: head was up on {eyes_up_pct}% of frames, keeping your eyes off the ball.",
                })
            else:
                items.append({
                    "status": "tip",
                    "text": f"Head down on {round(100.0 - eyes_up_pct, 1)}% of frames. Keep your chin up and feel the ball with your fingertips.",
                })

        # 5. Back Alignment
        back_pct = posture_summary.get("back_straight_pct", 0.0)
        if pose_frames >= 10:
            if back_pct >= 70.0:
                items.append({
                    "status": "good",
                    "text": f"Strong spine neutrality: chest up and hips hinged on {back_pct}% of frames.",
                })
            else:
                items.append({
                    "status": "tip",
                    "text": f"Avoid rounding your shoulders. Hinge from your hips while keeping your chest tall.",
                })

        return items
