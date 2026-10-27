"""
sync_split_annotations.py - Synchronize Expert Ground-Truth Annotations into ShotLabDB.

Reads structured annotations (e.g. ground_truth_annotations.json), verifies video file
integrity, ingests clips and intervals into shot_lab.db with proper split alignment,
and exports updated dataset manifests.
"""

from __future__ import annotations
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from scripts.export_dataset import DatasetExporter
except ImportError:
    from export_dataset import DatasetExporter

try:
    from scripts.batch_ingest_clips import load_clip_splits_config, compute_sha256, normalize_player_id, infer_camera_view
except ImportError:
    from batch_ingest_clips import load_clip_splits_config, compute_sha256, normalize_player_id, infer_camera_view


def sync_annotations_to_db(
    json_path: str = "data/ground_truth_annotations.json" if os.path.exists("data/ground_truth_annotations.json") else "ground_truth_annotations.json",
    db_path: str = "shot_lab.db",
    export_after_sync: bool = True,
    out_dir: str = "dataset_export"
) -> Dict[str, Any]:
    """
    Ingest annotations from json_path into shot_lab.db and optionally re-export splits.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"[FAIL-FAST] Annotation file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = ShotLabDB(db_path)
    splits_cfg = load_clip_splits_config()

    clips = data.get("clips", [])
    synced_clips = 0
    synced_intervals = 0

    for c in clips:
        orig_clip_id = c.get("clip_id", "")
        raw_filename = c.get("file", "")
        video_path = os.path.join("raw_clips", raw_filename) if not os.path.exists(raw_filename) else raw_filename

        if not os.path.exists(video_path):
            raise FileNotFoundError(
                f"[FAIL-FAST] Video file for clip '{orig_clip_id}' does not exist: {video_path}\n"
                f"Please ensure all required clips are placed in the 'raw_clips/' directory."
            )

        meta = c.get("metadata", {})
        player_id = meta.get("player_id") or normalize_player_id(raw_filename)[0]
        camera_view = meta.get("camera_view") or infer_camera_view(raw_filename)
        fps = meta.get("fps", 30.0)

        # Resolve split from clip_splits.json or fallback
        stem = os.path.splitext(os.path.basename(raw_filename))[0].lower()
        split = splits_cfg.get(orig_clip_id.lower()) or splits_cfg.get(stem) or "train"

        file_sha = compute_sha256(video_path)

        # Canonical clip ID
        canonical_clip_id = stem

        # Register clip
        db.register_labeled_clip(
            clip_id=canonical_clip_id,
            file_path=video_path.replace("\\", "/"),
            file_sha256=file_sha,
            player_id=player_id,
            camera_view=camera_view,
            shot_style="jump_shot",
            fps=fps,
            split=split,
            license="private_project",
            notes=f"Synced from {json_path}"
        )
        synced_clips += 1

        # Retrieve existing intervals to ensure idempotence
        existing = db.get_clip_annotations(canonical_clip_id).get("intervals", [])
        existing_spans = {(i["start_frame"], i["end_frame"]) for i in existing}

        shots = c.get("shots", [])
        for s in shots:
            shot_id = s.get("shot_id")
            events = s.get("events", {})
            start_f = events.get("shot_start_frame", 0)
            dip_f = events.get("peak_dip_frame")
            set_f = events.get("set_point_frame")
            rel_f = events.get("release_frame")
            ft_f = events.get("follow_through_frame")
            end_f = ft_f + 10 if ft_f is not None else (rel_f + 20 if rel_f is not None else start_f + 60)

            outcome_meta = s.get("outcome", {})
            raw_res = outcome_meta.get("result", "made").lower()
            outcome = "make" if "make" in raw_res or "made" in raw_res else ("miss" if "miss" in raw_res else "unknown")
            rim_contact = outcome_meta.get("rim_contact", "none")

            if (start_f, end_f) not in existing_spans:
                db.save_labeled_interval(
                    clip_id=canonical_clip_id,
                    interval_type="shot",
                    action_class="shot_event",
                    start_frame=start_f,
                    end_frame=end_f,
                    dip_frame=dip_f,
                    set_frame=set_f,
                    release_frame=rel_f,
                    follow_through_frame=ft_f,
                    outcome=outcome,
                    rim_contact=rim_contact,
                    human_annotator_id="expert_reviewer",
                    review_status="verified",
                    notes=f"Synced shot_id: {shot_id}"
                )
                existing_spans.add((start_f, end_f))
                synced_intervals += 1

    summary = {
        "status": "SUCCESS",
        "json_source": json_path,
        "clips_synced": synced_clips,
        "new_intervals_synced": synced_intervals
    }

    if export_after_sync:
        exporter = DatasetExporter(db=db, split_strategy="clip", out_dir=out_dir, validate_before_export=True)
        export_res = exporter.export()
        summary["export_summary"] = {
            "total_clips": export_res["manifest"]["total_clips"],
            "total_intervals": export_res["manifest"]["total_intervals"],
            "splits": export_res["manifest"]["splits"]
        }

    return summary


def main():
    parser = argparse.ArgumentParser(description="Sync external annotations into ShotLabDB.")
    parser.add_argument("--json-file", default="ground_truth_annotations.json", help="Path to annotations JSON file.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database.")
    parser.add_argument("--no-export", action="store_true", help="Skip dataset export after syncing.")
    args = parser.parse_args()

    try:
        res = sync_annotations_to_db(
            json_path=args.json_file,
            db_path=args.db,
            export_after_sync=not args.no_export
        )
        print("\n" + "=" * 65)
        print(" [SYNC SUCCESS] Ground-Truth Annotations Synchronized")
        print("=" * 65)
        print(f" Source:           {res['json_source']}")
        print(f" Clips Processed:  {res['clips_synced']}")
        print(f" New Intervals:    {res['new_intervals_synced']}")
        if "export_summary" in res:
            es = res["export_summary"]
            print(f" Total Clips in DB:     {es['total_clips']}")
            print(f" Total Intervals in DB: {es['total_intervals']}")
            print(" Split Counts:")
            for sp, sp_meta in es["splits"].items():
                print(f"   - {sp:<6}: {sp_meta['clip_count']} clips, {sp_meta['interval_count']} intervals")
        print("=" * 65 + "\n")
    except Exception as e:
        print(f"\n[ERROR] Sync failed: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
