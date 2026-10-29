"""Export calibration dataset joining reviewed attempts' estimator features with human M/X labels.

Excludes unknown (U) labels. Keeps session_id and player_id for grouped cross-validation.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def export_calibration_data(
    db_path: str = "shot_lab.db",
    output_path: str = "user_data/calibration_data.json",
) -> List[Dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        """
        SELECT shot_id, session_id, player_id, camera_view, shot_type, shot_style,
               outcome, review_status, outcome_source,
               automated_outcome, automated_outcome_conf, p_make,
               outcome_confidence, evidence_quality, outcome_reason,
               outcome_features, estimator_version, estimator_cfg_hash
        FROM shots
        WHERE review_status = 'approved' AND outcome IN ('make', 'miss')
        ORDER BY session_id, shot_id
        """
    )
    rows = cur.fetchall()

    records: List[Dict[str, Any]] = []
    make_count = 0
    miss_count = 0
    sessions = set()

    for r in rows:
        feats_str = r["outcome_features"]
        feats = {}
        if feats_str:
            try:
                feats = json.loads(feats_str)
            except Exception:
                feats = {}

        label = r["outcome"]
        if label == "make":
            make_count += 1
        elif label == "miss":
            miss_count += 1
        sessions.add(r["session_id"])

        record = {
            "shot_id": r["shot_id"],
            "session_id": r["session_id"],
            "player_id": r["player_id"],
            "camera_view": r["camera_view"],
            "shot_type": r["shot_type"],
            "shot_style": r["shot_style"],
            "label": label,
            "automated_outcome": r["automated_outcome"],
            "p_make": r["p_make"],
            "confidence": r["outcome_confidence"] or r["automated_outcome_conf"],
            "evidence_quality": r["evidence_quality"],
            "reason": r["outcome_reason"],
            "features": feats,
            "estimator_version": r["estimator_version"],
            "estimator_cfg_hash": r["estimator_cfg_hash"],
        }
        records.append(record)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(
        f"Exported {len(records)} reviewed attempts ({make_count} makes, {miss_count} misses) "
        f"across {len(sessions)} sessions to {output_path}."
    )
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export calibration dataset from reviewed shots.")
    parser.add_argument("--db", default="shot_lab.db", help="Path to shot_lab.db")
    parser.add_argument("--output", default="user_data/calibration_data.json", help="Output JSON path")
    args = parser.parse_args()

    export_calibration_data(db_path=args.db, output_path=args.output)

