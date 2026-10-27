"""
clean_db_provenance.py - Clean up duplicate clip aliases, consolidate intervals,
and enforce strict split mapping and file SHA256 fingerprints in shot_lab.db.
"""

import os
import sys
import hashlib
import json
import sqlite3
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from scripts.batch_ingest_clips import generate_clip_id, compute_sha256, load_clip_splits_config
except ImportError:
    from batch_ingest_clips import generate_clip_id, compute_sha256, load_clip_splits_config

DB_PATH = "shot_lab.db"

def consolidate_db():
    db = ShotLabDB(DB_PATH)
    splits_map = load_clip_splits_config()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Map physical files in raw_clips
        raw_files = [f for f in os.listdir("raw_clips") if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
        print(f"Found {len(raw_files)} physical video clips in raw_clips/")

        file_to_canonical = {}
        for rf in raw_files:
            rel = os.path.normpath(os.path.join("raw_clips", rf)).replace("\\", "/")
            canon_id = generate_clip_id(rf)
            file_to_canonical[rel.lower()] = (canon_id, rel, os.path.join("raw_clips", rf))

        # Check existing labeled_clips
        c.execute("SELECT * FROM labeled_clips")
        existing_clips = [dict(r) for r in c.fetchall()]

        # Identify aliases
        for clip in existing_clips:
            cid = clip["clip_id"]
            cpath = os.path.normpath(clip["file_path"]).replace("\\", "/").lower()

            if cpath in file_to_canonical:
                canon_id, canon_rel, full_path = file_to_canonical[cpath]
                if cid != canon_id:
                    print(f"Alias detected: '{cid}' -> canonical '{canon_id}' ({cpath})")

                    # Check if canonical clip exists in labeled_clips
                    c.execute("SELECT clip_id FROM labeled_clips WHERE clip_id = ?", (canon_id,))
                    if not c.fetchone():
                        # Promote this clip to canonical ID
                        c.execute("UPDATE labeled_clips SET clip_id = ? WHERE clip_id = ?", (canon_id, cid))
                        c.execute("UPDATE labeled_intervals SET clip_id = ? WHERE clip_id = ?", (canon_id, cid))
                        c.execute("UPDATE machine_proposals SET clip_id = ? WHERE clip_id = ?", (canon_id, cid))
                        cid = canon_id
                    else:
                        # Move intervals from alias to canonical if not already overlapping
                        c.execute("SELECT * FROM labeled_intervals WHERE clip_id = ?", (cid,))
                        alias_intervals = [dict(r) for r in c.fetchall()]
                        c.execute("SELECT start_frame, end_frame FROM labeled_intervals WHERE clip_id = ?", (canon_id,))
                        canon_spans = {(r["start_frame"], r["end_frame"]) for r in c.fetchall()}

                        for intv in alias_intervals:
                            span = (intv["start_frame"], intv["end_frame"])
                            if span not in canon_spans:
                                c.execute("UPDATE labeled_intervals SET clip_id = ? WHERE interval_id = ?", (canon_id, intv["interval_id"]))
                                canon_spans.add(span)
                            else:
                                c.execute("DELETE FROM labeled_intervals WHERE interval_id = ?", (intv["interval_id"],))

                        # Move proposals
                        c.execute("SELECT proposal_id, start_frame, end_frame FROM machine_proposals WHERE clip_id = ?", (canon_id,))
                        canon_prop_spans = {(r["start_frame"], r["end_frame"]) for r in c.fetchall()}
                        c.execute("SELECT * FROM machine_proposals WHERE clip_id = ?", (cid,))
                        alias_props = [dict(r) for r in c.fetchall()]
                        for p in alias_props:
                            span = (p["start_frame"], p["end_frame"])
                            if span not in canon_prop_spans:
                                c.execute("UPDATE machine_proposals SET clip_id = ? WHERE proposal_id = ?", (canon_id, p["proposal_id"]))
                                canon_prop_spans.add(span)
                            else:
                                c.execute("DELETE FROM machine_proposals WHERE proposal_id = ?", (p["proposal_id"],))

                        # Delete alias clip record
                        c.execute("DELETE FROM labeled_clips WHERE clip_id = ?", (cid,))

        conn.commit()

        # 2. Update SHA256 and Splits for all canonical clips
        c.execute("SELECT * FROM labeled_clips")
        remaining_clips = [dict(r) for r in c.fetchall()]
        print(f"\nRemaining canonical clips in labeled_clips: {len(remaining_clips)}")

        for clip in remaining_clips:
            cid = clip["clip_id"]
            cpath = clip["file_path"]
            if os.path.exists(cpath):
                sha = compute_sha256(cpath)
            else:
                alt = os.path.join("raw_clips", os.path.basename(cpath))
                sha = compute_sha256(alt) if os.path.exists(alt) else None

            # Determine split
            stem = os.path.splitext(os.path.basename(cpath))[0].lower()
            split = splits_map.get(cid.lower()) or splits_map.get(stem) or "train"

            c.execute("""
                UPDATE labeled_clips
                SET file_sha256 = ?, split = ?
                WHERE clip_id = ?
            """, (sha, split, cid))

        conn.commit()
        print("Database consolidation completed successfully!")

if __name__ == "__main__":
    consolidate_db()
