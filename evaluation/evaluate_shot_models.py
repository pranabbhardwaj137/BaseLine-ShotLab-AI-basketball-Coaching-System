"""
evaluate_shot_models.py - Unified Shot-Event Detector Benchmark Harness.

Compares:
 1. Uncalibrated Heuristic Baseline (ShotPhaseDetector)
 2. Calibrated Kinematic FSM (CalibratedFSMDetector)
 3. Learned ML Sequence Detector (MLSequenceDetector)

Evaluates precision, recall, F1, release timing error (ms), and false-alarm suppression
across train, val, and test splits. Emits audit-compliant SHOT_MODEL_EVAL_REPORT.json per AGENTS.md.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np

from basketball.persistence.shot_lab_db import ShotLabDB
from basketball.core.pose_engine import PoseEngine
from basketball.core.analyzer import compute_all_angles, ShotPhaseDetector
from basketball.core.shot_feature_extractor import ShotFeatureExtractor
from basketball.tracking.calibrated_fsm import CalibratedFSMDetector
from basketball.tracking.shot_detector_ml import MLSequenceDetector


MATCH_TOLERANCE_FRAMES = 15  # +/- 500 ms at 30 FPS


def match_events(
    detected_releases: List[int],
    ground_truth_releases: List[int],
    tolerance: int = MATCH_TOLERANCE_FRAMES
) -> Tuple[int, int, int, List[float]]:
    """
    Match candidate releases against ground truth releases using greedy nearest neighbor.
    Returns (TP, FP, FN, list_of_errors_in_frames).
    """
    matched_gt = set()
    errors = []
    tp = 0
    fp = 0

    for det in detected_releases:
        best_gt = None
        best_dist = float("inf")
        for gt in ground_truth_releases:
            if gt not in matched_gt:
                dist = abs(det - gt)
                if dist <= tolerance and dist < best_dist:
                    best_dist = dist
                    best_gt = gt

        if best_gt is not None:
            matched_gt.add(best_gt)
            tp += 1
            errors.append(best_dist)
        else:
            fp += 1

    fn = len(ground_truth_releases) - len(matched_gt)
    return tp, fp, fn, errors


def run_pipeline_on_clip(
    video_path: str,
    fps: float,
    max_frames: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
    """
    Run PoseEngine over video to extract frame kinematics and raw landmark data for evaluation.
    Returns (kinematics_list, raw_frames_list, duration_minutes).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video file: {video_path}")

    engine = PoseEngine(smoothing_alpha=0.35)
    extractor = ShotFeatureExtractor(default_fps=fps)

    kinematics_history: List[Dict[str, Any]] = []
    raw_frames: List[Dict[str, Any]] = []
    frame_history: List[Dict[str, Any]] = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames and frame_idx >= max_frames:
            break

        timestamp_ms = int(frame_idx * (1000.0 / max(1.0, fps)))
        out = engine.process(frame, timestamp_ms)

        if out is not None:
            landmarks = out["smoothed_landmarks"]
            valid = out["valid"]
            world = out.get("world_landmarks")
            angles = compute_all_angles(landmarks, valid, world_landmarks=world, min_visibility=0.45) or {}
            curr_frame = {"landmarks": landmarks, "angles": angles, "valid": valid, "frame_idx": frame_idx, "timestamp_ms": timestamp_ms}
            frame_history.append(curr_frame)
            raw_frames.append(curr_frame)
            if len(frame_history) > 10:
                frame_history.pop(0)

            k = extractor.extract_frame_kinematics(frame_history, fps=fps)
            kinematics_history.append(k)
        else:
            kinematics_history.append(extractor._empty_frame_features())
            raw_frames.append({"landmarks": {}, "angles": {}, "valid": False, "frame_idx": frame_idx, "timestamp_ms": timestamp_ms})

        frame_idx += 1

    cap.release()
    duration_min = (frame_idx / max(1.0, fps)) / 60.0
    return kinematics_history, raw_frames, max(0.01, duration_min)


def evaluate_detector_on_kinematics(
    detector_type: str,
    kinematics: List[Dict[str, Any]],
    raw_frames: Optional[List[Dict[str, Any]]] = None,
    trained_ml: Optional[MLSequenceDetector] = None
) -> List[int]:
    """Run specified detector over kinematic/landmark stream and return list of detected release frames."""
    detected_releases = []

    if detector_type == "uncalibrated_heuristic":
        det = ShotPhaseDetector()
        prev_state = "idle"
        frames_to_eval = raw_frames if raw_frames else []
        for f_idx, rf in enumerate(frames_to_eval):
            lm = rf.get("landmarks") or {}
            angles = rf.get("angles") or {}
            ts = rf.get("timestamp_ms", int(f_idx * (1000.0 / 30.0)))
            st, _, _ = det.update(lm, angles, timestamp_ms=ts)
            if prev_state in ("preparing", "set_point") and st == "releasing":
                detected_releases.append(f_idx)
            prev_state = st

    elif detector_type == "calibrated_fsm":
        fsm = CalibratedFSMDetector()
        for f_idx, k in enumerate(kinematics):
            _, prop = fsm.update(f_idx, k)
            if prop:
                detected_releases.append(prop["release_frame"])

    elif detector_type == "ml_sequence":
        ml = trained_ml or MLSequenceDetector()
        ml.reset_stream()
        for f_idx, k in enumerate(kinematics):
            prop = ml.update(f_idx, k)
            if prop:
                detected_releases.append(prop["release_frame"])

    return detected_releases


def evaluate_benchmark(
    db_path: str = "shot_lab.db",
    split: str = "val",
    max_frames_per_clip: Optional[int] = None,
    report_out: str = "SHOT_MODEL_EVAL_REPORT.json"
) -> Dict[str, Any]:
    """
    Run benchmark comparison across all three detectors on the requested split.
    """
    db = ShotLabDB(db_path)
    clips = db.list_labeled_clips(split=split)

    if not clips:
        raise ValueError(f"No clips found in database for split '{split}'.")

    # Check whether there are labeled intervals
    total_gt_shots = 0
    total_gt_negatives = 0
    total_evaluable_releases = 0
    clips_with_annotations = []

    for c in clips:
        ann = db.get_clip_annotations(c["clip_id"])
        intervals = ann.get("intervals", [])
        shots = [i for i in intervals if i.get("action_class") == "shot_event"]
        negs = [i for i in intervals if i.get("action_class") != "shot_event"]
        total_gt_shots += len(shots)
        total_gt_negatives += len(negs)

        evaluable_shots = [s for s in shots if s.get("release_frame") is not None]
        if max_frames_per_clip:
            evaluable_shots = [s for s in evaluable_shots if s["release_frame"] < max_frames_per_clip]

        total_evaluable_releases += len(evaluable_shots)
        if intervals:
            clips_with_annotations.append((c, shots, negs))

    if total_evaluable_releases == 0 and total_gt_negatives == 0:
        raise ValueError(
            f"[FAIL-FAST per AGENTS.md] Split '{split}' contains 0 evaluable intervals in database!\n"
            f"Cannot evaluate accuracy without human ground-truth labels covering evaluated frames."
        )

    # Train ML detector on 'train' split using REAL video kinematics
    ml_detector = MLSequenceDetector()
    train_clips = db.list_labeled_clips(split="train")
    X_train_list = []
    y_train_list = []
    extractor = ShotFeatureExtractor()

    print(f"Extracting real video training samples from {len(train_clips)} train clips...")
    for tc in train_clips:
        ann = db.get_clip_annotations(tc["clip_id"])
        t_intervals = ann.get("intervals", [])
        if not t_intervals:
            continue

        fpath = tc["file_path"]
        if not os.path.exists(fpath):
            alt = os.path.join("raw_clips", os.path.basename(fpath))
            if os.path.exists(alt):
                fpath = alt
            else:
                continue

        fps = float(tc.get("fps") or 30.0)
        t_kinematics, _, _ = run_pipeline_on_clip(fpath, fps=fps, max_frames=None)
        if len(t_kinematics) < 15:
            continue

        shot_release_frames = set()
        shot_span_frames = set()
        neg_span_frames = set()

        for intv in t_intervals:
            sf = intv["start_frame"]
            ef = intv["end_frame"]
            if intv.get("action_class") == "shot_event":
                rf = intv.get("release_frame")
                if rf is not None:
                    # Focus positive label around release keyframe
                    for f in range(max(sf, rf - 10), min(ef, rf + 6)):
                        shot_release_frames.add(f)
                for f in range(sf, ef):
                    shot_span_frames.add(f)
            else:
                for f in range(sf, ef):
                    neg_span_frames.add(f)

        for i in range(15, len(t_kinematics)):
            w = t_kinematics[i - 15:i]
            target_f = i - 1
            if target_f in shot_release_frames:
                vec = extractor.extract_window_vector(w)
                X_train_list.append(vec)
                y_train_list.append(1)
            elif target_f in neg_span_frames:
                vec = extractor.extract_window_vector(w)
                X_train_list.append(vec)
                y_train_list.append(0)
            elif i % 25 == 0 and target_f not in shot_span_frames:
                # Sample background idle frames as negatives
                vec = extractor.extract_window_vector(w)
                X_train_list.append(vec)
                y_train_list.append(0)

    if X_train_list:
        X_train = np.vstack(X_train_list)
        y_train = np.array(y_train_list, dtype=np.int32)
        train_stats = ml_detector.train(X_train, y_train)
        print(f"ML Sequence Detector trained on {len(X_train)} real window samples (Train Acc: {train_stats.get('train_accuracy')})")
    else:
        print("[WARN] No real training windows found; ML detector left untrained.")

    detectors = ["uncalibrated_heuristic", "calibrated_fsm", "ml_sequence"]
    results_by_detector: Dict[str, Any] = {}

    for det_name in detectors:
        tot_tp = 0
        tot_fp = 0
        tot_fn = 0
        all_errors_ms = []
        tot_duration_min = 0.0

        for c, shots, negs in clips_with_annotations:
            fpath = c["file_path"]
            if not os.path.exists(fpath):
                alt = os.path.join("raw_clips", os.path.basename(fpath))
                if os.path.exists(alt):
                    fpath = alt
                else:
                    raise FileNotFoundError(f"[FAIL-FAST] Video file not found: {fpath}")

            fps = float(c.get("fps") or 30.0)
            kinematics, raw_frames, dur_min = run_pipeline_on_clip(fpath, fps=fps, max_frames=max_frames_per_clip)
            tot_duration_min += dur_min

            eval_shots = [s for s in shots if s.get("release_frame") is not None]
            if max_frames_per_clip:
                eval_shots = [s for s in eval_shots if s["release_frame"] < max_frames_per_clip]

            gt_releases = [s["release_frame"] for s in eval_shots]
            det_releases = evaluate_detector_on_kinematics(det_name, kinematics, raw_frames=raw_frames, trained_ml=ml_detector)

            tp, fp, fn, frame_errors = match_events(det_releases, gt_releases, tolerance=MATCH_TOLERANCE_FRAMES)
            tot_tp += tp
            tot_fp += fp
            tot_fn += fn

            for fe in frame_errors:
                all_errors_ms.append(fe * (1000.0 / fps))

        # Compute summary metrics
        prec = (tot_tp / (tot_tp + tot_fp)) if (tot_tp + tot_fp) > 0 else 0.0
        rec = (tot_tp / (tot_tp + tot_fn)) if (tot_tp + tot_fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        mae_ms = float(np.mean(all_errors_ms)) if all_errors_ms else 0.0
        fp_per_min = (tot_fp / tot_duration_min) if tot_duration_min > 0 else 0.0

        results_by_detector[det_name] = {
            "true_positives": tot_tp,
            "false_positives": tot_fp,
            "false_negatives": tot_fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1_score": round(f1, 4),
            "release_timing_mae_ms": round(mae_ms, 1),
            "false_positives_per_min": round(fp_per_min, 2)
        }

    # Gate verification logic
    calib_f1 = results_by_detector["calibrated_fsm"]["f1_score"]
    calib_mae = results_by_detector["calibrated_fsm"]["release_timing_mae_ms"]
    ml_f1 = results_by_detector["ml_sequence"]["f1_score"]
    ml_mae = results_by_detector["ml_sequence"]["release_timing_mae_ms"]

    gate_passed = (calib_f1 >= 0.75 and calib_mae <= 150.0) or (ml_f1 >= 0.75 and ml_mae <= 150.0)
    verdict = "PROMOTED" if gate_passed else "EXPLORATORY"

    report = {
        "report_version": "1.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "synthetic": False,
        "evaluation_split": split,
        "clips_evaluated": len(clips_with_annotations),
        "total_intervals_in_split": total_gt_shots + total_gt_negatives,
        "evaluable_gt_releases": total_evaluable_releases,
        "ground_truth_negatives": total_gt_negatives,
        "max_frames_per_clip": max_frames_per_clip,
        "match_tolerance_ms": MATCH_TOLERANCE_FRAMES * (1000.0 / 30.0),
        "detectors": results_by_detector,
        "phase_6_gate_verdict": verdict,
        "recommended_detector": "calibrated_fsm" if calib_f1 >= ml_f1 else "ml_sequence"
    }

    with open(report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate shot event detectors against ground-truth splits.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database.")
    parser.add_argument("--split", default="val", help="Split to evaluate: 'train', 'val', or 'test'.")
    parser.add_argument("--max-frames", type=int, default=None, help="Max frames per clip to evaluate (optional, default: full clip).")
    parser.add_argument("--report", default="SHOT_MODEL_EVAL_REPORT.json", help="Path to output JSON report.")
    args = parser.parse_args()

    try:
        rep = evaluate_benchmark(
            db_path=args.db,
            split=args.split,
            max_frames_per_clip=args.max_frames,
            report_out=args.report
        )
        print("\n" + "=" * 70)
        print(f"  PHASE 6 SHOT-EVENT DETECTOR BENCHMARK: Split '{args.split.upper()}'")
        print("=" * 70)
        print(f" Clips Evaluated: {rep['clips_evaluated']} | Evaluable GT Releases: {rep['evaluable_gt_releases']} | Negatives: {rep['ground_truth_negatives']}")
        print(f"{'Detector':<24} | {'F1':<6} | {'Prec':<6} | {'Rec':<6} | {'MAE (ms)':<9} | {'FP/min'}")
        print("-" * 70)
        for name, metrics in rep["detectors"].items():
            print(f"{name:<24} | {metrics['f1_score']:<6.3f} | {metrics['precision']:<6.3f} | {metrics['recall']:<6.3f} | {metrics['release_timing_mae_ms']:<9.1f} | {metrics['false_positives_per_min']:.2f}")
        print("=" * 70)
        print(f" Gate Verdict:         {rep['phase_6_gate_verdict']}")
        print(f" Recommended Detector: {rep['recommended_detector']}")
        print(f" Report Saved To:      {args.report}\n")
    except Exception as e:
        print(f"\n[ERROR] Benchmark evaluation failed: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
