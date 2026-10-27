"""
inspect_db.py - Quick SQLite Database Inspector for Shot Lab & Model Lab.

Prints formatted tables of:
 1. Registered video clips (labeled_clips)
 2. Machine detector proposals (machine_proposals)
 3. Human ground-truth labeled intervals (labeled_intervals)
 4. Historical player shots & baseline status (shots, baselines)

Usage:
    python inspect_db.py [--db shot_lab.db] [--clip-id lavish_1]
"""

import sys
import argparse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from basketball.persistence.shot_lab_db import ShotLabDB


def inspect_database(db_path="shot_lab.db", clip_id=None):
    db = ShotLabDB(db_path)
    
    print("\n" + "=" * 100)
    print(f"  SHOT LAB DATABASE INSPECTION: {db_path}")
    print("=" * 100)

    # 1. Registered Clips
    clips = db.list_labeled_clips()
    print(f"\n[1] LABELED CLIPS ({len(clips)} total):")
    print("-" * 100)
    print(f"{'Clip ID':<18} | {'Player':<15} | {'Split':<8} | {'View':<12} | {'FPS':<6} | {'Frames':<8} | {'File Path'}")
    print("-" * 100)
    if not clips:
        print("  (No labeled clips registered yet)")
    for c in clips:
        fps_val = c.get('fps')
        fps_str = f"{fps_val:.1f}" if fps_val is not None else "30.0"
        fc_val = c.get('frame_count')
        fc_str = str(fc_val) if fc_val is not None else "0"
        split_str = str(c.get('split') or 'train')
        view_str = str(c.get('camera_view') or '-')
        fpath_str = str(c.get('file_path') or '-')
        print(f"{c['clip_id']:<18} | {c['player_id']:<15} | {split_str:<8} | {view_str:<12} | {fps_str:<6} | {fc_str:<8} | {fpath_str}")

    target_clips = [c for c in clips if c["clip_id"] == clip_id] if clip_id else clips

    # 2. Machine Proposals
    total_props = 0
    print(f"\n[2] MACHINE PROPOSALS (Cyan M-Lane):")
    print("-" * 100)
    print(f"{'Clip ID':<18} | {'Proposal ID':<14} | {'Start..End':<14} | {'Dip':<6} | {'Set':<6} | {'Rel':<6} | {'Conf':<6} | {'Status'}")
    print("-" * 100)
    for c in target_clips:
        cid = c["clip_id"]
        props = db.get_machine_proposals(cid)
        total_props += len(props)
        for p in props:
            span = f"F{p['start_frame']}..F{p['end_frame']}"
            dip = str(p.get("dip_frame") or "-")
            set_f = str(p.get("set_frame") or "-")
            rel = str(p.get("release_frame") or "-")
            conf_val = p.get('confidence')
            conf = f"{conf_val:.2f}" if conf_val is not None else "1.00"
            status = (p.get("status") or "proposed").upper()
            print(f"{cid:<18} | {p['proposal_id']:<14} | {span:<14} | {dip:<6} | {set_f:<6} | {rel:<6} | {conf:<6} | {status}")
    if total_props == 0:
        print("  (No machine proposals found)")

    # 3. Human Ground-Truth Intervals
    total_intvs = 0
    print(f"\n[3] HUMAN LABELED INTERVALS (Amber H-Lane):")
    print("-" * 100)
    print(f"{'Clip ID':<18} | {'Interval ID':<14} | {'Type':<10} | {'Action Class':<18} | {'Start..End':<14} | {'Dip->Rel':<12} | {'Outcome'}")
    print("-" * 100)
    for c in target_clips:
        cid = c["clip_id"]
        ann = db.get_clip_annotations(cid)
        intvs = ann.get("intervals", [])
        total_intvs += len(intvs)
        for i in intvs:
            span = f"F{i['start_frame']}..F{i['end_frame']}"
            dip = i.get("dip_frame")
            rel = i.get("release_frame")
            dip_rel = f"F{dip}->F{rel}" if dip is not None and rel is not None else "-"
            outcome = (i.get("outcome") or "-").upper()
            itype = i.get("interval_type", "shot")
            act = i.get("action_class", "shot_event")
            print(f"{cid:<18} | {i['interval_id']:<14} | {itype:<10} | {act:<18} | {span:<14} | {dip_rel:<12} | {outcome}")
    if total_intvs == 0:
        print("  (No human intervals committed yet)")

    print("\n" + "=" * 100 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Inspect Shot Lab SQLite database tables and records.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database.")
    parser.add_argument("--clip-id", help="Filter inspection to a specific clip_id.")
    args = parser.parse_args()

    inspect_database(db_path=args.db, clip_id=args.clip_id)


if __name__ == "__main__":
    main()
