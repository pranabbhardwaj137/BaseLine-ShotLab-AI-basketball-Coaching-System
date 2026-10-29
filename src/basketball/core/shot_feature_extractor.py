"""
shot_feature_extractor.py - Biomechanical Kinematic Feature Extraction Pipeline.

Extracts scale-normalized, torso-relative kinematic features from BlazePose landmarks
across single frames and temporal sliding windows for basketball shot-event detection.
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from basketball.core.analyzer import compute_all_angles, interpolate_kinematic_series, shooting_side


class ShotFeatureExtractor:
    """
    Extracts torso-scale-normalized biomechanical features from landmark streams.
    Features:
      - Torso-normalized wrist velocity (v_y) and acceleration (a_y)
      - Relative wrist-to-shoulder and wrist-to-nose vertical elevation
      - Kinetic chain joint angles and angular velocities (knee, hip, shoulder, elbow, wrist)
      - Dip-to-rise kinetic sequencing features
      - Temporal sliding window feature aggregation
    """

    def __init__(self, window_size: int = 15, default_fps: float = 30.0):
        self.window_size = window_size
        self.default_fps = default_fps

    @staticmethod
    def compute_torso_scale(landmarks: Dict[int, Any], side: str = "right") -> float:
        """
        Compute torso reference length in normalized 2D image coordinates:
        Distance from shoulder (11/12) to hip (23/24).
        """
        if not landmarks:
            return 0.35  # sensible default normalized torso height

        sh_idx = 11 if side == "left" else 12
        hip_idx = 23 if side == "left" else 24

        sh = landmarks.get(sh_idx)
        hip = landmarks.get(hip_idx)

        if not sh or not hip:
            return 0.35

        dx = sh["norm_x"] - hip["norm_x"]
        dy = sh["norm_y"] - hip["norm_y"]
        dist = math.hypot(dx, dy)
        return max(0.10, dist)  # clamp to avoid division by near-zero

    def extract_frame_kinematics(
        self,
        frame_history: List[Dict[str, Any]],
        fps: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Extract instantaneous kinematics for the latest frame in frame_history.
        Requires at least 1 frame; computes velocities using previous frames.
        """
        if not frame_history:
            return self._empty_frame_features()

        fps_val = fps or self.default_fps
        dt = 1.0 / max(1.0, fps_val)

        curr = frame_history[-1]
        landmarks = curr.get("landmarks") or {}
        angles = curr.get("angles") or {}
        side = angles.get("shooting_side") or shooting_side(landmarks)

        wrist_idx = 15 if side == "left" else 16
        sh_idx = 11 if side == "left" else 12
        hip_idx = 23 if side == "left" else 24
        nose_idx = 0

        torso_scale = self.compute_torso_scale(landmarks, side=side)

        wrist_lm = landmarks.get(wrist_idx)
        sh_lm = landmarks.get(sh_idx)
        nose_lm = landmarks.get(nose_idx)
        hip_lm = landmarks.get(hip_idx)

        wrist_y = wrist_lm["norm_y"] if wrist_lm else None
        sh_y = sh_lm["norm_y"] if sh_lm else None
        nose_y = nose_lm["norm_y"] if nose_lm else None
        hip_y = hip_lm["norm_y"] if hip_lm else None

        # Relative elevations normalized by torso scale
        # Note: image y increases downwards, so lower y means higher elevation.
        # Negative delta means wrist is ABOVE shoulder / nose.
        rel_shoulder = ((wrist_y - sh_y) / torso_scale) if (wrist_y is not None and sh_y is not None) else 0.0
        rel_nose = ((wrist_y - nose_y) / torso_scale) if (wrist_y is not None and nose_y is not None) else 0.0

        # Extract velocities from previous frames
        wrist_v_y = 0.0
        wrist_a_y = 0.0
        hip_v_y = 0.0

        if len(frame_history) >= 2:
            prev = frame_history[-2]
            prev_lm = prev.get("landmarks") or {}
            prev_w = prev_lm.get(wrist_idx)
            prev_hip = prev_lm.get(hip_idx)

            if wrist_y is not None and prev_w and prev_w.get("norm_y") is not None:
                # Vertical velocity (normalized by torso scale): negative = moving upward
                wrist_v_y = ((wrist_y - prev_w["norm_y"]) / dt) / torso_scale

            if hip_y is not None and prev_hip and prev_hip.get("norm_y") is not None:
                hip_v_y = ((hip_y - prev_hip["norm_y"]) / dt) / torso_scale

        if len(frame_history) >= 3:
            prev_prev = frame_history[-3]
            pp_lm = prev_prev.get("landmarks") or {}
            prev_lm = frame_history[-2].get("landmarks") or {}
            p_w = prev_lm.get(wrist_idx)
            pp_w = pp_lm.get(wrist_idx)

            if p_w and pp_w and p_w.get("norm_y") is not None and pp_w.get("norm_y") is not None:
                prev_v = ((p_w["norm_y"] - pp_w["norm_y"]) / dt) / torso_scale
                wrist_a_y = (wrist_v_y - prev_v) / dt

        # Angular kinematics
        elbow_angle = angles.get("elbow_shooting") or 90.0
        knee_angle = angles.get("knee_shooting") or 140.0
        sh_angle = angles.get("shoulder_shooting") or 45.0
        hip_angle = angles.get("hip_shooting") or 160.0
        wrist_angle = angles.get("wrist_flexion_angle") or 180.0

        elbow_v_ang = 0.0
        knee_v_ang = 0.0

        if len(frame_history) >= 2:
            prev_ang = frame_history[-2].get("angles") or {}
            p_elb = prev_ang.get("elbow_shooting")
            p_knee = prev_ang.get("knee_shooting")

            if p_elb is not None and angles.get("elbow_shooting") is not None:
                elbow_v_ang = (elbow_angle - p_elb) / dt  # deg/s

            if p_knee is not None and angles.get("knee_shooting") is not None:
                knee_v_ang = (knee_angle - p_knee) / dt  # deg/s

        is_valid = (wrist_y is not None and sh_y is not None)

        return {
            "torso_scale": float(torso_scale),
            "wrist_v_y": float(wrist_v_y),
            "wrist_a_y": float(wrist_a_y),
            "rel_shoulder": float(rel_shoulder),
            "rel_nose": float(rel_nose),
            "hip_v_y": float(hip_v_y),
            "elbow_angle": float(elbow_angle),
            "knee_angle": float(knee_angle),
            "shoulder_angle": float(sh_angle),
            "hip_angle": float(hip_angle),
            "wrist_angle": float(wrist_angle),
            "elbow_v_ang": float(elbow_v_ang),
            "knee_v_ang": float(knee_v_ang),
            "is_valid": bool(is_valid),
            "shooting_side": side
        }

    def _empty_frame_features(self) -> Dict[str, Any]:
        return {
            "torso_scale": 0.35,
            "wrist_v_y": 0.0,
            "wrist_a_y": 0.0,
            "rel_shoulder": 0.0,
            "rel_nose": 0.0,
            "hip_v_y": 0.0,
            "elbow_angle": 90.0,
            "knee_angle": 140.0,
            "shoulder_angle": 45.0,
            "hip_angle": 160.0,
            "wrist_angle": 180.0,
            "elbow_v_ang": 0.0,
            "knee_v_ang": 0.0,
            "is_valid": False,
            "shooting_side": "right"
        }

    def extract_window_vector(self, window_kinematics: List[Dict[str, Any]]) -> np.ndarray:
        """
        Aggregate a temporal sequence of frame kinematic dicts into a fixed-length 1D feature vector.
        Summary includes current frame values + window statistics (min, max, mean).
        Returns a 1D float32 numpy array.
        """
        if not window_kinematics:
            return np.zeros(24, dtype=np.float32)

        curr = window_kinematics[-1]

        # Extract time series for window
        wv_y = [k["wrist_v_y"] for k in window_kinematics]
        wa_y = [k["wrist_a_y"] for k in window_kinematics]
        rel_sh = [k["rel_shoulder"] for k in window_kinematics]
        rel_n = [k["rel_nose"] for k in window_kinematics]
        elb_v = [k["elbow_v_ang"] for k in window_kinematics]
        knee_v = [k["knee_v_ang"] for k in window_kinematics]
        knee_deg = [k["knee_angle"] for k in window_kinematics]
        elb_deg = [k["elbow_angle"] for k in window_kinematics]

        vec = [
            # Current instantaneous features (8)
            curr["wrist_v_y"],
            curr["wrist_a_y"],
            curr["rel_shoulder"],
            curr["rel_nose"],
            curr["elbow_angle"] / 180.0,
            curr["knee_angle"] / 180.0,
            curr["elbow_v_ang"] / 500.0,
            curr["knee_v_ang"] / 500.0,

            # Window temporal dynamics (12)
            float(np.min(wv_y)),                 # peak upward velocity (most negative)
            float(np.max(wv_y)),                 # peak downward velocity
            float(np.mean(wv_y)),
            float(np.min(rel_sh)),               # peak elevation relative to shoulder (most negative)
            float(np.min(rel_n)),                # peak elevation relative to nose
            float(np.max(wa_y)),                 # peak vertical acceleration
            float(np.max(elb_v)) / 500.0,        # peak elbow extension rate
            float(np.mean(elb_v)) / 500.0,
            float(np.min(knee_deg)) / 180.0,     # lowest dip angle
            float(np.max(knee_v)) / 500.0,       # peak knee uncoiling drive
            float(np.max(elb_deg)) / 180.0,      # max elbow extension
            float(np.std(wv_y)),                 # velocity volatility

            # Derived kinematic sequence indicators (4)
            1.0 if curr["rel_shoulder"] < -0.10 else 0.0,  # wrist above shoulder gate
            1.0 if curr["wrist_v_y"] < -0.50 else 0.0,     # upward burst gate
            1.0 if curr["knee_v_ang"] > 50.0 else 0.0,     # knee uncoiling onset
            1.0 if curr["is_valid"] else 0.0
        ]

        return np.array(vec, dtype=np.float32)

    @staticmethod
    def align_intervals_to_labels(
        total_frames: int,
        labeled_intervals: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Produce frame-level ground-truth labels for a clip:
        - binary_labels: 1 if inside a shot_event window (focusing around release), 0 otherwise.
        - class_labels: integer action class for multi-class negative suppression.
        """
        binary = np.zeros(total_frames, dtype=np.int32)
        classes = np.zeros(total_frames, dtype=np.int32)

        class_to_id = {
            "idle_reset": 0,
            "shot_event": 1,
            "dribble_drive": 2,
            "gather_no_shot": 3,
            "pass": 4,
            "pump_fake": 5,
            "rebound": 6,
            "defensive_contest": 7,
            "catch_and_hold": 8
        }

        for intv in labeled_intervals:
            start = max(0, intv.get("start_frame", 0))
            end = min(total_frames - 1, intv.get("end_frame", total_frames - 1))
            act = intv.get("action_class", "idle_reset")
            c_id = class_to_id.get(act, 0)

            if act == "shot_event":
                # For shot events, focus positive activation from dip to release + 5 frames
                dip = intv.get("dip_frame") or start
                rel = intv.get("release_frame") or end
                pos_start = max(0, dip)
                pos_end = min(total_frames - 1, rel + 5)
                binary[pos_start:pos_end + 1] = 1
                classes[start:end + 1] = c_id
            else:
                classes[start:end + 1] = c_id

        return binary, classes

    @staticmethod
    def compute_torso_lean_deg(landmarks: Dict[int, Any], side: str = "right") -> Optional[float]:
        """Compute torso sagittal lean angle relative to vertical in degrees."""
        if not landmarks:
            return None
        sh_idx = 11 if side == "left" else 12
        hip_idx = 23 if side == "left" else 24
        sh = landmarks.get(sh_idx)
        hip = landmarks.get(hip_idx)
        if not sh or not hip:
            return None
        dx = sh["norm_x"] - hip["norm_x"]
        dy = sh["norm_y"] - hip["norm_y"]
        # In image coords, shoulder is above hip, so dy is negative when standing upright
        angle_rad = math.atan2(abs(dx), abs(dy))
        return round(math.degrees(angle_rad), 1)

    @staticmethod
    def compute_hip_shoulder_separation_deg(landmarks: Dict[int, Any]) -> Optional[float]:
        """Compute rotational separation angle between shoulder and hip lines in image plane (degrees)."""
        if not landmarks:
            return None
        l_sh = landmarks.get(11)
        r_sh = landmarks.get(12)
        l_hip = landmarks.get(23)
        r_hip = landmarks.get(24)
        if not (l_sh and r_sh and l_hip and r_hip):
            return None
        sh_angle = math.degrees(math.atan2(r_sh["norm_y"] - l_sh["norm_y"], r_sh["norm_x"] - l_sh["norm_x"]))
        hip_angle = math.degrees(math.atan2(r_hip["norm_y"] - l_hip["norm_y"], r_hip["norm_x"] - l_hip["norm_x"]))
        diff = abs(sh_angle - hip_angle)
        if diff > 180.0:
            diff = 360.0 - diff
        return round(diff, 1)

    @classmethod
    def compute_stop_balance_sway(
        cls,
        frame_history: List[Dict[str, Any]],
        start_idx: int,
        stop_idx: int
    ) -> Optional[float]:
        """Compute normalized lateral hip sway range during deceleration or plant window."""
        if not frame_history or start_idx >= stop_idx:
            return None
        start = max(0, start_idx)
        end = min(len(frame_history), stop_idx + 1)
        window = frame_history[start:end]
        if len(window) < 2:
            return None
        xs: List[float] = []
        for f in window:
            lm = f.get("landmarks") or {}
            lh = lm.get(23)
            rh = lm.get(24)
            if lh and rh and lh.get("norm_x") is not None and rh.get("norm_x") is not None:
                xs.append((lh["norm_x"] + rh["norm_x"]) / 2.0)
        if len(xs) < 2:
            return None
        scale = cls.compute_torso_scale((window[0].get("landmarks") or {}))
        return round((max(xs) - min(xs)) / max(0.1, scale), 2)

    @classmethod
    def compute_backward_displacement(
        cls,
        frame_history: List[Dict[str, Any]],
        start_idx: int,
        plant_idx: int,
        side: str = "right"
    ) -> Optional[float]:
        """Compute horizontal backward displacement normalized by torso length (for step-back shots)."""
        if not frame_history or start_idx >= plant_idx:
            return None
        s_idx = max(0, start_idx)
        p_idx = min(len(frame_history) - 1, plant_idx)
        start_lm = frame_history[s_idx].get("landmarks") or {}
        plant_lm = frame_history[p_idx].get("landmarks") or {}
        hip_idx = 23 if side == "left" else 24
        s_hip = start_lm.get(hip_idx)
        p_hip = plant_lm.get(hip_idx)
        if not s_hip or not p_hip:
            return None
        dx = abs(p_hip["norm_x"] - s_hip["norm_x"])
        scale = cls.compute_torso_scale(start_lm, side=side)
        return round(dx / max(0.1, scale), 2)

    @classmethod
    def compute_landing_displacement(
        cls,
        frame_history: List[Dict[str, Any]],
        takeoff_idx: int,
        landing_idx: int
    ) -> Optional[float]:
        """Compute horizontal distance between takeoff spot and landing spot in torso lengths."""
        if not frame_history or takeoff_idx >= landing_idx:
            return None
        t_idx = max(0, takeoff_idx)
        l_idx = min(len(frame_history) - 1, landing_idx)
        t_lm = frame_history[t_idx].get("landmarks") or {}
        l_lm = frame_history[l_idx].get("landmarks") or {}
        t_ankles = [t_lm.get(j) for j in (27, 28) if t_lm.get(j)]
        l_ankles = [l_lm.get(j) for j in (27, 28) if l_lm.get(j)]
        if not t_ankles or not l_ankles:
            return None
        t_x = sum(a["norm_x"] for a in t_ankles) / len(t_ankles)
        l_x = sum(a["norm_x"] for a in l_ankles) / len(l_ankles)
        scale = cls.compute_torso_scale(t_lm)
        return round(abs(l_x - t_x) / max(0.1, scale), 2)

    @staticmethod
    def compute_load_to_release_ms(dip_frame: int, release_frame: int, fps: float = 30.0) -> float:
        """Compute time duration in ms between dip and release frames."""
        dt_frames = max(0, release_frame - dip_frame)
        return round(dt_frames * 1000.0 / max(1.0, fps), 1)

