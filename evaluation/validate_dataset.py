"""
validate_dataset.py - Automated Dataset QA & Integrity Validator for Developer Model Lab.

Enforces:
 1. Temporal bounds: 0 <= start <= end < frame_count.
 2. Chronological shot ordering: start <= dip <= set <= release <= follow_through <= end.
 3. Taxonomy adherence: action_class in TAXONOMY_ALL_ACTIONS (shot_event + 8 hard negatives).
 4. Outcome coherence: shots have make/miss/unknown; negatives have none/unknown.
 5. Split leakage prevention: Set(Players_train) intersection Set(Players_test) is empty.
 6. AGENTS.md missing-file integrity: raises actionable missing path error if video is missing.
 7. Overlapping interval detection.
"""

from __future__ import annotations
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.persistence.shot_lab_db import ShotLabDB, TAXONOMY_HARD_NEGATIVES, TAXONOMY_ALL_ACTIONS

class DatasetValidator:
    def __init__(
        self,
        db: Optional[ShotLabDB] = None,
        check_file_existence: bool = True,
        split_strategy: str = "player"
    ):
        self.db = db or ShotLabDB()
        self.check_file_existence = check_file_existence
        self.split_strategy = split_strategy.lower()

    def validate(self) -> Dict[str, Any]:
        """Run all integrity checks and return structured validation report."""
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        clips = self.db.list_labeled_clips()
        if not clips:
            return {
                "status": "FAILED",
                "message": "No labeled clips found in database.",
                "total_clips": 0,
                "total_intervals": 0,
                "errors": [{"code": "ERR_EMPTY_DATASET", "message": "Database contains 0 labeled clips."}],
                "warnings": []
            }

        player_to_splits: Dict[str, Set[str]] = {}
        split_counts: Dict[str, int] = {"train": 0, "val": 0, "test": 0, "other": 0}
        class_counts: Dict[str, int] = {c: 0 for c in TAXONOMY_ALL_ACTIONS}
        outcome_counts: Dict[str, int] = {"make": 0, "miss": 0, "unknown": 0, "none": 0}
        total_intervals = 0
        total_shots = 0
        total_negatives = 0

        for clip in clips:
            c_id = clip["clip_id"]
            player_id = clip["player_id"]
            split = clip.get("split", "train").lower()
            split_counts[split if split in split_counts else "other"] += 1
            frame_count = clip.get("frame_count")
            file_path = clip.get("file_path", "")

            # 1. Track player to split mapping for leakage check
            if player_id not in player_to_splits:
                player_to_splits[player_id] = set()
            player_to_splits[player_id].add(split)

            # 2. Check local video file accessibility (AGENTS.md rule)
            if self.check_file_existence:
                if not file_path or not os.path.exists(file_path):
                    errors.append({
                        "code": "ERR_MISSING_VIDEO",
                        "clip_id": c_id,
                        "file_path": file_path,
                        "message": (
                            f"Referenced video file '{file_path}' for clip '{c_id}' is missing or inaccessible. "
                            f"Per AGENTS.md data integrity rules: stop dependent work. "
                            f"Please place video footage at: '{os.path.abspath(file_path)}'"
                        )
                    })

            # 3. Check intervals for this clip
            annotations = self.db.get_clip_annotations(c_id)
            intervals = annotations.get("intervals", [])
            total_intervals += len(intervals)

            # Check for overlapping intervals
            sorted_intervals = sorted(intervals, key=lambda x: x["start_frame"])
            for i in range(len(sorted_intervals) - 1):
                cur = sorted_intervals[i]
                nxt = sorted_intervals[i + 1]
                if cur["end_frame"] >= nxt["start_frame"]:
                    warnings.append({
                        "code": "WARN_OVERLAPPING_INTERVALS",
                        "clip_id": c_id,
                        "interval_1": cur["interval_id"],
                        "interval_2": nxt["interval_id"],
                        "message": (
                            f"Intervals '{cur['interval_id']}' [{cur['start_frame']}..{cur['end_frame']}] and "
                            f"'{nxt['interval_id']}' [{nxt['start_frame']}..{nxt['end_frame']}] overlap in clip '{c_id}'."
                        )
                    })

            for intv in intervals:
                int_id = intv["interval_id"]
                int_type = intv.get("interval_type", "shot")
                act_class = intv.get("action_class", "shot_event")
                start = intv.get("start_frame")
                end = intv.get("end_frame")
                outcome = (intv.get("outcome") or "unknown").lower()

                if act_class in class_counts:
                    class_counts[act_class] += 1
                if outcome in outcome_counts:
                    outcome_counts[outcome] += 1

                if int_type == "shot":
                    total_shots += 1
                else:
                    total_negatives += 1

                # Taxonomy adherence
                if act_class not in TAXONOMY_ALL_ACTIONS:
                    errors.append({
                        "code": "ERR_TAXONOMY",
                        "clip_id": c_id,
                        "interval_id": int_id,
                        "message": f"Action class '{act_class}' not in recognized taxonomy ({TAXONOMY_ALL_ACTIONS})."
                    })

                # Temporal bounds
                if start is None or end is None:
                    errors.append({
                        "code": "ERR_BOUNDS",
                        "clip_id": c_id,
                        "interval_id": int_id,
                        "message": "Interval missing start_frame or end_frame."
                    })
                    continue

                if start < 0:
                    errors.append({
                        "code": "ERR_BOUNDS",
                        "clip_id": c_id,
                        "interval_id": int_id,
                        "message": f"Start frame {start} cannot be negative."
                    })

                if start > end:
                    errors.append({
                        "code": "ERR_TEMPORAL_ORDER",
                        "clip_id": c_id,
                        "interval_id": int_id,
                        "message": f"Start frame {start} exceeds end frame {end}."
                    })

                if frame_count is not None and frame_count > 0:
                    if end >= frame_count:
                        errors.append({
                            "code": "ERR_BOUNDS",
                            "clip_id": c_id,
                            "interval_id": int_id,
                            "message": f"End frame {end} exceeds video total frame count {frame_count}."
                        })

                # Shot-specific chronology & outcome coherence
                if int_type == "shot":
                    dip = intv.get("dip_frame")
                    set_p = intv.get("set_frame")
                    rel = intv.get("release_frame")
                    ft = intv.get("follow_through_frame")

                    # Ordering checks where frames are specified
                    frames_seq = [("start", start)]
                    if dip is not None:
                        frames_seq.append(("dip", dip))
                    if set_p is not None:
                        frames_seq.append(("set", set_p))
                    if rel is not None:
                        frames_seq.append(("release", rel))
                    if ft is not None:
                        frames_seq.append(("follow_through", ft))
                    frames_seq.append(("end", end))

                    for idx in range(len(frames_seq) - 1):
                        name1, f1 = frames_seq[idx]
                        name2, f2 = frames_seq[idx + 1]
                        if f1 > f2:
                            errors.append({
                                "code": "ERR_TEMPORAL_ORDER",
                                "clip_id": c_id,
                                "interval_id": int_id,
                                "message": f"Shot event {name1} frame ({f1}) occurs after {name2} frame ({f2})."
                            })

                    if outcome not in ("make", "miss", "unknown"):
                        errors.append({
                            "code": "ERR_OUTCOME_COHERENCE",
                            "clip_id": c_id,
                            "interval_id": int_id,
                            "message": f"Shot interval outcome must be 'make', 'miss', or 'unknown', got '{outcome}'."
                        })
                else:
                    # Hard negative outcome check
                    if outcome not in ("none", "unknown"):
                        errors.append({
                            "code": "ERR_OUTCOME_COHERENCE",
                            "clip_id": c_id,
                            "interval_id": int_id,
                            "message": f"Hard negative interval cannot have shot outcome '{outcome}' (must be 'none' or 'unknown')."
                        })

        # 4. Check split leakage across train / val / test
        if self.split_strategy == "player":
            for player, splits in player_to_splits.items():
                if "train" in splits and "test" in splits:
                    errors.append({
                        "code": "ERR_SPLIT_LEAKAGE",
                        "player_id": player,
                        "splits": list(splits),
                        "message": f"Split leakage detected: Player '{player}' appears in both 'train' and 'test' splits."
                    })
                if "val" in splits and "test" in splits:
                    errors.append({
                        "code": "ERR_SPLIT_LEAKAGE",
                        "player_id": player,
                        "splits": list(splits),
                        "message": f"Split leakage detected: Player '{player}' appears in both 'val' and 'test' splits."
                    })
        else:
            # Clip-level / session-separated strategy: ensure no physical file is assigned to multiple splits
            file_path_to_splits: Dict[str, Set[str]] = {}
            sha_to_splits: Dict[str, Set[str]] = {}
            for clip in clips:
                sp = clip.get("split", "train").lower()
                raw_path = clip.get("file_path", "")
                if raw_path:
                    norm_p = os.path.normpath(raw_path).replace("\\", "/").lower()
                    if norm_p not in file_path_to_splits:
                        file_path_to_splits[norm_p] = set()
                    file_path_to_splits[norm_p].add(sp)

                sha = clip.get("file_sha256")
                if sha:
                    if sha not in sha_to_splits:
                        sha_to_splits[sha] = set()
                    sha_to_splits[sha].add(sp)

            for pkey, splits in file_path_to_splits.items():
                if len(splits) > 1:
                    errors.append({
                        "code": "ERR_SPLIT_LEAKAGE",
                        "file_key": pkey,
                        "splits": list(splits),
                        "message": f"Split leakage detected: Physical video file '{pkey}' assigned to multiple splits ({splits})."
                    })

            for skey, splits in sha_to_splits.items():
                if len(splits) > 1:
                    errors.append({
                        "code": "ERR_SPLIT_LEAKAGE",
                        "file_key": skey[:16],
                        "splits": list(splits),
                        "message": f"Split leakage detected: File SHA '{skey[:16]}' assigned to multiple splits ({splits})."
                    })

            for player, splits in player_to_splits.items():
                if len(splits) > 1:
                    warnings.append({
                        "code": "WARN_INTRA_PLAYER_SPLIT",
                        "player_id": player,
                        "splits": list(splits),
                        "message": f"Player '{player}' has separate video sessions across splits ({splits}) - valid session-separated split."
                    })

        status = "PASSED" if len(errors) == 0 else "FAILED"
        return {
            "status": status,
            "total_clips": len(clips),
            "total_intervals": total_intervals,
            "total_shots": total_shots,
            "total_negatives": total_negatives,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "split_distribution": split_counts,
            "class_distribution": class_counts,
            "outcome_distribution": outcome_counts,
            "player_splits": {p: list(s) for p, s in player_to_splits.items()}
        }

def print_validation_report(report: Dict[str, Any]) -> None:
    """Print readable console summary of QA validation report."""
    print("\n" + "=" * 70)
    print("      DEVELOPER MODEL LAB - DATASET QA & INTEGRITY REPORT")
    print("=" * 70)
    print(f" Status:           {report['status']}")
    print(f" Total Clips:      {report['total_clips']}")
    print(f" Total Intervals:  {report['total_intervals']} (Shots: {report['total_shots']}, Negatives: {report['total_negatives']})")
    print(f" Errors:           {report['error_count']}")
    print(f" Warnings:         {report['warning_count']}")
    print("-" * 70)
    print(" Split Distribution:    ", report.get("split_distribution", {}))
    print(" Action Class Counts:   ", {k: v for k, v in report.get("class_distribution", {}).items() if v > 0})
    print(" Outcome Counts:        ", report.get("outcome_distribution", {}))
    print("-" * 70)

    if report["errors"]:
        print("\n [ERRORS FOUND]:")
        for e in report["errors"]:
            print(f"  * [{e['code']}] {e['message']}")

    if report["warnings"]:
        print("\n [WARNINGS]:")
        for w in report["warnings"]:
            print(f"  * [{w['code']}] {w['message']}")

    print("=" * 70 + "\n")

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate dataset annotations and integrity.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database")
    parser.add_argument("--strategy", choices=["clip", "player"], default="clip", help="Split validation strategy: 'clip' (session-separated) or 'player' (strict player holdout)")
    parser.add_argument("--skip-file-check", action="store_true", help="Skip checking if video files exist on disk")
    parser.add_argument("--json-report", default=None, help="Save report to JSON file")
    args = parser.parse_args(argv)

    db = ShotLabDB(args.db)
    validator = DatasetValidator(db, check_file_existence=not args.skip_file_check, split_strategy=args.strategy)
    report = validator.validate()
    print_validation_report(report)

    if args.json_report:
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[INFO] Report written to: {args.json_report}")

    return 0 if report["status"] == "PASSED" else 1

if __name__ == "__main__":
    sys.exit(main())
