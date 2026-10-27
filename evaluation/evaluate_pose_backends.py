"""Offline Pose Backend Comparative Benchmark: MediaPipe Tasks Pose vs. YOLOv8 Pose.

Evaluates 12 shared biomechanical keypoints between Google MediaPipe and Ultralytics YOLOv8 Pose
across validation clips, measuring detection completeness, mutual joint distance,
and temporal dropout rates without slowing down live inference.
"""

from __future__ import annotations
import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.core.pose_engine import PoseEngine

SHARED_JOINTS = {
    "left_shoulder":  {"mp": 11, "yolo": 5},
    "right_shoulder": {"mp": 12, "yolo": 6},
    "left_elbow":     {"mp": 13, "yolo": 7},
    "right_elbow":    {"mp": 14, "yolo": 8},
    "left_wrist":     {"mp": 15, "yolo": 9},
    "right_wrist":    {"mp": 16, "yolo": 10},
    "left_hip":       {"mp": 23, "yolo": 11},
    "right_hip":      {"mp": 24, "yolo": 12},
    "left_knee":      {"mp": 25, "yolo": 13},
    "right_knee":     {"mp": 26, "yolo": 14},
    "left_ankle":     {"mp": 27, "yolo": 15},
    "right_ankle":    {"mp": 28, "yolo": 16},
}


def load_yolo_pose(model_path: str = "models/yolov8m-pose.pt"):
    """Load Ultralytics YOLO Pose model."""
    try:
        from ultralytics import YOLO
        if os.path.exists(model_path):
            return YOLO(model_path)
        print(f"[WARN] YOLO Pose weights not found at {model_path}")
        return None
    except ImportError:
        print("[WARN] ultralytics not installed; cannot run YOLO Pose")
        return None


def run_pose_comparison_on_clip(
    video_path: str,
    mp_engine: PoseEngine,
    yolo_model: Any,
    max_frames: int = 150
) -> Dict[str, Any]:
    """Process video clip through both engines and compute agreement metrics."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": f"Cannot open {video_path}"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval_ms = 1000.0 / fps

    joint_distances = {j: [] for j in SHARED_JOINTS}
    mp_valid_counts = {j: 0 for j in SHARED_JOINTS}
    yolo_valid_counts = {j: 0 for j in SHARED_JOINTS}

    total_frames = 0
    both_detected_frames = 0

    while True:
        ret, frame = cap.read()
        if not ret or (max_frames and total_frames >= max_frames):
            break

        timestamp_ms = int(total_frames * frame_interval_ms)
        h, w = frame.shape[:2]

        # 1. MediaPipe Inference
        mp_out = mp_engine.process(frame, timestamp_ms)
        mp_lms = mp_out.get("smoothed_landmarks", {}) if mp_out else {}
        mp_valid = mp_out.get("valid", {}) if mp_out else {}

        # 2. YOLO Pose Inference
        yolo_kpts = None
        if yolo_model:
            try:
                y_res = yolo_model.predict(frame, verbose=False, conf=0.30)
                if y_res and len(y_res) > 0 and y_res[0].keypoints is not None:
                    # keypoints xy shape: [num_persons, 17, 2], conf: [num_persons, 17]
                    kpts_xy = y_res[0].keypoints.xy.cpu().numpy()
                    kpts_conf = y_res[0].keypoints.conf.cpu().numpy() if y_res[0].keypoints.conf is not None else None
                    if len(kpts_xy) > 0:
                        yolo_kpts = (kpts_xy[0], kpts_conf[0] if kpts_conf is not None and len(kpts_conf) > 0 else None)
            except Exception as e:
                yolo_kpts = None

        if mp_out is not None and yolo_kpts is not None:
            both_detected_frames += 1

        # Evaluate 12 shared joints
        for jname, mapping in SHARED_JOINTS.items():
            mp_idx = mapping["mp"]
            yolo_idx = mapping["yolo"]

            mp_pt = None
            if mp_idx in mp_lms and mp_valid.get(mp_idx, False):
                mp_pt = (mp_lms[mp_idx]["x"], mp_lms[mp_idx]["y"])
                mp_valid_counts[jname] += 1

            yolo_pt = None
            if yolo_kpts is not None:
                xy_arr, conf_arr = yolo_kpts
                if yolo_idx < len(xy_arr):
                    c = conf_arr[yolo_idx] if conf_arr is not None else 1.0
                    if c > 0.35 and (xy_arr[yolo_idx][0] > 0 or xy_arr[yolo_idx][1] > 0):
                        yolo_pt = (float(xy_arr[yolo_idx][0]), float(xy_arr[yolo_idx][1]))
                        yolo_valid_counts[jname] += 1

            if mp_pt is not None and yolo_pt is not None:
                dist_px = float(np.hypot(mp_pt[0] - yolo_pt[0], mp_pt[1] - yolo_pt[1]))
                norm_dist = dist_px / max(w, h)
                joint_distances[jname].append(norm_dist)

        total_frames += 1

    cap.release()

    per_joint_summary = {}
    all_dists = []
    for jname in SHARED_JOINTS:
        dists = joint_distances[jname]
        all_dists.extend(dists)
        mp_rate = (mp_valid_counts[jname] / max(1, total_frames)) * 100.0
        yolo_rate = (yolo_valid_counts[jname] / max(1, total_frames)) * 100.0
        mean_dist = float(np.mean(dists)) if dists else None
        p90_dist = float(np.percentile(dists, 90)) if dists else None

        per_joint_summary[jname] = {
            "mediapipe_detection_rate_pct": round(mp_rate, 1),
            "yolo_pose_detection_rate_pct": round(yolo_rate, 1),
            "mean_norm_distance": round(mean_dist, 4) if mean_dist else None,
            "p90_norm_distance": round(p90_dist, 4) if p90_dist else None,
            "compared_frames": len(dists)
        }

    overall_mean_dist = float(np.mean(all_dists)) if all_dists else None

    return {
        "clip_path": video_path,
        "total_frames_evaluated": total_frames,
        "frames_with_both_models": both_detected_frames,
        "overall_mean_normalized_joint_distance": round(overall_mean_dist, 4) if overall_mean_dist else None,
        "per_joint_metrics": per_joint_summary
    }


def evaluate_pose_backends(
    clips: Optional[List[str]] = None,
    yolo_model_path: str = "models/yolov8m-pose.pt",
    max_frames_per_clip: int = 120,
    output_report_path: str = "POSE_BACKEND_COMPARISON_REPORT.json"
) -> Dict[str, Any]:
    """Run full comparative benchmark across validation clips and write report."""
    if not clips:
        # Default to canonical validation clips
        cand = [
            "raw_clips/mikeddunnstud1.mp4",
            "raw_clips/lavish_3_mix.mp4",
            "raw_clips/sid_4_97deg_wrim.mp4"
        ]
        clips = [c for c in cand if os.path.exists(c)]

    yolo_model = load_yolo_pose(yolo_model_path)

    results = []
    print(f"\n======================================================================")
    print(f"  OFFLINE POSE BACKEND BENCHMARK: MediaPipe vs. YOLOv8 Pose")
    print(f"======================================================================")

    for c in clips:
        print(f"--> Evaluating {c} (up to {max_frames_per_clip} frames)...")
        mp_engine = PoseEngine(smoothing_alpha=0.35)
        try:
            res = run_pose_comparison_on_clip(c, mp_engine, yolo_model, max_frames=max_frames_per_clip)
        finally:
            mp_engine.close()
        results.append(res)
        print(f"    Both models active: {res.get('frames_with_both_models')}/{res.get('total_frames_evaluated')} frames")
        print(f"    Mean joint normalized distance: {res.get('overall_mean_normalized_joint_distance')}")

    report = {
        "benchmark": "MediaPipe_vs_YOLOv8_Pose_Comparative_Study",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mediapipe_model": "pose_landmarker.task (Heavy)",
        "yolo_pose_model": yolo_model_path,
        "evaluation_scope": "12 shared joints (shoulders, elbows, wrists, hips, knees, ankles)",
        "methodology_note": "Mutual estimate-to-estimate agreement evaluation. Neither model is treated as absolute ground truth.",
        "clips_evaluated": results
    }

    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"======================================================================")
    print(f" Report Saved To: {output_report_path}")
    print(f"======================================================================\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate MediaPipe vs YOLO Pose backends.")
    parser.add_argument("--clips", nargs="*", help="List of video files to evaluate.")
    parser.add_argument("--yolo-model", default="models/yolov8m-pose.pt", help="Path to YOLO Pose weights.")
    parser.add_argument("--max-frames", type=int, default=100, help="Max frames per clip.")
    parser.add_argument("--output", default="POSE_BACKEND_COMPARISON_REPORT.json", help="Report output file.")
    args = parser.parse_args()

    evaluate_pose_backends(
        clips=args.clips,
        yolo_model_path=args.yolo_model,
        max_frames_per_clip=args.max_frames,
        output_report_path=args.output
    )
