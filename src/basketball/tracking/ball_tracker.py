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
import logging

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
from basketball.tracking.outcome_estimator import (
    BallPt,
    RimAnchor,
    Outcome,
    estimate_outcome,
    get_cfg_hash,
    ESTIMATOR_VERSION,
    USE_LEGACY_OUTCOME,
    CFG,
)

logger = logging.getLogger(__name__)


def gate_ball_detections(
    ball_records: List[Dict[str, Any]],
    max_speed_px_per_s: float = 3500.0,
    max_size_ratio: float = 2.5
) -> List[BallPt]:
    """
    Track gating before building BallPt:
    Rejects detections whose per-frame displacement is implausible or whose bbox width
    changes sharply versus neighbors. Uses a simple physical consistency gate.
    Does not extrapolate through occlusion (the RANSAC parabola fit handles gaps).
    """
    if not ball_records:
        return []

    valid_pts: List[BallPt] = []
    for rec in ball_records:
        box = rec.get("box")
        t = float(rec.get("t", 0.0))
        conf = float(rec.get("conf", 0.0))
        if box is None or len(box) < 4:
            continue
        cx = (float(box[0]) + float(box[2])) / 2.0
        cy = (float(box[1]) + float(box[3])) / 2.0
        w = max(1.0, float(box[2]) - float(box[0]))

        if valid_pts:
            prev = valid_pts[-1]
            dt = t - prev.t
            if dt > 1e-4:
                dist = float(np.hypot(cx - prev.x, cy - prev.y))
                speed = dist / dt
                if speed > max_speed_px_per_s:
                    continue
                size_ratio = max(w, prev.w) / min(w, prev.w)
                if size_ratio > max_size_ratio and dt < 0.2:
                    continue
        valid_pts.append(BallPt(t=t, x=cx, y=cy, w=w, conf=conf))
    return valid_pts

def merge_ball_detections(
    full_det: Optional[Dict[str, Any]],
    roi_det: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge full-frame and rim-ROI ball detections.
    Keep the higher confidence when they overlap, or take whichever is detected.
    """
    f_ball = full_det.get("ball") if full_det else None
    f_conf = float(full_det.get("ball_conf", 0.0) or 0.0) if full_det else 0.0

    r_ball = roi_det.get("ball") if roi_det else None
    r_conf = float(roi_det.get("ball_conf", 0.0) or 0.0) if roi_det else 0.0

    if f_ball is None and r_ball is None:
        return {"ball": None, "ball_conf": 0.0}
    if f_ball is None:
        return {"ball": r_ball, "ball_conf": r_conf}
    if r_ball is None:
        return {"ball": f_ball, "ball_conf": f_conf}

    fx1, fy1, fx2, fy2 = f_ball
    rx1, ry1, rx2, ry2 = r_ball
    inter_x1 = max(fx1, rx1)
    inter_y1 = max(fy1, ry1)
    inter_x2 = min(fx2, rx2)
    inter_y2 = min(fy2, ry2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    f_area = max(1.0, (fx2 - fx1) * (fy2 - fy1))
    r_area = max(1.0, (rx2 - rx1) * (ry2 - ry1))
    iou = inter_area / (f_area + r_area - inter_area)

    fcx, fcy = (fx1 + fx2) / 2.0, (fy1 + fy2) / 2.0
    rcx, rcy = (rx1 + rx2) / 2.0, (ry1 + ry2) / 2.0
    dist = float(np.hypot(fcx - rcx, fcy - rcy))
    max_d = max(fx2 - fx1, rx2 - rx1) * 1.5

    if iou > 0.05 or dist < max_d:
        if r_conf > f_conf:
            return {"ball": r_ball, "ball_conf": r_conf}
        return {"ball": f_ball, "ball_conf": f_conf}

    if r_conf > f_conf:
        return {"ball": r_ball, "ball_conf": r_conf}
    return {"ball": f_ball, "ball_conf": f_conf}




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
        inference_size: int = 640,
        rim_anchor: Optional[RimAnchor] = None,
        fps: float = 30.0,
    ):
        self.model, self.mode, self.ball_classes, self.rim_classes = load_yolo(weights_path)
        self.conf = conf
        self.near_hand_px = near_hand_px
        self.leave_hand_px = leave_hand_px
        self.detect_every = max(1, detect_every)
        self.inference_size = inference_size
        self.rim_anchor: Optional[RimAnchor] = rim_anchor
        self.fps = fps
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
        self.active_shot_ball_records: List[Dict[str, Any]] = []

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
        self.active_shot_ball_records = []
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

        # Run Track Gating before building BallPt
        ball_pts = gate_ball_detections(self.active_shot_ball_records)
        release_t = (
            float(self.active_shot_release_time_ms) / 1000.0
            if self.active_shot_release_time_ms is not None
            else (float(self.active_shot_release_frame) / self.fps if self.active_shot_release_frame is not None else 0.0)
        )

        # Reference Outcome Estimator
        outcome_obj = estimate_outcome(ball_pts, release_t, self.rim_anchor)

        # Legacy calculation: used when self.rim_anchor is not configured or USE_LEGACY_OUTCOME is True
        legacy_outcome = "unknown"
        legacy_conf = 0.0
        legacy_reason = "NO_LEGACY_MATCH"
        if not self.rim_supported:
            legacy_reason = "UNAVAILABLE_NO_WEIGHTS"
        elif len(pts) < 4:
            legacy_reason = "INSUFFICIENT_FLIGHT_POINTS"
        elif last_rim is None:
            legacy_reason = "RIM_NOT_DETECTED"
        elif fit_r2 is None or fit_r2 < 0.70:
            legacy_reason = "POOR_TRAJECTORY_FIT"
        else:
            apex_idx = 0
            if peak is not None:
                for i, p in enumerate(pts):
                    if p[1] == peak[1]:
                        apex_idx = i
                        break
            post_apex_pts = pts[apex_idx:] if apex_idx < len(pts) else pts
            passed_near = any(ball_under_rim(p, last_rim, x_threshold=80.0) for p in post_apex_pts)
            legacy_outcome = "make" if passed_near else "miss"
            legacy_conf = round(min(0.95, float(fit_r2 or 0.5)), 2)
            legacy_reason = "TRAJECTORY_ENTRY_CONFIRMED" if passed_near else "MISSED_TRAJECTORY_ALIGNMENT"

        if USE_LEGACY_OUTCOME or self.rim_anchor is None:
            final_outcome = legacy_outcome
            final_reason = legacy_reason
            final_conf = legacy_conf
        else:
            final_outcome = outcome_obj.label
            final_reason = outcome_obj.reason
            final_conf = outcome_obj.confidence if outcome_obj.confidence is not None else 0.0

        logger.info(
            "OUTCOME COMPARISON [Shot %s]: Legacy=%s (conf=%.2f, reason=%s) vs Estimator=%s (p_make=%s, conf=%s, reason=%s)",
            shot_id, legacy_outcome, legacy_conf, legacy_reason,
            outcome_obj.label, outcome_obj.p_make, outcome_obj.confidence, outcome_obj.reason
        )

        summary = {
            "shot_id": shot_id,
            "ball_detection_status": coverage_status,
            "rim_detection_status": self.rim_status,
            "ball_coverage_ratio": round(coverage_ratio, 2),
            "ball_release_angle": release_angle,
            "entry_angle": entry_angle,
            "trajectory_fit_r2": fit_r2,
            "arc_peak": peak,
            "outcome": final_outcome,
            "outcome_reason": final_reason,
            "outcome_conf": final_conf,
            "p_make": outcome_obj.p_make,
            "confidence": outcome_obj.confidence,
            "evidence_quality": outcome_obj.evidence_quality,
            "outcome_features": outcome_obj.features,
            "estimator_version": ESTIMATOR_VERSION,
            "estimator_cfg_hash": get_cfg_hash(),
            "flight_points_count": len(ball_pts) if ball_pts else len(pts),
            "flight_centers": [[round(float(p.x), 1), round(float(p.y), 1)] for p in ball_pts] if ball_pts else [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in pts],
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
                classes=detect_classes if detect_classes else None,
                imgsz=self.inference_size
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


    def detect_rim_roi(
        self,
        frame: np.ndarray,
        rim: Optional[RimAnchor] = None,
        roi_scale: float = 6.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Rim-ROI second pass:
        Run ball detector on a full-resolution crop centered on the rim,
        about 6 rim widths wide and tall, and map detections back to full-frame coordinates.
        """
        anchor = rim or self.rim_anchor
        if self.model is None or self.mode == "unavailable" or anchor is None:
            return None

        h_frame, w_frame = frame.shape[:2]
        half = (roi_scale * anchor.w) / 2.0
        crop_x1 = max(0, int(anchor.cx - half))
        crop_y1 = max(0, int(anchor.cy - half))
        crop_x2 = min(w_frame, int(anchor.cx + half))
        crop_y2 = min(h_frame, int(anchor.cy + half))

        if crop_x2 <= crop_x1 + 10 or crop_y2 <= crop_y1 + 10:
            return None

        roi_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        try:
            results = self.model.predict(
                roi_crop,
                verbose=False,
                conf=self.conf,
                classes=self.ball_classes if self.ball_classes else None,
                imgsz=self.inference_size,
            )
        except Exception:
            return None

        best_ball, best_conf = None, 0.0
        if results and len(results) > 0:
            for box in results[0].boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                if cls in self.ball_classes and conf >= best_conf:
                    xyxy = [float(v) for v in box.xyxy[0].tolist()]
                    mapped = [
                        xyxy[0] + crop_x1,
                        xyxy[1] + crop_y1,
                        xyxy[2] + crop_x1,
                        xyxy[3] + crop_y1,
                    ]
                    best_ball = mapped
                    best_conf = conf

        if best_ball is not None:
            return {"ball": best_ball, "ball_conf": round(best_conf, 2)}
        return None

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
                t_sec = float(timestamp_ms) / 1000.0 if timestamp_ms else (float(self.active_shot_total_frames) / self.fps)
                self.active_shot_ball_records.append({"t": t_sec, "box": ball, "conf": ball_conf})
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
