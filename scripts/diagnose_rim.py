"""Comprehensive rim detection diagnosis across all cached sessions.

Analyzes raw YOLO rim detections vs consensus_rim filters to identify
why rim detection dropped to 0% and verify that the production consensus_rim
now successfully resolves anchors across user clips.
"""

from __future__ import annotations

import glob
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basketball.tracking.outcome_estimator import consensus_rim


def strict_consensus_rim_baseline(dets, frame_w, frame_h, min_conf=0.5, min_votes=5):
    """Old strict filters that rejected ~53% of genuine rim detections."""
    cand = []
    for cx, cy, w, h, conf in dets:
        if conf < min_conf or h <= 0:
            continue
        if not (1.1 <= w / h <= 3.0):
            continue
        if w > 0.25 * frame_w:
            continue
        if cy - h / 2 < 0.01 * frame_h:
            continue
        cand.append((cx, cy, w, h))
    if len(cand) < min_votes:
        return None

    a = np.asarray(cand, float)
    r = 0.5 * float(np.median(a[:, 2]))
    d = np.linalg.norm(a[:, None, :2] - a[None, :, :2], axis=2)
    votes = (d < r).sum(axis=1)
    seed = int(np.argmax(votes))
    if votes[seed] < min_votes:
        return None
    cluster = a[d[seed] < r]
    cx, cy, w, _ = np.median(cluster, axis=0)
    stability = float(np.std(cluster[:, :2], axis=0).max() / w)
    return (cx, cy, w, stability)


def diagnose():
    cache_files = sorted(glob.glob("user_data/pose_cache/*.json.gz"), key=os.path.getmtime, reverse=True)
    if not cache_files:
        print("No cache files found in user_data/pose_cache/")
        return

    print(f"Loaded {len(cache_files)} cached sessions from user_data/pose_cache/.\n")

    total_sessions = 0
    sessions_with_rim_dets = 0
    sessions_anchor_strict = 0
    sessions_anchor_production = 0

    all_rim_confs = []
    all_rim_aspects = []
    all_rim_widths = []

    per_session_results = []

    for f in cache_files:
        sess_name = os.path.basename(f).replace(".json.gz", "")
        try:
            with gzip.open(f, "rt", encoding="utf-8") as gz:
                data = json.load(gz)
        except Exception:
            continue

        total_sessions += 1
        ball_rim = data.get("ball_rim", [])
        if not ball_rim:
            continue

        fw = data.get("width") or 1920
        fh = data.get("height") or 1080
        total_frames = len(ball_rim)

        rim_frames = [t for t in ball_rim if t.get("rim") is not None]
        num_rim_dets = len(rim_frames)

        if num_rim_dets == 0:
            per_session_results.append({
                "session": sess_name,
                "frames": total_frames,
                "rim_dets": 0,
                "anchor_strict": False,
                "anchor_production": False,
                "notes": "No rim detected by YOLO",
            })
            continue

        sessions_with_rim_dets += 1

        raw_dets = []
        for t in rim_frames:
            r = t["rim"]
            rc = float(t.get("rim_conf", 0.0) or 0.0)
            cx = (r[0] + r[2]) / 2.0
            cy = (r[1] + r[3]) / 2.0
            w = r[2] - r[0]
            h = r[3] - r[1]
            raw_dets.append((cx, cy, w, h, rc))
            all_rim_confs.append(rc)
            if h > 0:
                all_rim_aspects.append(w / h)
            all_rim_widths.append(w)

        # 1. Old strict consensus
        anchor_strict = strict_consensus_rim_baseline(raw_dets, fw, fh)
        if anchor_strict is not None and anchor_strict[3] <= 0.15:
            sessions_anchor_strict += 1

        # 2. Production tuned consensus
        anchor_prod = consensus_rim(raw_dets, fw, fh)
        if anchor_prod is not None and anchor_prod.stability <= 0.25:
            sessions_anchor_production += 1

        confs = [d[4] for d in raw_dets]
        aspects = [d[2] / max(1.0, d[3]) for d in raw_dets]

        per_session_results.append({
            "session": sess_name,
            "frames": total_frames,
            "rim_dets": num_rim_dets,
            "rim_det_pct": round(100.0 * num_rim_dets / total_frames, 1),
            "mean_conf": round(float(np.mean(confs)), 2),
            "max_conf": round(float(np.max(confs)), 2),
            "mean_aspect": round(float(np.mean(aspects)), 2),
            "min_aspect": round(float(np.min(aspects)), 2),
            "max_aspect": round(float(np.max(aspects)), 2),
            "anchor_strict": bool(anchor_strict and anchor_strict[3] <= 0.15),
            "strict_stability": round(anchor_strict[3], 3) if anchor_strict else None,
            "anchor_production": bool(anchor_prod and anchor_prod.stability <= 0.25),
            "prod_stability": round(anchor_prod.stability, 3) if anchor_prod else None,
        })

    # Print summary
    print("=" * 80)
    print("RIM DETECTION & ANCHOR DIAGNOSIS SUMMARY")
    print("=" * 80)
    print(f"Total cached sessions evaluated: {total_sessions}")
    print(f"Sessions with raw YOLO rim detections: {sessions_with_rim_dets}/{total_sessions} ({100*sessions_with_rim_dets/max(1, total_sessions):.1f}%)")
    print(f"Sessions resolving anchor under STRICT filters (old 0% bug): {sessions_anchor_strict}/{sessions_with_rim_dets} ({100*sessions_anchor_strict/max(1, sessions_with_rim_dets):.1f}%)")
    print(f"Sessions resolving anchor under PRODUCTION TUNED filters:    {sessions_anchor_production}/{sessions_with_rim_dets} ({100*sessions_anchor_production/max(1, sessions_with_rim_dets):.1f}%)")
    print()

    if all_rim_confs:
        print("Raw YOLO Rim Confidence Distribution:")
        print(f"  Min:    {np.min(all_rim_confs):.2f}")
        print(f"  25th %: {np.percentile(all_rim_confs, 25):.2f}")
        print(f"  Median: {np.median(all_rim_confs):.2f}")
        print(f"  Mean:   {np.mean(all_rim_confs):.2f}")
        print(f"  75th %: {np.percentile(all_rim_confs, 75):.2f}")
        print(f"  Max:    {np.max(all_rim_confs):.2f}")
        below_05 = sum(1 for c in all_rim_confs if c < 0.5)
        print(f"  Detections with conf < 0.50: {below_05}/{len(all_rim_confs)} ({100*below_05/len(all_rim_confs):.1f}% were rejected by old filter)")
        print()

    if all_rim_aspects:
        print("Raw YOLO Rim Aspect Ratio (w / h) Distribution:")
        print(f"  Min:    {np.min(all_rim_aspects):.2f}")
        print(f"  25th %: {np.percentile(all_rim_aspects, 25):.2f}")
        print(f"  Median: {np.median(all_rim_aspects):.2f}")
        print(f"  Mean:   {np.mean(all_rim_aspects):.2f}")
        print(f"  75th %: {np.percentile(all_rim_aspects, 75):.2f}")
        print(f"  Max:    {np.max(all_rim_aspects):.2f}")
        outside_old = sum(1 for a in all_rim_aspects if not (1.1 <= a <= 3.0))
        print(f"  Detections with aspect outside [1.1, 3.0]: {outside_old}/{len(all_rim_aspects)} ({100*outside_old/len(all_rim_aspects):.1f}% were rejected by old filter)")
        print()

    print("-" * 80)
    print(f"{'Session':<32} | {'Frames':<6} | {'Rims':<6} | {'Det %':<6} | {'Conf':<6} | {'Aspect':<10} | {'Strict':<6} | {'Tuned':<6}")
    print("-" * 80)
    for r in per_session_results[:25]:
        aspect_str = f"{r.get('mean_aspect', '-')} [{r.get('min_aspect', '-')}-{r.get('max_aspect', '-')}]" if 'mean_aspect' in r else "-"
        print(
            f"{r['session'][:32]:<32} | "
            f"{r['frames']:<6} | "
            f"{r['rim_dets']:<6} | "
            f"{r.get('rim_det_pct', 0):<6} | "
            f"{r.get('mean_conf', '-'):<6} | "
            f"{aspect_str:<10} | "
            f"{str(r['anchor_strict']):<6} | "
            f"{str(r['anchor_production']):<6}"
        )
    print("=" * 80)


if __name__ == "__main__":
    diagnose()
