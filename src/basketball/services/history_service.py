"""Approved-evidence player history and descriptive practice trends."""

from __future__ import annotations

import datetime as dt
import statistics
from typing import Any

from basketball.persistence.shot_lab_db import ShotLabDB
from basketball.coaching.coaching_service import METRIC_DEFINITIONS, _numeric_values


MIN_METRIC_SAMPLES = 5


def _eligible(shot: dict[str, Any]) -> bool:
    return shot.get("review_status") == "approved" and shot.get("tracking_confidence") == "SUFFICIENT"


def _summary(shots: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = _numeric_values(shots, key)
    if len(values) < MIN_METRIC_SAMPLES:
        return {"sample_count": len(values), "mean": None, "sample_std": None,
                "minimum_required": MIN_METRIC_SAMPLES}
    return {"sample_count": len(values), "mean": round(statistics.mean(values), 2),
            "sample_std": round(statistics.stdev(values), 2),
            "minimum_required": MIN_METRIC_SAMPLES}


def _time_order(shot: dict[str, Any]) -> tuple[int, str]:
    frame = shot.get("annotated_release_frame")
    if frame is None:
        frame = shot.get("machine_release_frame")
    return (frame if isinstance(frame, int) else 2**63 - 1, str(shot.get("created_at") or ""))


def _session_record(session: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        key: {**_summary(shots, key), "label": definition["label"], "unit": definition["unit"]}
        for key, definition in METRIC_DEFINITIONS.items()
    }
    supported = [shot for shot in shots if _eligible(shot)]
    early_late = {}
    ordered = sorted(supported, key=_time_order)
    if len(ordered) >= 6:
        split = len(ordered) // 2
        early, late = ordered[:split], ordered[split:]
        for key, definition in METRIC_DEFINITIONS.items():
            early_values = _numeric_values(early, key)
            late_values = _numeric_values(late, key)
            if len(early_values) >= 3 and len(late_values) >= 3:
                early_mean, late_mean = statistics.mean(early_values), statistics.mean(late_values)
                early_late[key] = {
                    "label": definition["label"],
                    "early_mean": round(early_mean, 2),
                    "late_mean": round(late_mean, 2),
                    "late_minus_early": round(late_mean - early_mean, 2),
                    "early_count": len(early_values),
                    "late_count": len(late_values),
                    "interpretation": "Descriptive within-session change; this does not establish fatigue or cause.",
                }
    return {
        "session_id": session["session_id"],
        "created_at": str(session.get("created_at") or ""),
        "camera_view": session.get("camera_view"),
        "shot_type": session.get("shot_type"),
        "shot_style": session.get("shot_style") or "jump_shot",
        "approved_sufficient_shots": len(supported),
        "metrics": metrics,
        "within_session_change": early_late,
    }


def build_player_history(db_path: str, player_id: str, limit: int = 12) -> dict[str, Any]:
    """Return only reviewed, confidence-sufficient records for one player."""
    db = ShotLabDB(db_path)
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE player_id = ? ORDER BY created_at DESC, rowid DESC",
            (player_id,),
        ).fetchall()
    if not rows:
        return {
            "player_id": player_id, "sessions": [], "total_eligible_sessions": 0,
            "weekly_target": db.get_weekly_session_target(player_id),
            "eligible_sessions_this_week": 0, "active_streak_days": 0,
            "active_remediation": db.get_active_remediation(player_id),
            "latest_remediation": db.get_latest_remediation(player_id),
            "message": "No saved sessions for this player yet.",
        }

    all_approved = db.get_shots(player_id=player_id, review_status="approved", min_confidence="SUFFICIENT")
    by_session: dict[str, list[dict[str, Any]]] = {}
    for shot in all_approved:
        by_session.setdefault(shot["session_id"], []).append(shot)
    sessions = []
    for row in rows:
        session = dict(row)
        shots = by_session.get(session["session_id"], [])
        sessions.append(_session_record(session, shots))
    eligible_sessions = [session for session in sessions if session["approved_sufficient_shots"] > 0]

    # Compare only adjacent sessions with exactly the same camera and shot context,
    # and only when each session has enough observations for the given metric.
    for index, session in enumerate(sessions):
        previous = next((prior for prior in sessions[index + 1:]
                         if (prior["camera_view"], prior["shot_type"], prior["shot_style"])
                         == (session["camera_view"], session["shot_type"], session["shot_style"])
                         and any(metric["mean"] is not None for metric in prior["metrics"].values())), None)
        trends = {}
        if previous:
            for key, definition in METRIC_DEFINITIONS.items():
                current_metric = session["metrics"][key]
                previous_metric = previous["metrics"][key]
                if current_metric["mean"] is not None and previous_metric["mean"] is not None:
                    trends[key] = {
                        "label": definition["label"],
                        "previous_session_id": previous["session_id"],
                        "previous_mean": previous_metric["mean"],
                        "current_mean": current_metric["mean"],
                        "delta": round(current_metric["mean"] - previous_metric["mean"], 2),
                        "unit": definition["unit"],
                    }
        session["previous_comparable_session_id"] = previous["session_id"] if previous else None
        session["session_deltas"] = trends

    visible = sessions[:max(1, min(int(limit), 50))]
    day_strings = sorted({session["created_at"][:10] for session in eligible_sessions if len(session["created_at"]) >= 10})
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = {dt.date.fromisoformat(value) for value in day_strings}
    if today in dates:
        cursor = today
    elif today - dt.timedelta(days=1) in dates:
        cursor = today - dt.timedelta(days=1)
    else:
        cursor = None
    streak = 0
    while cursor is not None and cursor in dates:
        streak += 1
        cursor -= dt.timedelta(days=1)
    week_start = today - dt.timedelta(days=today.weekday())
    this_week = sum(1 for session in eligible_sessions
                    if len(session["created_at"]) >= 10
                    and week_start <= dt.date.fromisoformat(session["created_at"][:10]) <= today)
    return {
        "player_id": player_id,
        "sessions": visible,
        "total_eligible_sessions": len(eligible_sessions),
        "weekly_target": db.get_weekly_session_target(player_id),
        "eligible_sessions_this_week": this_week,
        "active_streak_days": streak,
        "active_remediation": db.get_active_remediation(player_id),
        "latest_remediation": db.get_latest_remediation(player_id),
        "activity_definition": "A practice session counts when it has at least one human-approved, confidence-sufficient shot; streaks count distinct days using the DB's UTC date.",
        "consistency_definition": "Per-session sample standard deviation for each metric; it is a variability summary, not a validated score.",
        "message": "History uses approved shots with sufficient tracking confidence. Sessions with no such shots do not count toward practice activity.",
    }
