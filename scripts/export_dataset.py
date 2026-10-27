"""
export_dataset.py - Manifest-Driven Exporter for Developer Model Lab.

Exports labeled dataset splits (train.jsonl, val.jsonl, test.jsonl) along with
a top-level DATASET_MANIFEST.json containing SHA256 checksums, taxonomy distributions,
and license provenance per AGENTS.md requirements.
"""

from __future__ import annotations
import os
import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.persistence.shot_lab_db import ShotLabDB, TAXONOMY_ALL_ACTIONS
from evaluation.validate_dataset import DatasetValidator


def compute_file_sha256(filepath: str) -> Optional[str]:
    """Compute hex SHA256 checksum for a local file if it exists."""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_string_sha256(content: str) -> str:
    """Compute hex SHA256 checksum of string content encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DatasetExporter:
    """Exports clips, machine proposals, and human intervals to JSONL splits with manifest."""

    def __init__(
        self,
        db: Optional[ShotLabDB] = None,
        out_dir: str = "dataset_export",
        is_synthetic: bool = False,
        force: bool = False,
        validate_before_export: bool = True,
        split_strategy: str = "player"
    ):
        self.db = db or ShotLabDB()
        self.out_dir = out_dir
        self.is_synthetic = is_synthetic
        self.force = force
        self.validate_before_export = validate_before_export
        self.split_strategy = split_strategy

    def export(self) -> Dict[str, Any]:
        """Execute the export workflow.

        Returns:
            Dictionary containing export summary and manifest details.
        """
        # Step 1: Validation gate
        if self.validate_before_export:
            validator = DatasetValidator(
                db=self.db,
                check_file_existence=not self.is_synthetic,
                split_strategy=self.split_strategy
            )
            report = validator.validate()
            if report.get("status") != "PASSED" and not self.force:
                raise ValueError(
                    f"Dataset validation failed with {len(report.get('errors', []))} error(s). "
                    f"Run validate_dataset.py for details or pass --force to bypass. Errors: {report.get('errors')}"
                )

        os.makedirs(self.out_dir, exist_ok=True)

        clips = self.db.list_labeled_clips()
        if not clips and not self.force:
            raise ValueError("No labeled clips found to export.")

        # Organize by split
        splits_data: Dict[str, List[Dict[str, Any]]] = {
            "train": [],
            "val": [],
            "test": []
        }

        action_counts: Dict[str, int] = {act: 0 for act in TAXONOMY_ALL_ACTIONS}
        outcome_counts: Dict[str, int] = {"make": 0, "miss": 0, "unknown": 0, "none": 0}
        player_split_map: Dict[str, List[str]] = {"train": [], "val": [], "test": []}
        referenced_files: List[Dict[str, Any]] = []

        total_intervals = 0

        for clip in clips:
            c_id = clip["clip_id"]
            split = clip.get("split", "train").lower()
            if split not in splits_data:
                splits_data[split] = []
                player_split_map[split] = []

            player_id = clip.get("player_id", "unknown")
            if player_id not in player_split_map[split]:
                player_split_map[split].append(player_id)

            file_path = clip.get("file_path", "")
            sha256_hash = clip.get("file_sha256")
            if not sha256_hash and file_path and os.path.exists(file_path):
                sha256_hash = compute_file_sha256(file_path)

            referenced_files.append({
                "clip_id": c_id,
                "file_path": file_path,
                "file_sha256": sha256_hash
            })

            # Fetch machine proposals and human intervals
            ann = self.db.get_clip_annotations(c_id)
            proposals = ann.get("proposals", [])
            intervals = ann.get("intervals", [])
            total_intervals += len(intervals)

            for intv in intervals:
                act = intv.get("action_class", "shot_event")
                out = (intv.get("outcome") or "unknown").lower()
                action_counts[act] = action_counts.get(act, 0) + 1
                outcome_counts[out] = outcome_counts.get(out, 0) + 1

            record = {
                "clip_id": c_id,
                "file_path": file_path,
                "file_sha256": sha256_hash,
                "player_id": player_id,
                "camera_view": clip.get("camera_view"),
                "shot_style": clip.get("shot_style", "jump_shot"),
                "fps": clip.get("fps", 30.0),
                "frame_count": clip.get("frame_count"),
                "width": clip.get("width"),
                "height": clip.get("height"),
                "split": split,
                "license": clip.get("license", "private_project"),
                "notes": clip.get("notes"),
                "machine_proposals": proposals,
                "human_intervals": intervals
            }
            splits_data[split].append(record)

        # Write split JSONL files and compute checksums
        split_manifest_meta: Dict[str, Any] = {}
        for split_name, records in splits_data.items():
            split_filename = f"{split_name}.jsonl"
            split_filepath = os.path.join(self.out_dir, split_filename)

            lines = [json.dumps(r) for r in records]
            content = "\n".join(lines) + ("\n" if lines else "")

            with open(split_filepath, "w", encoding="utf-8") as f:
                f.write(content)

            split_sha256 = compute_string_sha256(content)
            split_int_count = sum(len(r["human_intervals"]) for r in records)

            split_manifest_meta[split_name] = {
                "file": split_filename,
                "sha256": split_sha256,
                "clip_count": len(records),
                "interval_count": split_int_count
            }

        # Build DATASET_MANIFEST.json
        manifest = {
            "manifest_version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "synthetic": self.is_synthetic,
            "total_clips": len(clips),
            "total_intervals": total_intervals,
            "splits": split_manifest_meta,
            "taxonomy": {
                "action_classes": action_counts,
                "outcomes": outcome_counts
            },
            "player_split_mapping": player_split_map,
            "referenced_files": referenced_files
        }

        manifest_path = os.path.join(self.out_dir, "DATASET_MANIFEST.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return {
            "status": "SUCCESS",
            "out_dir": self.out_dir,
            "manifest_path": manifest_path,
            "manifest": manifest
        }


def main():
    parser = argparse.ArgumentParser(description="Export Developer Model Lab dataset splits and manifest.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database.")
    parser.add_argument("--out-dir", default="dataset_export", help="Output directory for JSONL splits and manifest.")
    parser.add_argument("--strategy", choices=["clip", "player"], default="clip", help="Split validation strategy (clip or player).")
    parser.add_argument("--synthetic", action="store_true", help="Explicitly flag dataset as synthetic test fixtures.")
    parser.add_argument("--force", action="store_true", help="Bypass validation failures and export anyway.")
    parser.add_argument("--no-validate", action="store_true", help="Skip pre-export validation check.")
    args = parser.parse_args()

    db = ShotLabDB(args.db)
    exporter = DatasetExporter(
        db=db,
        out_dir=args.out_dir,
        is_synthetic=args.synthetic,
        force=args.force,
        validate_before_export=not args.no_validate,
        split_strategy=args.strategy
    )

    try:
        res = exporter.export()
        print(f"Export completed successfully to '{res['out_dir']}'.")
        print(f"Manifest written to: {res['manifest_path']}")
        print(f"Total clips: {res['manifest']['total_clips']} | Total intervals: {res['manifest']['total_intervals']}")
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
