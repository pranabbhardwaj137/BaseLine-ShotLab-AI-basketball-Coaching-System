"""Evidence-gated coaching insights for the local Phase 8 player app."""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List

from basketball.analysis.baseline_engine import BaselineEngine, MIN_BASELINE_SAMPLE_SIZE
from basketball.coaching.coach_engine import CoachEngine, DEFAULT_COACHING_CONFIG
from basketball.persistence.shot_lab_db import ShotLabDB


METRIC_DEFINITIONS = {
    "sequence_lag_ms": {
        "label": "Kinetic sequencing lag",
        "unit": "ms",
        "baseline_mean": "mean_sequence_lag_all",
        "baseline_std": "std_sequence_lag_all",
        "cue_threshold": "tier1_sequence_lag_max_ms",
        "cue_direction": "above",
    },
    "elbow_angle_release_3d": {
        "label": "3D elbow angle at release",
        "unit": "degrees",
        "baseline_mean": "mean_elbow_release_all",
        "baseline_std": "std_elbow_release_all",
        "cue_threshold": "tier2_elbow_release_min_deg",
        "cue_direction": "below",
    },
    "torso_sway_deg": {
        "label": "Torso sway",
        "unit": "degrees",
        "baseline_mean": "mean_torso_sway_all",
        "baseline_std": "std_torso_sway_all",
        "cue_threshold": "tier3_torso_sway_max_deg",
        "cue_direction": "above",
    },
}


def _numeric_values(shots: List[Dict[str, Any]], key: str) -> List[float]:
    values = []
    for shot in shots:
        value = shot.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if math.isfinite(value):
            values.append(value)
    return values


def _metric_summary(shots: List[Dict[str, Any]], key: str, definition: Dict[str, str]) -> dict:
    values = _numeric_values(shots, key)
    count = len(values)
    ready = count >= MIN_BASELINE_SAMPLE_SIZE
    return {
        "key": key,
        "label": definition["label"],
        "unit": definition["unit"],
        "sample_count": count,
        "minimum_required": MIN_BASELINE_SAMPLE_SIZE,
        "status": "available" if ready else "insufficient_sample",
        "mean": round(statistics.mean(values), 2) if ready else None,
        "sample_std": round(statistics.stdev(values), 2) if count >= 2 and ready else (0.0 if ready else None),
    }


def _cue_evidence(cue: dict, shots: List[dict], shot_style: str, session_id: str) -> List[dict]:
    metric_key = cue.get("target_metric_key")
    definition = METRIC_DEFINITIONS.get(metric_key)
    if not definition:
        return []
    threshold = DEFAULT_COACHING_CONFIG.get(shot_style, DEFAULT_COACHING_CONFIG["jump_shot"])[
        definition["cue_threshold"]
    ]
    candidates = []
    for shot in shots:
        value = shot.get(metric_key)
        if value is None:
            continue
        is_trigger = value > threshold if definition["cue_direction"] == "above" else value < threshold
        if not is_trigger:
            continue
        release_frame = shot.get("annotated_release_frame")
        if release_frame is None:
            release_frame = shot.get("machine_release_frame")
        candidates.append({
            "shot_id": shot["shot_id"],
            "session_id": shot["session_id"],
            "metric_key": metric_key,
            "metric_value": round(float(value), 2),
            "unit": definition["unit"],
            "threshold": threshold,
            "frame": release_frame,
            "fps": shot.get("session_fps"),
            "current_session": shot["session_id"] == session_id,
            "outcome": shot.get("outcome", "unknown"),
        })
    candidates.sort(key=lambda item: (item["current_session"], abs(item["metric_value"] - threshold)), reverse=True)
    return candidates[:3]


def build_session_insights(db_path: str, session_id: str) -> dict:
    """Summarize only approved, confidence-gated shots and emit at most one cue."""
    db = ShotLabDB(db_path)
    session = db.get_session(session_id)
    if not session:
        return {"status": "NOT_FOUND", "session_id": session_id, "message": "Session not found."}

    session_shots_all = db.get_shots(session_id=session_id, min_confidence=None)
    session_approved = [
        shot for shot in session_shots_all
        if shot.get("review_status") == "approved" and shot.get("tracking_confidence") == "SUFFICIENT"
    ]
    cohort_shots_all = db.get_shots(
        player_id=session["player_id"],
        camera_view=session["camera_view"],
        shot_type=session["shot_type"],
        shot_style=session.get("shot_style", "jump_shot"),
        review_status="approved",
        min_confidence="SUFFICIENT",
    )
    session_contexts = {}
    for source_id in {shot["session_id"] for shot in cohort_shots_all}:
        source_session = db.get_session(source_id)
        if source_session:
            session_contexts[source_id] = source_session
    for shot in cohort_shots_all:
        shot["session_fps"] = session_contexts.get(shot["session_id"], {}).get("fps")

    session_metrics = [
        _metric_summary(session_approved, key, definition)
        for key, definition in METRIC_DEFINITIONS.items()
    ]
    cohort_metrics = {
        key: _metric_summary(cohort_shots_all, key, definition)
        for key, definition in METRIC_DEFINITIONS.items()
    }
    response = {
        "session_id": session_id,
        "status": "INSUFFICIENT_EVIDENCE",
        "context": {
            "player_id": session["player_id"],
            "camera_view": session["camera_view"],
            "shot_type": session["shot_type"],
            "shot_style": session.get("shot_style", "jump_shot"),
        },
        "session_approved_valid_shots": len(session_approved),
        "cohort_approved_valid_shots": len(cohort_shots_all),
        "minimum_required": MIN_BASELINE_SAMPLE_SIZE,
        "session_metrics": session_metrics,
        "cohort_metrics": list(cohort_metrics.values()),
        "cue": None,
        "evidence": [],
    }

    if len(cohort_shots_all) < MIN_BASELINE_SAMPLE_SIZE:
        response["message"] = (
            f"No coaching cue yet: {len(cohort_shots_all)} approved, confidence-gated shots in this "
            f"player/view/shot-style group; at least {MIN_BASELINE_SAMPLE_SIZE} are required."
        )
        return response

    eligible_metrics = {
        key for key, summary in cohort_metrics.items()
        if summary["sample_count"] >= MIN_BASELINE_SAMPLE_SIZE
    }
    if not eligible_metrics:
        response["message"] = (
            "No coaching cue yet: fewer than five approved shots contain the same measurable mechanic. "
            "Missing measurements are not filled in."
        )
        return response

    baseline = BaselineEngine(db).compute_baseline(
        player_id=session["player_id"],
        camera_view=session["camera_view"],
        shot_type=session["shot_type"],
        shot_style=session.get("shot_style", "jump_shot"),
        require_human_confirmed=True,
        save_to_db=False,
    )
    if baseline.get("status") != "VALID_BASELINE":
        response["message"] = baseline.get("message", "A matched reviewed baseline is not available yet.")
        return response

    for key, definition in METRIC_DEFINITIONS.items():
        if key not in eligible_metrics:
            baseline[definition["baseline_mean"]] = None
            baseline[definition["baseline_std"]] = None
    # Do not generate make/miss associations in the user app; this cue uses
    # mechanics thresholds only, with no outcome-causality language.
    baseline["sample_size_makes"] = 0
    baseline["sample_size_misses"] = 0
    cue = CoachEngine(db).generate_primary_cue(baseline, save_to_db=False)
    cue_metric = cue.get("target_metric_key")
    if cue.get("priority_tier", 0) > 0 and cue_metric in cohort_metrics:
        metric_sample_count = cohort_metrics[cue_metric]["sample_count"]
        cue["biomechanical_evidence"] = cue["biomechanical_evidence"].replace(
            f"Across {baseline['sample_size_total']} reviewed",
            f"Across {metric_sample_count} reviewed",
        )
    response["status"] = "READY"
    response["cue"] = {
        key: value for key, value in cue.items()
        if key not in {"player_id", "baseline_id", "remediation_id", "pre_make_count", "pre_total_count"}
    }
    response["cue"]["evidence"] = cue.get("biomechanical_evidence", "")
    response["cue"]["thresholds_are_starting_defaults"] = True
    response["cue"]["baseline_sample_size"] = len(cohort_shots_all)
    if cue.get("priority_tier", 0) > 0:
        response["evidence"] = _cue_evidence(
            cue, cohort_shots_all, session.get("shot_style", "jump_shot"), session_id
        )
        response["message"] = "One mechanics-based cue is available from approved, confidence-gated evidence."
    else:
        response["message"] = (
            "No cue threshold was crossed in the eligible metrics. The maintenance suggestion is a practice prompt, "
            "not a claim that form is optimal."
        )
    return response
