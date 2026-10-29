"""Export image frames around rim crossing for disagreement and unknown outcome attempts.

Saves image sequences and metadata manifests under user_data/hard_frames/<shot_id>/
for visual inspection, re-training, or edge case annotation.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


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


def export_hard_frames(
    db_path: str = "shot_lab.db",
    out_dir: str = "user_data/hard_frames",
    window_frames: int = 30,
    limit: int | None = None,
) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    jobs_db_path = f"{db_path}.web_jobs.sqlite3"
    upload_dir = Path("user_data/uploads").resolve()

    # Disagreements and unknowns on reviewed attempts
    cur.execute(
        """
        SELECT shot_id, session_id, player_id, outcome, review_status,
               automated_outcome, automated_outcome_conf, p_make,
               evidence_quality, outcome_reason, outcome_features,
               machine_release_frame, annotated_release_frame,
               machine_start_frame, annotated_start_frame
        FROM shots
        WHERE review_status = 'approved'
          AND (automated_outcome != outcome OR automated_outcome = 'unknown')
        ORDER BY session_id, shot_id
        """
    )
    hard_shots = cur.fetchall()
    if limit:
        hard_shots = hard_shots[:limit]

    print(f"Found {len(hard_shots)} hard/disagreement shot attempts in {db_path}.")

    session_video_map: Dict[str, Path] = {}
    if Path(jobs_db_path).is_file():
        con_j = sqlite3.connect(jobs_db_path)
        cur_j = con_j.cursor()
        for s in hard_shots:
            sess_id = s["session_id"]
            if sess_id not in session_video_map:
                cur_j.execute("SELECT video_path, replay_path FROM app_jobs WHERE session_id = ?", (sess_id,))
                rows = cur_j.fetchall()
                if rows:
                    resolved = resolve_video_path(rows[0][0], upload_dir) or resolve_video_path(rows[0][1], upload_dir)
                    if resolved:
                        session_video_map[sess_id] = resolved

    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    exported_count = 0

    for shot in hard_shots:
        shot_id = shot["shot_id"]
        sess_id = shot["session_id"]
        vpath = session_video_map.get(sess_id)
        if not vpath or not vpath.is_file():
            continue

        cap = cv2.VideoCapture(str(vpath))
        if not cap.isOpened():
            continue

        total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1000)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)

        rel_f = shot["annotated_release_frame"] or shot["machine_release_frame"] or shot["annotated_start_frame"] or 0
        crossing_approx = int(rel_f + round(fps * 0.75))  # typical flight to rim is ~0.75s
        half_win = window_frames // 2
        start_f = max(0, crossing_approx - half_win)
        stop_f = min(total_vid_frames - 1, crossing_approx + half_win)

        shot_dir = out_root / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)

        frame_files = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        curr_f = start_f
        while curr_f <= stop_f:
            ok, frame = cap.read()
            if not ok:
                break
            frame_name = f"frame_{curr_f:05d}.jpg"
            frame_path = shot_dir / frame_name
            cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            frame_files.append(frame_name)
            curr_f += 1

        cap.release()

        feats = {}
        if shot["outcome_features"]:
            try:
                feats = json.loads(shot["outcome_features"])
            except Exception:
                feats = {}

        manifest = {
            "shot_id": shot_id,
            "session_id": sess_id,
            "player_id": shot["player_id"],
            "human_label": shot["outcome"],
            "machine_outcome": shot["automated_outcome"],
            "p_make": shot["p_make"],
            "evidence_quality": shot["evidence_quality"],
            "outcome_reason": shot["outcome_reason"],
            "release_frame": rel_f,
            "exported_range": [start_f, stop_f],
            "frame_files": frame_files,
            "features": feats,
        }
        with open(shot_dir / "manifest.json", "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)

        exported_count += 1
        print(f"Exported {len(frame_files)} frames for hard attempt {shot_id} -> {shot_dir}")

    print(f"\nDone. Exported {exported_count} hard shot attempts to {out_root}.")
    return exported_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export hard attempt frames around rim crossing.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to shot_lab.db")
    parser.add_argument("--out-dir", default="user_data/hard_frames", help="Output directory")
    parser.add_argument("--window-frames", type=int, default=30, help="Frames to export around crossing")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of attempts")
    args = parser.parse_args()

    export_hard_frames(
        db_path=args.db,
        out_dir=args.out_dir,
        window_frames=args.window_frames,
        limit=args.limit,
    )

