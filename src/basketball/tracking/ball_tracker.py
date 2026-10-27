"""In-memory ball and rim tracker with dynamic class resolution and explicit evidence gating.

Model Limitations & Architecture:
  - Supports dynamic YOLO checkpoints via --weights (defaults to models/best.pt).
  - Dynamically inspects model.names to map ball and rim classes.
  - Stock YOLOv8n COCO model detects class 32 ('sports ball') only. Rim tracking,
    rim entry angle, and automated make/miss classification are UNAVAILABLE without
    rim-aware weights (e.g. models/best.pt or models/ballRim.pt).
  - Confidence gating: detections with confidence < 0.30 or flights with < 4 verified
    centers are marked as 'Inconclusive / Insufficient Evidence'.
  - Automated outcomes remain strictly advisory / shadow and never overwrite human ground truth.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import cv2
import numpy as np

from basketball.tracking.ball_geometry import (
    arc_peak,
    ball_under_rim,
    box_center,
    box_to_point_distance,
    calculate_entry_angle,
    fit_parabola,
    last_valid_box,
    point_distance,
    release_angle_deg,
    sample_parabola,
)


def load_yolo(weights_path: Optional[str] = None) -> Tuple[Any, str, List[int], List[int]]:
    """
    Load YOLO model with dynamic class resolution.
    Returns (model, mode, ball_classes, rim_classes).
    Mode is 'custom', 'coco', or 'unavailable'.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[WARN] Ball tracking needs ultralytics. Falling back to UNAVAILABLE mode.")
        return None, "unavailable", [], []

    # Search candidates: explicit weights_path -> models/best.pt -> weights/basket_rim.pt -> yolov8n.pt
    candidates = []
    if weights_path:
        candidates.append(Path(weights_path))
    candidates.extend([
        Path("models/best.pt"),
        Path("weights/basket_rim.pt"),
        Path("yolov8n.pt")
    ])

    loaded_model = None
    loaded_path = None
    for cand in candidates:
        if cand.exists():
            try:
                loaded_model = YOLO(str(cand))
                loaded_path = cand
                break
            except Exception as e:
                print(f"[WARN] Failed to load candidate weights {cand}: {e}")

    if loaded_model is None:
        try:
            print("[INFO] Attempting download/load of stock yolov8n.pt...")
            loaded_model = YOLO("yolov8n.pt")
            loaded_path = Path("yolov8n.pt")
        except Exception as e:
            print(f"[WARN] Could not load YOLO model: {e}")
            return None, "unavailable", [], []

    # Dynamic Class Resolution from model.names
    names = getattr(loaded_model, "names", {})
    if isinstance(names, list):
        names_dict = {i: n for i, n in enumerate(names)}
    elif isinstance(names, dict):
        names_dict = names
    else:
        names_dict = {}

    ball_classes = [
        int(idx) for idx, name in names_dict.items()
        if any(k in str(name).lower() for k in ["ball", "basketball"])
    ]
    rim_classes = [
        int(idx) for idx, name in names_dict.items()
        if (any(k in str(name).lower() for k in ["rim", "hoop", "net"]) or str(name).lower().strip() == "basket")
        and "basketball" not in str(name).lower()
    ]

    # COCO fallback: if no ball classes resolved, check for sports ball (class 32)
    if not ball_classes and 32 in names_dict:
        ball_classes = [32]

    if rim_classes:
        mode = "custom"
        print(f"[INFO] Loaded custom YOLO weights: {loaded_path} (ball classes: {ball_classes}, rim classes: {rim_classes})")
    else:
        mode = "coco"
        print(f"[INFO] Loaded YOLO model without rim: {loaded_path} (mode: coco, ball classes: {ball_classes})")

    return loaded_model, mode, ball_classes, rim_classes


class BallTracker:
    """Tracks basketball trajectory, launch angle, and rim entry geometry with dynamic classes."""

    def __init__(
        self,
        weights_path: Optional[str] = None,
        conf: float = 0.25,
        near_hand_px: float = 130.0,
        leave_hand_px: float = 150.0,
        detect_every: int = 1,
    ):
        self.model, self.mode, self.ball_classes, self.rim_classes = load_yolo(weights_path)
        self.conf = conf
        self.near_hand_px = near_hand_px
        self.leave_hand_px = leave_hand_px
        self.detect_every = max(1, detect_every)
        self._frame_i = 0
        self._last = {"ball": None, "rim": None, "ball_conf": 0.0, "rim_conf": 0.0}

        self.rim_supported = (self.mode == "custom" and len(self.rim_classes) > 0)
        if self.mode == "unavailable":
            self.rim_status = "UNAVAILABLE_NO_WEIGHTS"
        elif self.rim_supported:
            self.rim_status = "NOT_DETECTED"
        else:
            self.rim_status = "UNAVAILABLE_NO_WEIGHTS"

        # Active Shot Lifecycle Synchronization State
        self.active_shot_id: Optional[str] = None
        self.active_shot_start_frame: Optional[int] = None
        self.active_shot_release_frame: Optional[int] = None
        self.active_shot_release_time_ms: Optional[int] = None
        self.active_shot_total_frames: int = 0
        self.active_shot_ball_frames: int = 0
        self.active_shot_flight_centers: List[Tuple[float, float]] = []
        self.active_shot_flight_timestamps: List[int] = []

        self.release_started: bool = False
        self.release_ended: bool = False
        self.tracking_flight: bool = False
        self.ball_history: List[Optional[List[float]]] = []
        self.rim_history: List[Optional[List[float]]] = []
        self.flight_centers: List[Tuple[float, float]] = []
        self.flight_timestamps: List[int] = []
        self.release_frames: int = 0
        self.last_shot: Optional[Dict[str, Any]] = None

    def on_shot_started(self, shot_id: str, frame_idx: int, timestamp_ms: int = 0) -> None:
        """Called by master pose engine when a new shot attempt begins."""
        self.active_shot_id = shot_id
        self.active_shot_start_frame = frame_idx
        self.active_shot_release_frame = None
        self.active_shot_release_time_ms = None
        self.active_shot_total_frames = 0
        self.active_shot_ball_frames = 0
        self.active_shot_flight_centers = []
        self.active_shot_flight_timestamps = []
        self.active_shot_last_rim = None
        self.release_started = True
        self.tracking_flight = False

    def on_shot_release(self, shot_id: str, frame_idx: int, timestamp_ms: int = 0, hand_coords=None) -> None:
        """Called by master pose engine when kinematic release is triggered."""
        if self.active_shot_id == shot_id:
            self.active_shot_release_frame = frame_idx
            self.active_shot_release_time_ms = timestamp_ms
            self.tracking_flight = True

    def on_shot_ended(self, shot_id: str, frame_idx: int, timestamp_ms: int = 0) -> Optional[Dict[str, Any]]:
        """Called by master pose engine when follow-through completes. Returns isolated summary."""
        if self.active_shot_id != shot_id:
            return None

        total_frames = max(1, self.active_shot_total_frames)
        detected_frames = self.active_shot_ball_frames
        coverage_ratio = detected_frames / total_frames

        if detected_frames == 0:
            coverage_status = "NOT_DETECTED"
        elif coverage_ratio >= 0.70:
            coverage_status = "HIGH_COVERAGE"
        else:
            coverage_status = "LOW_COVERAGE"

        # Fit parabola to flight centers collected during post-release flight
        pts = [c for c in self.active_shot_flight_centers if c is not None]
        release_angle = None
        entry_angle = None
        fit_r2 = None
        peak = None

        # Determine rim box (prefer rim observed during active shot, fall back to last detection)
        last_rim = getattr(self, "active_shot_last_rim", None) or self._last.get("rim")

        if len(pts) >= 4:
            peak = arc_peak(self.active_shot_flight_centers)
            parabola = fit_parabola(self.active_shot_flight_centers)
            if parabola is not None:
                fit_r2 = parabola.get("r2")
                # Calculate entry angle using most recent rim detection if available
                if last_rim is not None:
                    entry_angle = calculate_entry_angle(parabola, last_rim)
            if len(pts) >= 2:
                release_angle = release_angle_deg(
                    pts[1],
                    pts[0]
                )

        # Advisory Make / Miss Qualification
        if not self.rim_supported:
            outcome = "unknown"
            outcome_reason = "UNAVAILABLE_NO_WEIGHTS"
            outcome_conf = 0.0
        elif len(pts) < 4:
            outcome = "unknown"
            outcome_reason = "INSUFFICIENT_FLIGHT_POINTS"
            outcome_conf = 0.0
        elif last_rim is None:
            outcome = "unknown"
            outcome_reason = "RIM_NOT_DETECTED"
            outcome_conf = 0.0
        elif fit_r2 is None or fit_r2 < 0.70:
            outcome = "unknown"
            outcome_reason = "POOR_TRAJECTORY_FIT"
            outcome_conf = round(float(fit_r2), 2) if fit_r2 is not None else 0.0
        else:
            # Check rim proximity and entry alignment
            rim_center = box_center(last_rim)
            # Find points after apex
            apex_idx = 0
            if peak is not None:
                for i, p in enumerate(pts):
                    if p[1] == peak[1]:
                        apex_idx = i
                        break
            post_apex_pts = pts[apex_idx:] if apex_idx < len(pts) else pts

            # Check if any post-apex ball center is near or below rim center
            passed_near_rim = False
            for p in post_apex_pts:
                if ball_under_rim(p, last_rim, x_threshold=80.0):
                    passed_near_rim = True
                    break

            fit_conf = float(fit_r2) if fit_r2 is not None else 0.50
            if passed_near_rim:
                outcome = "make"
                outcome_reason = "TRAJECTORY_ENTRY_CONFIRMED"
                outcome_conf = round(min(0.95, fit_conf), 2)
            else:
                outcome = "miss"
                outcome_reason = "MISSED_TRAJECTORY_ALIGNMENT"
                outcome_conf = round(min(0.95, fit_conf), 2)

        summary = {
            "shot_id": shot_id,
            "ball_detection_status": coverage_status,
            "rim_detection_status": self.rim_status,
            "ball_coverage_ratio": round(coverage_ratio, 2),
            "ball_release_angle": release_angle,
            "entry_angle": entry_angle,
            "trajectory_fit_r2": fit_r2,
            "arc_peak": peak,
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            "outcome_conf": outcome_conf,
            "flight_points_count": len(pts),
        }

        self.last_shot = summary
        self.active_shot_id = None
        self.tracking_flight = False
        return summary

    def detect(self, frame: np.ndarray) -> Dict[str, Any]:
        """Run YOLO inference with dynamic classes."""
        self._frame_i += 1
        if (self._frame_i - 1) % self.detect_every != 0:
            return dict(self._last)

        if self.model is None or self.mode == "unavailable":
            return {
                "ball": None,
                "rim": None,
                "ball_conf": 0.0,
                "rim_conf": 0.0,
                "rim_status": "UNAVAILABLE_NO_WEIGHTS"
            }

        detect_classes = list(set(self.ball_classes + self.rim_classes))
        try:
            results = self.model.predict(
                frame,
                verbose=False,
                conf=self.conf,
                classes=detect_classes if detect_classes else None
            )
        except Exception as e:
            return dict(self._last)

        ball, rim, ball_conf, rim_conf = None, None, 0.0, 0.0
        if results and len(results) > 0:
            boxes = results[0].boxes
            for box in boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                xyxy = [float(v) for v in box.xyxy[0].tolist()]

                if cls in self.ball_classes and conf >= ball_conf:
                    ball, ball_conf = xyxy, conf
                elif cls in self.rim_classes and conf >= rim_conf:
                    rim, rim_conf = xyxy, conf

        if self.rim_supported and rim is not None:
            self.rim_status = "CONFIRMED_RIM"
        elif self.rim_supported:
            self.rim_status = "NOT_DETECTED"
        else:
            self.rim_status = "UNAVAILABLE_NO_WEIGHTS"

        self._last = {
            "ball": ball,
            "rim": rim,
            "ball_conf": round(ball_conf, 2),
            "rim_conf": round(rim_conf, 2),
            "rim_status": self.rim_status,
        }
        return dict(self._last)

    def update(self, detections: Dict[str, Any], landmarks: Optional[Dict[int, Any]], valid=None, timestamp_ms: int = 0) -> Dict[str, Any]:
        """Advance trajectory state machine with confidence gating."""
        wrists = _wrist_pixels(landmarks, valid)
        elbow_y = _shooting_elbow_y(landmarks, valid)
        ball = detections.get("ball")
        rim = detections.get("rim")
        ball_conf = detections.get("ball_conf", 0.0)

        self.ball_history.append(ball)
        self.rim_history.append(rim)

        if self.active_shot_id is not None:
            self.active_shot_total_frames += 1
            if rim is not None:
                self.active_shot_last_rim = rim
            if ball is not None and ball_conf >= 0.30:
                self.active_shot_ball_frames += 1
                center = box_center(ball)
                if center is not None and self.tracking_flight:
                    self.active_shot_flight_centers.append(center)
                    self.active_shot_flight_timestamps.append(timestamp_ms)

        status = "idle"
        release_angle = None
        outcome = None

        near = _ball_near_any_wrist(ball, wrists, self.near_hand_px)
        above_elbow = _ball_above_elbow(ball, elbow_y)

        if near and above_elbow:
            status = "in_hand"
        elif self.tracking_flight:
            status = "in_flight"

        return {
            "status": status,
            "mode": self.mode,
            "rim_status": self.rim_status,
            "ball_conf": ball_conf,
            "release_angle": release_angle,
            "outcome": outcome,
            "release_frames": self.release_frames,
            "ball": ball,
            "rim": rim,
            "flight_centers": list(self.active_shot_flight_centers) if self.active_shot_id else list(self.flight_centers),
            "last_shot": self.last_shot,
        }

    def reset(self) -> None:
        self.release_started = False
        self.release_ended = False
        self.tracking_flight = False
        self.ball_history = []
        self.rim_history = []
        self.flight_centers = []
        self.flight_timestamps = []
        self.release_frames = 0

    def draw(self, frame: np.ndarray, info: Dict[str, Any]) -> np.ndarray:
        """Render ball trajectory, bounding box, and model transparency banner."""
        if not info:
            return frame

        ball = info.get("ball")
        rim = info.get("rim")
        ball_conf = info.get("ball_conf", 0.0)
        mode = info.get("mode", "coco")

        # 1. Draw Ball Bounding Box & Center
        if ball is not None and ball_conf >= 0.30:
            cx, cy = [int(v) for v in box_center(ball)]
            x1, y1, x2, y2 = [int(v) for v in ball]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
            cv2.circle(frame, (cx, cy), 4, (0, 140, 255), -1)
            cv2.putText(
                frame, f"Ball: {ball_conf:.2f}", (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1, cv2.LINE_AA,
            )

        # 2. Draw Rim Bounding Box
        if rim is not None:
            rx1, ry1, rx2, ry2 = [int(v) for v in rim]
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
            cv2.putText(
                frame, "Basket Rim", (rx1, max(20, ry1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA,
            )

        # 3. Draw Parabolic Flight Path Trail
        centers = info.get("flight_centers", [])
        for i in range(1, len(centers)):
            pt1 = (int(centers[i - 1][0]), int(centers[i - 1][1]))
            pt2 = (int(centers[i][0]), int(centers[i][1]))
            cv2.line(frame, pt1, pt2, (0, 215, 255), 2, cv2.LINE_AA)

        # 4. Ball HUD status badge (Bottom Left)
        height = frame.shape[0]
        if mode == "custom":
            mode_text = "YOLO: Custom (Ball + Rim)"
        elif mode == "coco":
            mode_text = "YOLO: Stock COCO (Ball Only)"
        else:
            mode_text = "YOLO: Unavailable"
        status_text = info.get("status", "idle").upper()
        hud_str = f"{mode_text} | Status: {status_text}"
        cv2.putText(frame, hud_str, (30, height - 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1, cv2.LINE_AA)

        return frame


def _wrist_pixels(landmarks: Optional[Dict[int, Any]], valid=None) -> List[Tuple[float, float]]:
    if not landmarks:
        return []
    pts = []
    for idx in (15, 16):
        if idx in landmarks and (valid is None or valid.get(idx, True)):
            pts.append((landmarks[idx]["x"], landmarks[idx]["y"]))
    return pts


def _shooting_elbow_y(landmarks: Optional[Dict[int, Any]], valid=None) -> Optional[float]:
    if not landmarks:
        return None
    for idx in (14, 13):
        if idx in landmarks and (valid is None or valid.get(idx, True)):
            return landmarks[idx]["y"]
    return None


def _ball_near_any_wrist(ball: Optional[List[float]], wrists: List[Tuple[float, float]], threshold_px: float) -> bool:
    if ball is None or not wrists:
        return False
    center = box_center(ball)
    return any(point_distance(center, w) < threshold_px for w in wrists)


def _ball_above_elbow(ball: Optional[List[float]], elbow_y: Optional[float]) -> bool:
    if ball is None or elbow_y is None:
        return False
    center = box_center(ball)
    return center[1] < elbow_y
