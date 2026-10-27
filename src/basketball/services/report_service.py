"""Builds, persists and serves the per-session shooting-coach report.

Pipeline: shot rows (SQLite) + pose cache  ->  shooting_analysis.analyze_session
          -> shot_coach findings / plan / injury section -> 10-section report JSON
          + annotated keyframes (JPEG, drawn on real video frames).

Analysis and report are cached in SQLite (schema v7) keyed on their inputs, so reopening
a session returns the saved report; any review edit, boundary change or new pose data
changes the key and triggers a rebuild.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional

import cv2

import basketball.analysis.shooting_analysis as sa
import basketball.coaching.shot_coach as coach
from basketball.persistence.shot_lab_db import ShotLabDB

REPORT_VERSION = "shot-report-1.1"
KEYFRAME_KINDS = ("dip", "release", "finish")
MAX_KEYFRAME_ATTEMPTS = 12

VIEW_LABELS = {"side_90": "Side (90°)", "oblique_45": "Angled (45°)", "frontal": "Front", "rear": "Behind the shooter"}
CONFIDENCE_TEXT = {
    "high": "High — landmarks clearly visible on most frames, and the camera view suits this measurement.",
    "medium": "Medium — landmarks mostly visible, or the camera view is only partly suited.",
    "low": "Low — shown for reference only; not used for coaching.",
    "not_measurable": "Not measurable from this video — the camera view or visibility does not support it.",
}


# --------------------------------------------------------------------------- inputs
def session_profile(session: dict[str, Any]) -> dict[str, Any]:
    try:
        notes = json.loads(session.get("notes") or "{}")
    except (TypeError, json.JSONDecodeError):
        notes = {}
    return {
        "player_id": session.get("player_id"),
        "handedness": notes.get("handedness", "unspecified"),
        "skill_level": notes.get("skill_level", "intermediate"),
        "goals": notes.get("goals", ""),
        "pain_reported": bool(notes.get("pain_reported")),
        "original_filename": notes.get("original_filename"),
        "video": notes.get("video") or {},
        "camera_view": session.get("camera_view"),
        "shot_type": session.get("shot_type"),
        "shot_style": session.get("shot_style") or "jump_shot",
        "created_at": str(session.get("created_at") or ""),
    }


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _shot_state(shots):
    return [(s["shot_id"], s.get("annotated_start_frame"), s.get("annotated_dip_frame"), s.get("annotated_release_frame"), s.get("annotated_end_frame"),
             s.get("machine_start_frame"), s.get("machine_dip_frame"), s.get("machine_release_frame"), s.get("machine_end_frame"),
             s.get("review_status"), s.get("outcome"), s.get("automated_outcome"), s.get("automated_outcome_conf")) for s in shots]


def _cache_stamp(path: Path):
    try:
        stat = path.stat()
        return (stat.st_size, int(stat.st_mtime))
    except OSError:
        return None


# --------------------------------------------------------------------------- analysis
def get_or_compute_analysis(db_path: str, session_id: str, pose_cache_dir: Path) -> dict[str, Any]:
    """Return the stored session analysis, recomputing it when its inputs changed."""
    db = ShotLabDB(db_path)
    session = db.get_session(session_id)
    if not session:
        raise LookupError("Session not found")
    profile = session_profile(session)
    shots = db.get_shots(session_id=session_id, min_confidence=None)
    cache_path = Path(pose_cache_dir) / f"{session_id}.json.gz"
    stamp = _cache_stamp(cache_path)
    if stamp is None:
        return {"status": "NO_POSE_DATA", "message": "This session has no pose data on this computer, so it cannot be measured. "
                "Sessions created with the desktop app (main.py) or whose pose cache was deleted cannot produce a coaching report.",
                "attempts": [], "camera_view": session.get("camera_view")}
    input_key = _key(sa.ANALYSIS_VERSION, stamp, _shot_state(shots), session.get("camera_view"), profile["handedness"])
    stored = db.get_session_analysis(session_id)
    if stored and stored["input_key"] == input_key:
        return stored["analysis"]
    cache = sa.load_pose_cache(cache_path)
    analysis = sa.analyze_session(cache, shots, session.get("camera_view") or "side_90",
                                  handedness=profile["handedness"], metadata=profile["video"])
    analysis["status"] = "COMPLETE"
    analysis["input_key"] = input_key
    db.save_session_analysis(session_id, analysis, input_key)
    return analysis


# --------------------------------------------------------------------------- keyframes
SKELETON = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25),
            (25, 27), (24, 26), (26, 28), (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32)]


def _read_frame(paths, frame_index):
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                continue
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, image = capture.read()
            if ok and image is not None:
                return image
        finally:
            capture.release()
    return None


def _draw_label(image, text, org, scale, color=(255, 255, 255), bg=(16, 21, 29)):
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = max(1, int(round(scale * 2)))
    (w, h), base = cv2.getTextSize(text, font, scale, thickness)
    x, y = int(org[0]), int(org[1])
    x = max(2, min(image.shape[1] - w - 6, x))
    y = max(h + 6, min(image.shape[0] - 4, y))
    cv2.rectangle(image, (x - 4, y - h - 6), (x + w + 4, y + base), bg, -1)
    cv2.putText(image, text, (x, y - 2), font, scale, color, thickness, cv2.LINE_AA)


def render_keyframe(video_paths, series: sa.PoseSeries, frame_index: int, attempt: dict, kind: str,
                    out_path: Path) -> bool:
    image = _read_frame(video_paths, frame_index)
    if image is None:
        return False
    h, w = image.shape[:2]
    sx, sy = w / series.width, h / series.height
    scale = max(0.5, min(1.4, h / 900))

    def pt(joint):
        p = series.point(frame_index, joint)
        return (int(p[0] * sx), int(p[1] * sy)) if p and p[2] >= 0.3 else None

    side = attempt.get("shooting_side") or "right"
    arm = sa.SIDE_JOINTS[side]
    leg = sa.SIDE_JOINTS[attempt.get("leg_side") or side]
    highlight = {(arm["shoulder"], arm["elbow"]), (arm["elbow"], arm["wrist"]),
                 (leg["hip"], leg["knee"]), (leg["knee"], leg["ankle"])}
    thick = max(2, int(3 * scale))
    for a, b in SKELETON:
        pa, pb = pt(a), pt(b)
        if pa and pb:
            color = (5, 183, 242) if (a, b) in highlight or (b, a) in highlight else (235, 235, 235)
            cv2.line(image, pa, pb, (16, 21, 29), thick + 3, cv2.LINE_AA)
            cv2.line(image, pa, pb, color, thick, cv2.LINE_AA)
    for joint in range(11, 33):
        p = pt(joint)
        if p:
            cv2.circle(image, p, thick + 1, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(image, p, thick + 1, (16, 21, 29), 1, cv2.LINE_AA)
    elbow = sa.angle_2d(series.point(frame_index, arm["shoulder"]), series.point(frame_index, arm["elbow"]),
                        series.point(frame_index, arm["wrist"]))
    knee = sa.angle_2d(series.point(frame_index, leg["hip"]), series.point(frame_index, leg["knee"]),
                       series.point(frame_index, leg["ankle"]))
    if elbow is not None and pt(arm["elbow"]):
        _draw_label(image, f"elbow {elbow:.0f} deg", (pt(arm["elbow"])[0] + 12, pt(arm["elbow"])[1]), scale * 0.7)
    if knee is not None and pt(leg["knee"]):
        _draw_label(image, f"knee {knee:.0f} deg", (pt(leg["knee"])[0] + 12, pt(leg["knee"])[1]), scale * 0.7)
    caption = f"Attempt {attempt['attempt_index']}  {kind.title()}  {frame_index / series.fps:.2f} s  (frame {frame_index})  2D image angles"
    _draw_label(image, caption, (10, h - 10), scale * 0.62, color=(255, 255, 255), bg=(216, 79, 31))  # BGR marker blue
    max_h = 720
    if h > max_h:
        image = cv2.resize(image, (int(w * max_h / h), max_h), interpolation=cv2.INTER_AREA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.jpg")
    if not cv2.imwrite(str(tmp), image, [cv2.IMWRITE_JPEG_QUALITY, 82]):
        return False
    tmp.replace(out_path)
    return True


def _keyframe_frames(attempt):
    finish = (attempt["metrics"].get("elbow_extension_peak_deg") or {}).get("frame")
    return {"dip": attempt.get("dip_frame"), "release": attempt.get("release_frame"),
            "finish": finish if finish is not None and finish != attempt.get("release_frame") else None}


def ensure_keyframes(session_id: str, analysis: dict, pose_cache_dir: Path, keyframe_dir: Path, video_paths) -> list[dict]:
    """Render (or reuse) annotated keyframes for each non-discarded attempt."""
    attempts = [a for a in analysis.get("attempts", []) if a.get("review_status") != "discarded"][:MAX_KEYFRAME_ATTEMPTS]
    if not attempts:
        return []
    folder = Path(keyframe_dir) / session_id
    wanted, series = [], None
    for attempt in attempts:
        for kind, frame in _keyframe_frames(attempt).items():
            if frame is None:
                continue
            name = f"{attempt['shot_id']}_{kind}_{int(frame)}.jpg"
            path = folder / name
            if not path.is_file():
                if series is None:
                    series = sa.PoseSeries(sa.load_pose_cache(Path(pose_cache_dir) / f"{session_id}.json.gz"))
                if not render_keyframe(video_paths, series, int(frame), attempt, kind, path):
                    continue
            wanted.append({"attempt": attempt["attempt_index"], "shot_id": attempt["shot_id"], "kind": kind,
                           "frame": int(frame), "time_s": round(int(frame) / (analysis.get("fps") or 30), 3), "name": name})
    keep = {item["name"] for item in wanted}
    if folder.is_dir():
        for stale in folder.glob("*.jpg"):
            if stale.name not in keep:
                stale.unlink(missing_ok=True)
    return wanted


# --------------------------------------------------------------------------- report
def _technical_rows(analysis, coaching):
    attempts = analysis.get("attempts", [])
    findings_by_metric = {}
    # Specific findings describe an area better than the cross-metric consistency finding.
    for finding in sorted(coaching["findings"], key=lambda f: f["category"] == "consistency"):
        for key in finding.get("metric_keys", []):
            findings_by_metric.setdefault(key, finding)
    rows = []
    for area, keys in coach.AREAS:
        measured, reasons = [], []
        for key in keys:
            pairs = coach.usable_values(attempts, key)
            definition = sa.METRIC_DEFINITIONS[key]
            if pairs:
                values = [r["value"] for _, r in pairs]
                conf = min((r["confidence"] for _, r in pairs), key=lambda c: sa.CONFIDENCE_ORDER[c])
                text = coach._fmt(values[0], definition["unit"]) if len(values) == 1 else \
                    f"{coach._fmt(statistics_mean(values), definition['unit'])} avg ({coach._fmt(min(values), definition['unit'])}–{coach._fmt(max(values), definition['unit'])}, n={len(values)})"
                measured.append({"key": key, "label": definition["label"], "text": text, "confidence": conf,
                                 "basis": definition["basis"]})
            else:
                records = [a["metrics"].get(key) for a in attempts if a.get("review_status") != "discarded"]
                reason = next((r.get("reason") for r in records if r and r.get("reason")), None)
                if reason:
                    reasons.append(f"{definition['label']}: {reason}")
        finding = next((findings_by_metric[k] for k in keys if k in findings_by_metric), None)
        if not measured:
            rows.append({"area": area, "observation": "Not measurable from this video", "evidence": [],
                         "confidence": "not_measurable", "interpretation": reasons[0] if reasons else
                         "No attempt had usable landmarks for this area."})
            continue
        if finding:
            observation = finding["title"]
            interpretation = (("Strength: " if finding["kind"] == "strength" else "Work on: ") + finding["action"])
            confidence = finding["confidence"]
        else:
            observation = "Measured; no clear pattern to flag"
            interpretation = "Values fell between the coaching thresholds or varied between attempts; compare with your next session."
            confidence = min((m["confidence"] for m in measured), key=lambda c: sa.CONFIDENCE_ORDER[c])
        rows.append({"area": area, "observation": observation, "evidence": measured,
                     "confidence": confidence, "interpretation": interpretation})
    return rows


def statistics_mean(values):
    return sum(values) / len(values)


def _shot_by_shot(analysis, focus):
    out = []
    for attempt in analysis.get("attempts", []):
        evaluation = coach.evaluate_attempt(attempt) if attempt.get("review_status") != "discarded" else {"strengths": [], "opportunities": []}
        measurements = []
        for key, record in attempt["metrics"].items():
            if record.get("value") is None:
                continue
            measurements.append({"key": key, "label": record["label"], "display": coach._fmt(record["value"], record["unit"]),
                                 "confidence": record["confidence"], "time_s": record.get("time_s"),
                                 "frame": record.get("frame"), "detail": record.get("detail")})
        if attempt.get("review_status") == "discarded":
            action = "Marked 'Not a shot'; excluded from coaching."
        elif evaluation["opportunities"] and focus:
            action = f"Apply your first focus: {focus['action']}"
        elif evaluation["opportunities"]:
            action = "Re-check this attempt in the replay before changing anything."
        else:
            action = "Repeat this pattern."
        out.append({
            "attempt": attempt["attempt_index"], "shot_id": attempt["shot_id"],
            "start_s": attempt.get("start_s"), "release_s": attempt.get("release_s"), "end_s": attempt.get("end_s"),
            "dip_s": attempt.get("dip_s"),
            "start_frame": attempt.get("start_frame"), "release_frame": attempt.get("release_frame"), "dip_frame": attempt.get("dip_frame"),
            "review_status": attempt.get("review_status"), "outcome": attempt.get("outcome"),
            "automated_outcome": attempt.get("automated_outcome"),
            "automated_outcome_conf": attempt.get("automated_outcome_conf"),
            "trajectory_fit_r2": attempt.get("trajectory_fit_r2"),
            "entry_angle_deg": attempt.get("entry_angle_deg"),
            "manually_added": attempt.get("manually_added"), "shooting_side": attempt.get("shooting_side"),
            "pose_coverage": attempt.get("pose_coverage"),
            "measurements": measurements, "strengths": evaluation["strengths"],
            "opportunities": evaluation["opportunities"], "next_action": action,
        })
    return out


def _previous_comparison(db: ShotLabDB, session: dict, analysis: dict) -> Optional[dict]:
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT s.session_id, s.created_at, a.analysis_json FROM sessions s JOIN session_analysis a ON a.session_id = s.session_id "
            "WHERE s.player_id = ? AND s.camera_view = ? AND s.shot_type = ? AND COALESCE(s.shot_style,'jump_shot') = ? "
            "AND s.session_id != ? AND s.created_at <= ? ORDER BY s.created_at DESC LIMIT 1",
            (session["player_id"], session["camera_view"], session["shot_type"], session.get("shot_style") or "jump_shot",
             session["session_id"], session.get("created_at") or "9999"),
        ).fetchall()
    if not rows:
        return None
    previous = json.loads(rows[0]["analysis_json"])
    deltas = []
    for key, entry in analysis.get("consistency", {}).items():
        before = previous.get("consistency", {}).get(key, {})
        if entry.get("mean") is not None and before.get("mean") is not None:
            deltas.append({"key": key, "label": entry["label"], "unit": entry["unit"], "previous": before["mean"],
                           "current": entry["mean"], "change": round(entry["mean"] - before["mean"], 2),
                           "previous_sd": before.get("sd"), "current_sd": entry.get("sd")})
    warnings = []
    pq, cq = previous.get("quality", {}), analysis.get("quality", {})
    if pq.get("estimated_view") and cq.get("estimated_view") and pq["estimated_view"] != cq["estimated_view"]:
        warnings.append("The camera angle looks different from the previous session, so view-dependent changes may not be real.")
    if pq.get("subject_height_ratio") and cq.get("subject_height_ratio") and \
            abs(pq["subject_height_ratio"] - cq["subject_height_ratio"]) > 0.1:
        warnings.append("You appear at a different size in the frame than last time; the camera distance probably changed.")
    return {"previous_session_id": rows[0]["session_id"], "previous_date": str(rows[0]["created_at"]),
            "deltas": deltas, "warnings": warnings,
            "note": "Descriptive change between sessions. Changes smaller than the spread (SD) are within normal variation."}


def build_report(db_path: str, session_id: str, pose_cache_dir: Path, keyframe_dir: Path, video_paths=(),
                 *, force: bool = False) -> dict[str, Any]:
    db = ShotLabDB(db_path)
    session = db.get_session(session_id)
    if not session:
        raise LookupError("Session not found")
    profile = session_profile(session)
    analysis = get_or_compute_analysis(db_path, session_id, pose_cache_dir)
    input_key = _key(REPORT_VERSION, coach.COACH_VERSION, analysis.get("input_key"), profile,
                     analysis.get("status"))
    stored = db.get_session_report(session_id)
    if stored and stored["input_key"] == input_key and not force:
        report = stored["report"]
        # Keyframes are files; make sure they still exist (e.g. after moving folders).
        if analysis.get("status") == "COMPLETE":
            report["evidence"]["keyframes"] = ensure_keyframes(session_id, analysis, pose_cache_dir, keyframe_dir, video_paths)
        report["meta"]["from_cache"] = True
        return report

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    attempts = analysis.get("attempts", [])
    active = [a for a in attempts if a.get("review_status") != "discarded"]
    confirmed = [a for a in active if a.get("review_status") == "approved"]
    coaching = coach.build_findings(analysis, profile) if attempts else coach.build_findings({"attempts": []}, profile)
    focus = coach.first_focus(coaching)
    plan = coach.build_practice_plan(coaching, analysis, profile)
    injury = coach.build_injury_section(analysis, coaching, profile)
    quality = analysis.get("quality") or {}
    keyframes = ensure_keyframes(session_id, analysis, pose_cache_dir, keyframe_dir, video_paths) \
        if analysis.get("status") == "COMPLETE" else []

    has_ball = any(a.get("automated_outcome") and a.get("automated_outcome") != "unknown" for a in active)
    limitations = [
        "Measurements come from single-camera 2D pose estimation; they are estimates, not lab motion capture.",
    ]
    if not has_ball:
        limitations.append("Ball and rim trajectory was inconclusive or not detected, so make/miss outcomes require human review.")
    if quality.get("issues"):
        limitations.extend(quality["issues"])
    if active and not confirmed:
        limitations.append("None of the attempts has been confirmed in Review yet; findings rest on machine-proposed attempts and their confidence is reduced.")
    if len(active) < 3:
        limitations.append(f"Only {len(active)} attempt{'s' if len(active) != 1 else ''} analysed; consistency needs at least three.")

    if analysis.get("status") == "NO_POSE_DATA":
        summary = analysis["message"]
    elif not active:
        summary = "No shot attempts are available to analyse. Add an attempt manually in Review, or upload a clip where your whole body and the ball are visible."
    else:
        parts = []
        if coaching["top_strengths"]:
            parts.append("Strongest: " + "; ".join(f["title"].lower() for f in coaching["top_strengths"][:2]) + ".")
        if focus:
            parts.append(f"First focus: {focus['title'].lower()}.")
        if not parts:
            parts.append("No pattern was clear enough to flag with medium or high confidence; see the technical table and shot-by-shot measurements.")
        summary = " ".join(parts)

    observations = []
    for finding in coaching["findings"]:
        for stamp in finding.get("timestamps", []):
            observations.append({"time_s": stamp["time_s"], "frame": stamp["frame"], "attempt": stamp["attempt"],
                                 "text": f"{finding['title']} — {stamp['label']}", "finding_id": finding["id"],
                                 "kind": finding["kind"], "confidence": finding["confidence"]})
    observations.sort(key=lambda o: (o["time_s"], o["attempt"]))

    comparison_keys = ["knee_flexion_min_deg", "elbow_angle_release_deg", "elbow_extension_peak_deg",
                       "release_height_ratio", "torso_lean_change_deg", "hip_drift_ratio", "follow_through_hold_ms"]
    comparison = {"columns": [{"key": k, "label": sa.METRIC_DEFINITIONS[k]["label"], "unit": sa.METRIC_DEFINITIONS[k]["unit"]}
                              for k in comparison_keys],
                  "rows": [{"attempt": a["attempt_index"], "review_status": a.get("review_status"),
                            "values": {k: {"display": coach._fmt(a["metrics"][k]["value"], a["metrics"][k]["unit"]) if a["metrics"][k]["value"] is not None else "—",
                                           "confidence": a["metrics"][k]["confidence"]} for k in comparison_keys}}
                           for a in active]}

    used_keys = sorted({k for a in active for k, r in a["metrics"].items() if r.get("value") is not None})

    trajectory_attempts = [
        a for a in active if a.get("automated_outcome") and a.get("automated_outcome") != "unknown"
    ]
    if trajectory_attempts:
        ball_traj_summary = f"{len(trajectory_attempts)} of {len(active)} attempt{'s' if len(active) != 1 else ''} tracked with advisory ball/rim trajectory."
    else:
        ball_traj_summary = "Ball trajectory was not detected or was inconclusive for these attempts."

    report = {
        "meta": {"session_id": session_id, "player_id": session["player_id"], "generated_at": generated_at,
                 "report_version": REPORT_VERSION, "analysis_version": analysis.get("analysis_version"),
                 "coach_version": coach.COACH_VERSION, "from_cache": False},
        "overview": {
            "session_date": profile["created_at"], "video_filename": profile.get("original_filename"),
            "duration_s": profile["video"].get("duration_seconds") or analysis.get("duration_s"),
            "fps": profile["video"].get("fps") or analysis.get("fps"),
            "resolution": f"{profile['video'].get('width')}×{profile['video'].get('height')}" if profile["video"].get("width") else None,
            "attempts_total": len(attempts), "attempts_confirmed": len(confirmed),
            "attempts_unconfirmed": len([a for a in active if a.get("review_status") != "approved"]),
            "attempts_discarded": len(attempts) - len(active),
            "analysis_status": analysis.get("status"),
            "camera_view": VIEW_LABELS.get(session.get("camera_view"), session.get("camera_view")),
            "estimated_view": VIEW_LABELS.get(quality.get("estimated_view"), quality.get("estimated_view")),
            "quality": quality, "limitations": limitations, "summary": summary,
            "shot_type": session.get("shot_type"), "shot_style": session.get("shot_style") or "jump_shot",
            "skill_level": profile["skill_level"], "goals": profile["goals"],
        },
        "executive": {
            "strengths": coaching["top_strengths"], "improvements": coaching["top_improvements"],
            "possible_issues": coaching["possible_issues"], "first_focus": focus,
            "no_strengths_note": None if coaching["top_strengths"] else "No strength was supported strongly enough to list; this does not mean there are none.",
            "no_improvements_note": None if coaching["top_improvements"] else "No improvement area was supported with medium or high confidence.",
        },
        "technical": _technical_rows(analysis, coaching) if active else [],
        "evidence": {"keyframes": keyframes, "observations": observations, "comparison": comparison,
                     "ball_trajectory": ball_traj_summary},
        "shots": _shot_by_shot(analysis, focus),
        "correction_plan": [{
            "finding_id": f["id"], "issue": f["title"], "category": f["category"], "evidence": f["observed"],
            "evidence_items": f["evidence"], "why": f["why"], "cue": f["action"], "drills": f["drills"],
            "success": f.get("success"), "confidence": f["confidence"], "confidence_reason": f["confidence_reason"],
            "limitations": f["limitations"],
        } for f in (coaching["top_improvements"] or coaching["possible_issues"])],
        "practice_plan": plan,
        "injury": injury,
        "progress": {
            "baseline": plan["baseline_metrics"],
            "priorities": [f["title"] for f in (coaching["top_improvements"] or coaching["possible_issues"])][:3],
            "checklist": plan["checklist"], "compare_metrics": [b["label"] for b in plan["baseline_metrics"]],
            "recording_warning": "Future comparisons are only reliable from the same camera position, view, distance and lighting."
                                 + (" This session already has recording issues: " + " ".join(quality.get("issues", [])) if quality.get("issues") else ""),
            "previous": _previous_comparison(db, session, analysis) if analysis.get("status") == "COMPLETE" else None,
        },
        "findings": coaching["findings"],
        "methodology": {
            "pipeline": [
                "OpenCV decodes every frame (FFmpeg converts formats OpenCV cannot read).",
                "MediaPipe Pose Landmarker (BlazePose, heavy model) estimates 33 body landmarks per frame with a visibility score, plus estimated 3D world coordinates. Landmarks are lightly smoothed over time.",
                "A shot-phase state machine proposes attempts from wrist height and arm movement; you can confirm, correct, discard or add attempts.",
                "For each attempt the measurement engine computes the metrics below from the landmarks around the dip, release and landing.",
                "Deterministic coaching rules turn medium/high-confidence measurements into findings; an optional AI explanation can only rephrase this evidence.",
            ],
            "metrics": [{"key": k, "label": sa.METRIC_DEFINITIONS[k]["label"], "unit": sa.METRIC_DEFINITIONS[k]["unit"],
                         "basis": sa.METRIC_DEFINITIONS[k]["basis"], "definition": sa.METRIC_DEFINITIONS[k]["definition"],
                         "limitation": sa.METRIC_DEFINITIONS[k]["limitation"],
                         "views": {VIEW_LABELS[v]: s for v, s in sa.METRIC_DEFINITIONS[k]["views"].items()}}
                        for k in (used_keys or list(sa.METRIC_DEFINITIONS))],
            "confidence": CONFIDENCE_TEXT,
            "bases": {"image_2d": "Angle measured in the image plane (a projection, depends on camera angle).",
                      "world_3d_estimate": "Angle from MediaPipe's inferred 3D coordinates (model estimate from one camera).",
                      "image_ratio": "Distance in the image divided by your own torso length, shoulder width or hip width; not centimetres.",
                      "timing": "Frame differences converted to milliseconds; resolution is one frame."},
            "medical": "This report gives coaching observations, not medical advice. It does not diagnose, predict or score injury risk.",
            "thresholds": "Coaching thresholds are prototype heuristics chosen to flag only clear patterns; they are not validated norms and no single 'ideal' form is assumed.",
        },
    }
    db.save_session_report(session_id, report, input_key, REPORT_VERSION)
    return report
