"""
batch_ingest_clips.py - Automated Batch Ingestion & Proposal Generation for Raw Clips.

Scans the raw_clips directory, extracts video metadata, enforces player identity
normalization (mapping all sid_*.mp4 to 'sid', lavish_*.mp4 to 'lavish', etc.),
partitions splits with zero leakage, and runs automated pose/shot phase proposals.
"""

from __future__ import annotations
import os
import sys
import json
import hashlib
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import cv2

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.persistence.shot_lab_db import ShotLabDB
from basketball.core.pose_engine import PoseEngine
from basketball.core.analyzer import ShotPhaseDetector, compute_all_angles
from evaluation.validate_dataset import DatasetValidator
from basketball.tracking.calibrated_fsm import CalibratedFSMDetector
from basketball.core.shot_feature_extractor import ShotFeatureExtractor
from basketball.tracking.shot_detector_ml import MLSequenceDetector

# Player Registry Definitions
PLAYER_REGISTRY = {
    "sid": {"name": "Sid", "height_m": 1.83, "wingspan_m": 1.85},
    "lavish": {"name": "Lavish", "height_m": 1.80, "wingspan_m": 1.82},
    "mike_dunn": {"name": "Mike Dunn", "height_m": 1.88, "wingspan_m": 1.90},
    "klay_thompson": {"name": "Klay Thompson", "height_m": 1.98, "wingspan_m": 2.06},
    "mixkit_shooter": {"name": "Mixkit Shooter", "height_m": 1.85, "wingspan_m": 1.88},
    "stock_shooter": {"name": "Stock Shooter", "height_m": 1.85, "wingspan_m": 1.88}
}

# Fallback Player-level Split Strategy
DEFAULT_PLAYER_SPLITS = {
    "lavish": "train",
    "klay_thompson": "train",
    "mike_dunn": "val",
    "sid": "train",
    "mixkit_shooter": "val",
    "stock_shooter": "train"
}

SPLITS_CONFIG_PATH = "configs/clip_splits.json" if os.path.exists("configs/clip_splits.json") else "clip_splits.json"


def load_clip_splits_config() -> Dict[str, str]:
    """Load explicit clip splits from config file if available."""
    if os.path.exists(SPLITS_CONFIG_PATH):
        try:
            with open(SPLITS_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k.lower(): v.lower() for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            print(f"[WARN] Failed to read {SPLITS_CONFIG_PATH}: {e}")
    return {}


def compute_sha256(filepath: str, block_size: int = 65536) -> str:
    """Calculate SHA256 checksum of a file."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            sha.update(block)
    return sha.hexdigest()


def normalize_player_id(filename: str) -> Tuple[str, str]:
    """
    Map video filename to canonical player_id and display name.
    Ensures sid_1..sid_6 all map to 'sid', lavish_1..lavish_5 to 'lavish', etc.
    """
    name_lower = filename.lower()
    if name_lower.startswith("sid_") or "sid" in name_lower:
        return "sid", PLAYER_REGISTRY["sid"]["name"]
    elif name_lower.startswith("lavish_") or "lavish" in name_lower:
        return "lavish", PLAYER_REGISTRY["lavish"]["name"]
    elif "mike" in name_lower or "dunn" in name_lower:
        return "mike_dunn", PLAYER_REGISTRY["mike_dunn"]["name"]
    elif "klay" in name_lower:
        return "klay_thompson", PLAYER_REGISTRY["klay_thompson"]["name"]
    elif "mixkit" in name_lower:
        return "mixkit_shooter", PLAYER_REGISTRY["mixkit_shooter"]["name"]
    elif "whatsapp" in name_lower or any(ch.isdigit() for ch in filename):
        return "stock_shooter", PLAYER_REGISTRY["stock_shooter"]["name"]
    else:
        base = os.path.splitext(filename)[0].split("_")[0].lower()
        if base in PLAYER_REGISTRY:
            return base, PLAYER_REGISTRY[base]["name"]
        return "stock_shooter", PLAYER_REGISTRY["stock_shooter"]["name"]


def infer_camera_view(filename: str) -> str:
    """Infer camera viewpoint from filename conventions."""
    name_lower = filename.lower()
    if any(k in name_lower for k in ["90deg", "97deg", "side", "klay", "mikeddunnstud2"]):
        return "side_90"
    elif any(k in name_lower for k in ["0deg", "front"]):
        return "frontal_0"
    elif any(k in name_lower for k in ["stud1", "mix", "mult", "mikedunn", "sid_1", "sid_2"]):
        return "oblique_45"
    return "oblique_45"


def generate_clip_id(filename: str) -> str:
    """Generate clean, human-readable clip_id from filename."""
    stem = os.path.splitext(filename)[0]
    # Clean redundant suffixes while preserving distinction
    return stem.lower()


def detect_proposals_for_clip(
    video_path: str,
    fps: float,
    total_frames: int,
    shot_style: str = "jump_shot",
    detector_type: str = "calibrated"
) -> List[Dict[str, Any]]:
    """
    Run PoseEngine + chosen detector (calibrated | ml_sequence | heuristic) over the video.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    engine = PoseEngine(smoothing_alpha=0.35)
    extractor = ShotFeatureExtractor(default_fps=fps)

    calib_detector = CalibratedFSMDetector(shot_style=shot_style) if detector_type == "calibrated" else None
    ml_detector = MLSequenceDetector(default_fps=fps) if detector_type == "ml_sequence" else None
    heuristic_detector = ShotPhaseDetector(shot_style=shot_style) if detector_type == "heuristic" else None

    proposals: List[Dict[str, Any]] = []
    frame_idx = 0
    frame_history: List[Dict[str, Any]] = []
    current_start = None
    current_dip = None
    current_set = None
    current_release = None
    prev_state = "idle"

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_ms = int(frame_idx * (1000.0 / max(fps, 1.0)))
        out = engine.process(frame, timestamp_ms)

        if out is not None:
            landmarks = out["smoothed_landmarks"]
            valid = out["valid"]
            world_landmarks = out.get("world_landmarks")
            angles = compute_all_angles(landmarks, valid, world_landmarks=world_landmarks, min_visibility=0.45) or {}

            frame_history.append({"landmarks": landmarks, "angles": angles, "frame_idx": frame_idx})
            if len(frame_history) > 10:
                frame_history.pop(0)

            kinematics = extractor.extract_frame_kinematics(frame_history, fps=fps)

            if detector_type == "calibrated" and calib_detector is not None:
                _, prop = calib_detector.update(frame_idx, kinematics)
                if prop:
                    proposals.append(prop)

            elif detector_type == "ml_sequence" and ml_detector is not None:
                prop = ml_detector.update(frame_idx, kinematics)
                if prop:
                    proposals.append(prop)

            elif detector_type == "heuristic" and heuristic_detector is not None:
                state, vy, ve = heuristic_detector.update(landmarks, angles, timestamp_ms)
                if prev_state in ("idle", "follow_through") and state == "preparing":
                    current_start = frame_idx
                    current_dip = frame_idx
                    current_set = None
                    current_release = None
                if prev_state == "preparing" and state == "set_point":
                    current_set = frame_idx
                if prev_state in ("preparing", "set_point") and state == "releasing":
                    current_release = frame_idx
                if state == "follow_through" and prev_state in ("releasing", "set_point"):
                    p_start = max(0, current_start if current_start is not None else frame_idx - 15)
                    p_dip = current_dip if current_dip is not None else p_start
                    p_set = current_set if current_set is not None else (p_start + (frame_idx - p_start) // 2)
                    p_rel = current_release if current_release is not None else (frame_idx - 3)
                    p_end = min(total_frames - 1, frame_idx)
                    if p_start <= p_dip <= p_set <= p_rel <= p_end:
                        proposals.append({
                            "detector_name": "shot_phase_detector",
                            "detector_version": "1.0.0",
                            "start_frame": int(p_start),
                            "dip_frame": int(p_dip),
                            "set_frame": int(p_set),
                            "release_frame": int(p_rel),
                            "end_frame": int(p_end),
                            "confidence": 0.85,
                            "status": "proposed"
                        })
                    current_start = None
                    current_dip = None
                    current_set = None
                    current_release = None
                prev_state = state

        frame_idx += 1

    cap.release()
    return proposals


def ingest_all_clips(
    clips_dir: str = "raw_clips",
    db_path: str = "shot_lab.db",
    generate_proposals: bool = True,
    force_repropose: bool = False,
    detector_type: str = "calibrated"
) -> Dict[str, Any]:
    """
    Batch process and ingest all video clips in clips_dir.
    """
    if not os.path.exists(clips_dir):
        raise FileNotFoundError(f"Clips directory '{clips_dir}' does not exist.")

    db = ShotLabDB(db_path=db_path)

    # 1. Ensure Player Profiles in DB
    print("\n--- Registering Base Players ---")
    for p_id, p_info in PLAYER_REGISTRY.items():
        db.upsert_player(
            player_id=p_id,
            name=p_info["name"],
            height_m=p_info.get("height_m"),
            wingspan_m=p_info.get("wingspan_m")
        )
        print(f" [Player] {p_id:15s} -> {p_info['name']} (Registered)")

    # 2. Find all video clips
    valid_extensions = {".mp4", ".mov", ".avi", ".mkv"}
    video_files = sorted([
        f for f in os.listdir(clips_dir)
        if os.path.splitext(f)[1].lower() in valid_extensions
    ])

    if not video_files:
        print(f"[WARN] No video files found in {clips_dir}")
        return {"total_clips": 0, "clips_ingested": 0}

    print(f"\n--- Found {len(video_files)} Video Clips in '{clips_dir}' ---")

    clip_splits_map = load_clip_splits_config()
    ingestion_results = []

    for idx, fname in enumerate(video_files, 1):
        fpath = os.path.join(clips_dir, fname)
        rel_path = fpath.replace("\\", "/")
        clip_id = generate_clip_id(fname)
        player_id, player_name = normalize_player_id(fname)
        camera_view = infer_camera_view(fname)
        
        # Split Assignment Priority: clip_splits.json -> default player split -> "train"
        stem = os.path.splitext(fname)[0].lower()
        if clip_id.lower() in clip_splits_map:
            split = clip_splits_map[clip_id.lower()]
        elif stem in clip_splits_map:
            split = clip_splits_map[stem]
        elif fname.lower() in clip_splits_map:
            split = clip_splits_map[fname.lower()]
        else:
            split = DEFAULT_PLAYER_SPLITS.get(player_id, "train")
            print(f"  [NEW CLIP] '{fname}' not explicitly mapped in clip_splits.json -> assigned to '{split}' by default.")

        # Probe video
        cap = cv2.VideoCapture(fpath)
        if not cap.isOpened():
            print(f"[{idx}/{len(video_files)}] [ERROR] Failed to open {fname}")
            continue

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        file_sha256 = compute_sha256(fpath)

        # Register clip in labeled_clips
        db.register_labeled_clip(
            clip_id=clip_id,
            file_path=rel_path,
            file_sha256=file_sha256,
            player_id=player_id,
            camera_view=camera_view,
            shot_style="jump_shot",
            fps=fps,
            frame_count=total_frames,
            width=w,
            height=h,
            split=split,
            license="private_project",
            notes=f"Auto-ingested from {fname}"
        )

        # Machine Proposal Generation
        existing_proposals = db.get_machine_proposals(clip_id)
        prop_count = len(existing_proposals)

        if generate_proposals and (prop_count == 0 or force_repropose):
            print(f"[{idx:02d}/{len(video_files):02d}] Processing {fname} ({total_frames} frames, {fps:.1f} fps) ...", end="", flush=True)
            t0 = time.time()
            proposals = detect_proposals_for_clip(fpath, fps, total_frames, shot_style="jump_shot", detector_type=detector_type)
            det_name = "calibrated_fsm" if detector_type == "calibrated" else ("ml_sequence_detector" if detector_type == "ml_sequence" else "shot_phase_detector")
            det_version = "1.0.0"
            if proposals:
                db.save_machine_proposals(clip_id, proposals, detector_name=det_name, detector_version=det_version)
            dt = time.time() - t0
            prop_count = len(proposals)
            print(f" Done ({dt:.1f}s, {prop_count} proposals)")
        else:
            print(f"[{idx:02d}/{len(video_files):02d}] Ingested {fname} (Player: {player_id:14s} | Split: {split:5s} | View: {camera_view:10s} | Proposals: {prop_count})")

        ingestion_results.append({
            "clip_id": clip_id,
            "filename": fname,
            "player_id": player_id,
            "split": split,
            "camera_view": camera_view,
            "frames": total_frames,
            "proposals": prop_count
        })

    # 3. Clean up historical misassigned clips in labeled_clips if any
    all_clips = db.list_labeled_clips()
    for c in all_clips:
        c_file = c.get("file_path", "")
        c_fname = os.path.basename(c_file)
        if c_fname:
            expected_p, _ = normalize_player_id(c_fname)
            stem_c = os.path.splitext(c_fname)[0].lower()
            c_id = c["clip_id"].lower()
            if c_id in clip_splits_map:
                expected_split = clip_splits_map[c_id]
            elif stem_c in clip_splits_map:
                expected_split = clip_splits_map[stem_c]
            elif c_fname.lower() in clip_splits_map:
                expected_split = clip_splits_map[c_fname.lower()]
            else:
                expected_split = DEFAULT_PLAYER_SPLITS.get(expected_p, "train")

            if c["player_id"] != expected_p or c["split"] != expected_split:
                db.register_labeled_clip(
                    clip_id=c["clip_id"],
                    file_path=c["file_path"],
                    player_id=expected_p,
                    split=expected_split
                )

    print(f"\n=== Batch Ingestion Completed ({len(ingestion_results)} clips processed) ===")
    return {
        "total_clips": len(ingestion_results),
        "clips": ingestion_results
    }


def main():
    parser = argparse.ArgumentParser(description="Batch Ingestion for Basketball Shot Lab Clips.")
    parser.add_argument("--clips_dir", type=str, default="raw_clips", help="Directory containing raw video clips")
    parser.add_argument("--db_path", type=str, default="shot_lab.db", help="SQLite database path")
    parser.add_argument("--no_proposals", action="store_true", help="Skip running pose detector proposals")
    parser.add_argument("--force_repropose", action="store_true", help="Re-run proposal detection even if proposals exist")
    parser.add_argument("--detector", type=str, choices=["calibrated", "ml_sequence", "heuristic"], default="calibrated", help="Detector model to use for proposals")
    args = parser.parse_args()

    # Ingest
    res = ingest_all_clips(
        clips_dir=args.clips_dir,
        db_path=args.db_path,
        generate_proposals=not args.no_proposals,
        force_repropose=args.force_repropose,
        detector_type=args.detector
    )

    # Validate
    from evaluation.validate_dataset import DatasetValidator
    print("\n--- Running Dataset Validation ---")
    val = DatasetValidator(db=ShotLabDB(args.db_path), split_strategy="clip")
    report = val.validate()
    print(f"Validation Status: {report['status']}")
    print(f"Total Clips in DB: {report['total_clips']}")
    print(f"Split Breakdown:   {report.get('split_distribution')}")
    print(f"Errors:            {len(report['errors'])}")
    print(f"Warnings:          {len(report['warnings'])}")


if __name__ == "__main__":
    main()

