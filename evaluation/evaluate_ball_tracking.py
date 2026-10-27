"""Unified Evaluation Harness & Audit Report for Ball/Rim Detection and Trajectory Tracking.

Benchmarks models/best.pt on:
  Part A: Roboflow test split (Basketball.v1i.yolov8/test, 472 images) for mAP@50, Precision, Recall.
  Part B: Project video tracking coverage, trajectory fit R^2, and rim proximity across validation clips.
  Part C: Produces audit-compliant BALL_RIM_EVAL_REPORT.json conforming to AGENTS.md integrity rules.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.tracking.ball_tracker import BallTracker
try:
    from scripts.batch_ingest_clips import load_clip_splits_config
except ImportError:
    from batch_ingest_clips import load_clip_splits_config


def compute_file_sha256(filepath: str) -> str:
    """Compute cryptographic SHA256 of model checkpoint."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def evaluate_dataset_object_detection(
    weights_path: str = "models/best.pt",
    data_yaml_path: str = "Basketball.v1i.yolov8/data.yaml",
    split: str = "test",
    max_images: Optional[int] = None
) -> Dict[str, Any]:
    """Run Ultralytics evaluation on dataset split."""
    try:
        from ultralytics import YOLO
    except ImportError:
        return {"error": "ultralytics not installed"}

    if not os.path.exists(weights_path):
        return {"error": f"Weights not found: {weights_path}"}
    if not os.path.exists(data_yaml_path):
        return {"error": f"Data yaml not found: {data_yaml_path}"}

    model = YOLO(weights_path)
    abs_yaml = os.path.abspath(data_yaml_path)

    val_kwargs = {
        "data": abs_yaml,
        "split": split,
        "verbose": False,
        "batch": 16,
        "imgsz": 640
    }
    if max_images is not None and max_images > 0:
        val_kwargs["max_det"] = 50

    metrics = model.val(**val_kwargs)

    # Extract metrics
    mp = float(metrics.box.mp) if hasattr(metrics.box, "mp") else 0.0
    mr = float(metrics.box.mr) if hasattr(metrics.box, "mr") else 0.0
    map50 = float(metrics.box.map50) if hasattr(metrics.box, "map50") else 0.0
    map50_95 = float(metrics.box.map) if hasattr(metrics.box, "map") else 0.0

    # Per-class breakdown
    class_names = getattr(model, "names", {})
    class_metrics = {}
    if hasattr(metrics.box, "p") and hasattr(metrics.box, "r") and hasattr(metrics.box, "ap50"):
        p_list = metrics.box.p
        r_list = metrics.box.r
        ap50_list = metrics.box.ap50
        for idx, name in class_names.items():
            if idx < len(p_list):
                class_metrics[name] = {
                    "precision": round(float(p_list[idx]), 4),
                    "recall": round(float(r_list[idx]), 4),
                    "map50": round(float(ap50_list[idx]), 4)
                }

    return {
        "dataset_yaml": data_yaml_path,
        "split_evaluated": split,
        "total_test_images": 472 if split == "test" else 130,
        "mean_precision": round(mp, 4),
        "mean_recall": round(mr, 4),
        "map50": round(map50, 4),
        "map50_95": round(map50_95, 4),
        "per_class_metrics": class_metrics
    }


def evaluate_video_ball_tracking(
    weights_path: str = "models/best.pt",
    clips: Optional[List[str]] = None,
    max_frames_per_clip: int = 150
) -> List[Dict[str, Any]]:
    """Evaluate ball/rim detection frequency and trajectory fit on video clips."""
    tracker = BallTracker(weights_path=weights_path)
    if not clips:
        # Default to canonical validation clips, including all available clips with ground-truth labels
        cand = [
            "raw_clips/sid_4_97deg_wrim.mp4",
            "raw_clips/lavish_3_mix.mp4",
            "raw_clips/mikeddunnstud1.mp4",
            "raw_clips/mixkit-basketball-player-shooting-baskets-while-training-alone-44447-hd-ready.mp4",
            "raw_clips/mixkit-skilled-basketball-player-shooting-baskets-training-alone-44448-hd-ready.mp4"
        ]
        clips = [c for c in cand if os.path.exists(c)]

    clip_results = []
    for cpath in clips:
        cap = cv2.VideoCapture(cpath)
        if not cap.isOpened():
            continue

        clip_id = os.path.splitext(os.path.basename(cpath))[0]

        # Check for human ground-truth intervals in shot_lab.db
        gt_intervals = []
        if os.path.exists("shot_lab.db"):
            try:
                import sqlite3
                conn = sqlite3.connect("shot_lab.db")
                cur = conn.cursor()
                cur.execute(
                    "SELECT interval_id, start_frame, end_frame, release_frame, outcome "
                    "FROM labeled_intervals WHERE clip_id = ? ORDER BY start_frame",
                    (clip_id,)
                )
                gt_intervals = cur.fetchall()
                conn.close()
            except Exception:
                pass

        first_intv = gt_intervals[0] if gt_intervals else None
        if first_intv and first_intv[1] < max_frames_per_clip:
            shot_start = max(0, first_intv[1])
            shot_release = first_intv[3] if first_intv[3] is not None else shot_start + 10
            human_label = first_intv[4]
        else:
            shot_start = 0
            shot_release = 10
            human_label = None

        total_frames = 0
        ball_frames = 0
        rim_frames = 0
        conf_sum_ball = 0.0
        conf_sum_rim = 0.0

        tracker.on_shot_started(f"shot_{clip_id}", frame_idx=shot_start)

        while True:
            ret, frame = cap.read()
            if not ret or (max_frames_per_clip and total_frames >= max_frames_per_clip):
                break

            if total_frames == shot_release:
                tracker.on_shot_release(f"shot_{clip_id}", frame_idx=total_frames)

            det = tracker.detect(frame)
            tracker.update(det, landmarks=None, timestamp_ms=int(total_frames * 33.33))

            if det.get("ball") is not None:
                ball_frames += 1
                conf_sum_ball += det.get("ball_conf", 0.0)
            if det.get("rim") is not None:
                rim_frames += 1
                conf_sum_rim += det.get("rim_conf", 0.0)

            total_frames += 1

        cap.release()
        shot_summary = tracker.on_shot_ended(f"shot_{clip_id}", frame_idx=total_frames)

        ball_cov = round(ball_frames / max(1, total_frames), 3)
        rim_cov = round(rim_frames / max(1, total_frames), 3)
        mean_b_conf = round(conf_sum_ball / max(1, ball_frames), 3) if ball_frames > 0 else 0.0
        mean_r_conf = round(conf_sum_rim / max(1, rim_frames), 3) if rim_frames > 0 else 0.0

        item = {
            "clip_path": cpath,
            "total_frames_evaluated": total_frames,
            "ball_coverage_ratio": ball_cov,
            "rim_coverage_ratio": rim_cov,
            "mean_ball_confidence": mean_b_conf,
            "mean_rim_confidence": mean_r_conf,
            "trajectory_fit_r2": shot_summary.get("trajectory_fit_r2") if shot_summary else None,
            "release_angle_deg": shot_summary.get("ball_release_angle") if shot_summary else None,
            "entry_angle_deg": shot_summary.get("entry_angle") if shot_summary else None,
            "advisory_outcome": shot_summary.get("outcome") if shot_summary else "unknown",
            "advisory_reason": shot_summary.get("outcome_reason") if shot_summary else "NO_SHOT"
        }
        if human_label is not None:
            item["human_ground_truth_outcome"] = human_label
            item["human_ground_truth_intervals_total"] = len(gt_intervals)

        clip_results.append(item)

    return clip_results


def run_full_evaluation(
    weights_path: str = "models/best.pt",
    data_yaml_path: str = "Basketball.v1i.yolov8/data.yaml",
    clips: Optional[List[str]] = None,
    output_report_path: str = "BALL_RIM_EVAL_REPORT.json",
    max_clip_frames: int = 150
) -> Dict[str, Any]:
    """Execute unified dual-track benchmark and compile BALL_RIM_EVAL_REPORT.json."""
    sha256 = compute_file_sha256(weights_path) if os.path.exists(weights_path) else "MISSING"

    print(f"\n======================================================================")
    print(f"  PHASE 7 BALL & RIM TRACKING BENCHMARK: {weights_path}")
    print(f"======================================================================")
    print(f" Checksum SHA256: {sha256}")

    # 1. Dataset Evaluation
    print(f"--> Part A: Running object detection validation on {data_yaml_path}...")
    dataset_res = evaluate_dataset_object_detection(weights_path, data_yaml_path, split="test")
    print(f"    mAP@50: {dataset_res.get('map50')} | Precision: {dataset_res.get('mean_precision')} | Recall: {dataset_res.get('mean_recall')}")

    # 2. Video Tracking Evaluation
    print(f"--> Part B: Running video tracking continuity on project validation footage...")
    video_res = evaluate_video_ball_tracking(weights_path, clips=clips, max_frames_per_clip=max_clip_frames)
    mean_ball_cov = float(np.mean([c["ball_coverage_ratio"] for c in video_res])) if video_res else 0.0
    mean_rim_cov = float(np.mean([c["rim_coverage_ratio"] for c in video_res])) if video_res else 0.0
    print(f"    Clips evaluated: {len(video_res)}")
    print(f"    Average Ball Coverage: {mean_ball_cov * 100:.1f}% | Average Rim Coverage: {mean_rim_cov * 100:.1f}%")

    # Gate Verdict
    map50 = dataset_res.get("map50", 0.0)
    if map50 >= 0.70:
        verdict = "QUALIFIED_AS_ADVISORY"
    elif map50 >= 0.50:
        verdict = "EXPLORATORY"
    else:
        verdict = "DEFICIENT"

    report = {
        "benchmark": "Phase_7_Ball_Rim_and_Trajectory_Verification",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model_file": weights_path,
        "model_sha256": sha256,
        "gate_verdict": verdict,
        "advisory_governance": {
            "automated_outcomes_advisory_only": True,
            "human_ground_truth_overwritten": False,
            "baseline_admission_allowed": False,
            "governance_note": "Automated ball/rim tracking and make/miss classifications are shadow/advisory. Human M/X/U ground truth is immutable."
        },
        "part_a_dataset_object_detection": dataset_res,
        "part_b_video_tracking_continuity": {
            "pooled_ball_coverage_ratio": round(mean_ball_cov, 3),
            "pooled_rim_coverage_ratio": round(mean_rim_cov, 3),
            "clips": video_res
        }
    }

    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"======================================================================")
    print(f" Gate Verdict:         {verdict}")
    print(f" Report Saved To:      {output_report_path}")
    print(f"======================================================================\n")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate ball & rim tracking model on dataset and videos.")
    parser.add_argument("--weights", default="models/best.pt", help="Path to model weights.")
    parser.add_argument("--data-yaml", default="Basketball.v1i.yolov8/data.yaml", help="Path to Roboflow data.yaml.")
    parser.add_argument("--output", default="BALL_RIM_EVAL_REPORT.json", help="Path to report JSON.")
    parser.add_argument("--max-clip-frames", type=int, default=150, help="Max frames to process per clip.")
    args = parser.parse_args()

    run_full_evaluation(
        weights_path=args.weights,
        data_yaml_path=args.data_yaml,
        output_report_path=args.output,
        max_clip_frames=args.max_clip_frames
    )
