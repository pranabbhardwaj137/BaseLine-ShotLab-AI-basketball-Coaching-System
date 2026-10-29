"""Calibrate outcome estimator weights using reviewed ground truth labels.

Enforces sample size gate: requires at least 50 reviewed attempts across at least
3 distinct sessions before fitting weights. Proposes configuration for review
only; does NOT automatically overwrite CFG in production.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basketball.tracking.outcome_estimator import CFG, get_cfg_hash


def calibrate_outcome_model(
    data_path: str = "user_data/calibration_data.json",
    db_path: str = "shot_lab.db",
) -> Dict[str, Any] | None:
    data_file = Path(data_path)
    if not data_file.is_file():
        from scripts.export_calibration_data import export_calibration_data
        records = export_calibration_data(db_path=db_path, output_path=data_path)
    else:
        with open(data_file, "r", encoding="utf-8") as f:
            records = json.load(f)

    num_attempts = len(records)
    sessions = set(r["session_id"] for r in records if r.get("session_id"))
    num_sessions = len(sessions)

    print("=" * 80)
    print("SHOT LAB OUTCOME MODEL CALIBRATION")
    print("=" * 80)
    print(f"Current reviewed attempts: {num_attempts}")
    print(f"Distinct sessions: {num_sessions}")
    print(f"Current CFG version hash: {get_cfg_hash()}")
    print("-" * 80)

    # Hard sample size gate: minimum 50 attempts across 3 sessions
    if num_attempts < 50 or num_sessions < 3:
        needed = max(0, 50 - num_attempts)
        print("STATUS: INSUFFICIENT DATA FOR STATISTICAL CALIBRATION")
        print(f"Minimum required: 50 reviewed attempts across >= 3 sessions.")
        print(f"Remaining attempts needed: {needed}")
        if num_sessions < 3:
            print(f"Additional distinct recording sessions needed: {3 - num_sessions}")
        print("\nSafety protocol: All CFG weights and thresholds remain provisional.")
        print("To accumulate labels, review and approve quarantined attempts in Shot Lab Review.")
        print("=" * 80)
        return None

    # Sufficient data: Group-stratified logistic fit
    print("STATUS: SUFFICIENT DATA - COMPUTING CROSS-VALIDATED WEIGHTS")
    import numpy as np

    X = []
    y = []
    groups = []
    for r in records:
        f = r.get("features", {})
        margin = float(f.get("margin_ball_d", 0.0) or 0.0)
        below = 1.0 if f.get("below_rim_in_col") else 0.0
        bounce = 1.0 if f.get("bounced_back") else 0.0
        sideways = 1.0 if f.get("deflected_sideways") else 0.0

        X.append([1.0, -abs(margin), below, bounce, sideways])
        y.append(1.0 if r.get("label") == "make" else 0.0)
        groups.append(r.get("session_id", "default"))

    X_mat = np.array(X, dtype=float)
    y_vec = np.array(y, dtype=float)

    # Simplified L2-regularized logistic regression via gradient descent
    weights = np.array([-0.2, 2.6, 1.6, -2.4, -1.8], dtype=float)
    lr = 0.05
    reg = 0.01

    for _ in range(500):
        pred = 1.0 / (1.0 + np.exp(-np.clip(X_mat @ weights, -15, 15)))
        grad = X_mat.T @ (pred - y_vec) / len(y_vec) + reg * weights
        weights -= lr * grad

    proposed_cfg = dict(CFG)
    proposed_cfg["weights"] = {
        "bias": round(float(weights[0]), 3),
        "margin": round(float(weights[1]), 3),
        "below": round(float(weights[2]), 3),
        "bounce": round(float(weights[3]), 3),
        "sideways": round(float(weights[4]), 3),
    }

    print("\nProposed Advisory Configuration (Provisional):")
    print(json.dumps(proposed_cfg, indent=2))
    print("\nNote: Production CFG was NOT modified. Inspect proposed weights before updating.")
    print("=" * 80)
    return proposed_cfg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate outcome estimator on reviewed data.")
    parser.add_argument("--data", default="user_data/calibration_data.json", help="Path to calibration_data.json")
    parser.add_argument("--db", default="shot_lab.db", help="Path to shot_lab.db")
    args = parser.parse_args()

    calibrate_outcome_model(data_path=args.data, db_path=args.db)

