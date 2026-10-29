"""Compare YOLO models (e.g. models/best.pt vs models/ballRim.pt) on reviewed clips.

Measures ball and rim detection rates, mean confidence scores, rim anchor stability,
and processing FPS on clips with human-approved make/miss labels.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

import cv2
import numpy as np

# Add src to python path if not present
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basketball.tracking.ball_tracker import BallTracker
from basketball.tracking.outcome_estimator import consensus_rim


def resolve_video_path(stored_path: str | None, upload_dir: Path) -> Path | None:
    if not stored_path:
        return None
    p = Path(stored_path)
    if p.is_file():
        return p
    local_p = upload_dir / p.name
    if local_p.is_file():
        return local_p
    return None


def run_model_comparison(
    db_path: str = "shot_lab.db",
    models: List[str] | None = None,
    limit_clips: int | None = None,
    frames_per_clip: int = 120,
) -> None:
    if models is None:
        models = ["models/best.pt", "models/ballRim.pt"]

    upload_dir = Path("user_data/uploads").resolve()
    jobs_db_path = f"{db_path}.web_jobs.sqlite3"

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT shot_id, session_id, player_id, outcome, machine_release_frame, annotated_release_frame
        FROM shots
        WHERE review_status = 'approved' AND outcome IN ('make', 'miss')
        """
    )
    shots = cur.fetchall()
    total_reviewed = len(shots)

    print(f"Loaded {total_reviewed} human-reviewed attempts (make/miss) from {db_path}.")
    if total_reviewed < 50:
        print(
            f"NOTICE: Reviewed attempts count ({total_reviewed}) is under 50. "
            "Results are strictly anecdotal and cannot be considered a statistically significant benchmark."
        )

    # Find unique sessions and their video files
    session_map: Dict[str, Path] = {}
    if Path(jobs_db_path).is_file():
        con_j = sqlite3.connect(jobs_db_path)
        cur_j = con_j.cursor()
        for shot in shots:
            sess_id = shot[1]
            if sess_id not in session_map:
                cur_j.execute("SELECT video_path, replay_path FROM app_jobs WHERE session_id = ?", (sess_id,))
                rows = cur_j.fetchall()
                if rows:
                    resolved = resolve_video_path(rows[0][0], upload_dir) or resolve_video_path(rows[0][1], upload_dir)
                    if resolved:
                        session_map[sess_id] = resolved

    available_clips = list(session_map.items())
    if limit_clips:
        available_clips = available_clips[:limit_clips]

    print(f"Found {len(available_clips)} video clips available on disk for evaluation.\n")

    results: List[Dict[str, Any]] = []

    for model_path in models:
        if not Path(model_path).is_file():
            print(f"Skipping {model_path}: weights file not found.")
            continue

        print(f"Evaluating {model_path}...")
        try:
            tracker = BallTracker(weights_path=model_path, conf=0.25, detect_every=1)
        except Exception as exc:
            print(f"Failed to load {model_path}: {exc}")
            continue

        total_frames = 0
        ball_detected_frames = 0
        rim_detected_frames = 0
        ball_confs: List[float] = []
        rim_confs: List[float] = []
        all_rim_dets: List[tuple] = []
        start_time = time.perf_counter()

        for sess_id, vpath in available_clips:
            cap = cv2.VideoCapture(str(vpath))
            if not cap.isOpened():
                continue

            frame_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
            frame_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
            clip_frames = 0

            while clip_frames < frames_per_clip:
                ok, frame = cap.read()
                if not ok:
                    break
                clip_frames += 1
                total_frames += 1

                det = tracker.detect(frame)
                b = det.get("ball")
                r = det.get("rim")
                bc = float(det.get("ball_conf", 0.0) or 0.0)
                rc = float(det.get("rim_conf", 0.0) or 0.0)

                if b is not None and bc >= 0.25:
                    ball_detected_frames += 1
                    ball_confs.append(bc)

                if r is not None and rc >= 0.25:
                    rim_detected_frames += 1
                    rim_confs.append(rc)
                    cx = (r[0] + r[2]) / 2.0
                    cy = (r[1] + r[3]) / 2.0
                    w = r[2] - r[0]
                    h = r[3] - r[1]
                    all_rim_dets.append((cx, cy, w, h, rc))

            cap.release()

        elapsed = time.perf_counter() - start_time
        fps = total_frames / max(0.001, elapsed)
        ball_rate = (ball_detected_frames / max(1, total_frames)) * 100.0
        rim_rate = (rim_detected_frames / max(1, total_frames)) * 100.0
        ball_mean_conf = float(np.mean(ball_confs)) if ball_confs else 0.0
        rim_mean_conf = float(np.mean(rim_confs)) if rim_confs else 0.0

        anchor = consensus_rim(all_rim_dets, frame_w, frame_h) if all_rim_dets else None
        rim_stability = anchor.stability if anchor else 9.99

        results.append({
            "model": Path(model_path).name,
            "ball_rate": ball_rate,
            "rim_rate": rim_rate,
            "ball_mean_conf": ball_mean_conf,
            "rim_mean_conf": rim_mean_conf,
            "rim_stability": rim_stability,
            "fps": fps,
        })

    print("\n" + "=" * 90)
    print(f"| {'Model':<20} | {'Ball Det %':<10} | {'Rim Det %':<10} | {'Ball Mean Conf':<14} | {'Rim Mean Conf':<13} | {'Rim Stability':<13} | {'FPS':<6} |")
    print("|" + "-" * 22 + "|" + "-" * 12 + "|" + "-" * 12 + "|" + "-" * 16 + "|" + "-" * 15 + "|" + "-" * 15 + "|" + "-" * 8 + "|")
    for r in results:
        stab_str = f"{r['rim_stability']:.3f}" if r["rim_stability"] < 9.0 else "None"
        print(f"| {r['model']:<20} | {r['ball_rate']:>9.1f}% | {r['rim_rate']:>9.1f}% | {r['ball_mean_conf']:>14.2f} | {r['rim_mean_conf']:>13.2f} | {stab_str:>13} | {r['fps']:>6.1f} |")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare YOLO models on reviewed clips.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to shot_lab.db")
    parser.add_argument("--models", nargs="+", default=["models/best.pt", "models/ballRim.pt"], help="Model paths")
    parser.add_argument("--limit-clips", type=int, default=None, help="Limit number of clips")
    parser.add_argument("--frames-per-clip", type=int, default=60, help="Frames to evaluate per clip")
    args = parser.parse_args()

    run_model_comparison(
        db_path=args.db,
        models=args.models,
        limit_clips=args.limit_clips,
        frames_per_clip=args.frames_per_clip,
    )
