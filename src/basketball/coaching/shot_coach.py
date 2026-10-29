"""Deterministic, evidence-grounded shooting coach.

Input: the output of ``shooting_analysis.analyze_session`` plus the player's profile.
Output: findings (strengths and improvements), a correction plan, a practice plan and
the "Technique, Load Management, and Injury-Risk Reduction" guidance.

Every finding answers five questions - what was observed, which evidence from the
video supports it, why it may matter, what to change, how to practise - and lists the
attempts, timestamps, measurements and confidence it rests on. A rule only fires when
measured values with medium or high confidence support it; nothing here is generic
advice presented as a measurement.

Thresholds below are coaching heuristics chosen for this prototype so that only clear
patterns are flagged. They are not validated norms and do not define an ideal form;
the report says so wherever they are used.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Callable, Optional

from basketball.analysis.shooting_analysis import METRIC_DEFINITIONS, USABLE

COACH_VERSION = "shot-coach-1.1"

SKILL_SETTINGS = {
    "beginner": {"sessions": "3 sessions a week", "minutes": "30-40 minutes", "shot_cap": 100, "sets": 2},
    "intermediate": {"sessions": "3-4 sessions a week", "minutes": "40-50 minutes", "shot_cap": 200, "sets": 3},
    "advanced": {"sessions": "4-5 sessions a week", "minutes": "50-60 minutes", "shot_cap": 300, "sets": 3},
    "coach": {"sessions": "3-4 sessions a week (adjust to the player)", "minutes": "40-50 minutes", "shot_cap": 200, "sets": 3},
}

DRILLS: dict[str, dict[str, Any]] = {
    "one_hand_form": {
        "name": "One-hand form shooting",
        "how": "Stand 1-2 m from the rim, ball on the shooting hand only, guide hand behind your back. Lift, extend and hold the finish until the ball lands.",
        "dose": {"beginner": "2 sets of 8 makes", "intermediate": "3 sets of 10 makes", "advanced": "3 sets of 12 makes"},
    },
    "follow_through_hold": {
        "name": "Hold the follow-through",
        "how": "On every close-range shot, keep the arm up and the wrist relaxed until the ball hits the rim or net. Count 'one-two' before lowering it.",
        "dose": {"beginner": "Every shot in the form block", "intermediate": "Every shot in the form block", "advanced": "Every shot in the form and spot blocks"},
    },
    "dip_and_rise": {
        "name": "Dip-and-rise rhythm",
        "how": "Start tall, ball at the chest. Bend the knees into a comfortable quarter-squat as the ball dips to the waist, then rise and shoot in one smooth motion. Do it without the ball first, then from 1-2 m.",
        "dose": {"beginner": "2 sets of 6 without the ball, then 2 sets of 6 shots", "intermediate": "2 sets of 8 without the ball, then 3 sets of 8 shots", "advanced": "3 sets of 8 shots from three spots"},
    },
    "legs_then_arm": {
        "name": "'One-two' timing shots",
        "how": "Say 'one' as the legs push and 'two' as the arm extends. Shoot from 2 m, slow tempo, so the arm only finishes after the legs have started straightening.",
        "dose": {"beginner": "2 sets of 8", "intermediate": "3 sets of 8", "advanced": "3 sets of 10"},
    },
    "land_and_freeze": {
        "name": "Land-and-freeze",
        "how": "Mark your take-off spot with tape. Shoot from 1-2 m, then land on both feet and freeze for two seconds. Check that you landed on or very near the tape, knees soft.",
        "dose": {"beginner": "2 sets of 6", "intermediate": "3 sets of 8", "advanced": "3 sets of 8, then 1 set from 3 m"},
    },
    "tall_chest_form": {
        "name": "Tall-chest form shooting",
        "how": "From 1-2 m, keep the chest tall and the head still from the dip to the landing; jump straight up rather than forward or sideways.",
        "dose": {"beginner": "2 sets of 8", "intermediate": "3 sets of 8", "advanced": "3 sets of 10"},
    },
    "elbow_under_ball": {
        "name": "Wall line-up",
        "how": "Stand facing a wall or mirror at arm's length. Lift the ball with the shooting elbow under it and the forearm vertical, then extend toward the wall without touching it. Then repeat the same line-up on close shots.",
        "dose": {"beginner": "2 sets of 10 reps", "intermediate": "2 sets of 10 reps, then 2 sets of 8 shots", "advanced": "2 sets of 10 shots"},
    },
    "same_shot_ladder": {
        "name": "Same-shot ladder",
        "how": "Five spots, one step apart, starting 1 m from the rim. Take 5 shots per spot with the same cue; move back only after 4 of 5 feel identical (same dip, same finish).",
        "dose": {"beginner": "Spots 1-3", "intermediate": "Spots 1-5", "advanced": "Spots 1-5, twice"},
    },
}

# area -> metrics, used for the technical table
AREAS = [
    ("Stance", ["stance_width_ratio"]),
    ("Balance and landing", ["hip_drift_ratio", "landing_offset_ratio"]),
    ("Lower body", ["knee_flexion_min_deg", "hip_flexion_min_deg", "knee_extension_range_deg", "knee_inward_ratio"]),
    ("Elbow alignment", ["elbow_flare_ratio", "elbow_angle_set_deg"]),
    ("Arm extension", ["elbow_extension_peak_deg"]),
    ("Release", ["elbow_angle_release_deg", "elbow_angle_release_3d_deg", "release_height_ratio", "shoulder_elevation_release_deg"]),
    ("Torso", ["torso_lean_release_deg", "torso_lean_change_deg"]),
    ("Follow-through", ["follow_through_hold_ms"]),
    ("Timing", ["sequencing_lag_ms", "release_vs_leg_extension_ms", "prep_duration_ms"]),
]

LEVELS = ["low", "medium", "high"]


# --------------------------------------------------------------------------- helpers
def _active(attempts):
    return [a for a in attempts if a.get("review_status") != "discarded"]


def usable_values(attempts, key):
    """(attempt, metric record) pairs with medium/high confidence for one metric."""
    out = []
    for attempt in _active(attempts):
        record = attempt["metrics"].get(key)
        if record and record.get("confidence") in USABLE and record.get("value") is not None:
            out.append((attempt, record))
    return out


def _fmt(value, unit):
    if value is None:
        return " - "
    if unit == "°":
        return f"{value:.0f}°"
    if unit == "ms":
        return f"{value:.0f} ms"
    return f"{value:.2f} {unit}"


def _evidence(pairs):
    return [{
        "attempt": a["attempt_index"], "shot_id": a.get("shot_id"), "metric": r["key"], "label": r["label"],
        "value": r["value"], "unit": r["unit"], "display": _fmt(r["value"], r["unit"]),
        "frame": r.get("frame"), "time_s": r.get("time_s"), "confidence": r["confidence"],
        "confirmed": a.get("review_status") == "approved", "detail": r.get("detail"),
    } for a, r in pairs]


def _finding_confidence(supporting, total_usable):
    """Confidence of a pattern: how many attempts support it, how good the data is, and review state."""
    if not supporting:
        return "low", "No supporting measurements."
    n = len(supporting)
    all_high = all(r["confidence"] == "high" for _, r in supporting)
    if n >= 3 and all_high:
        level = 2
    elif n >= 2:
        level = 1
    else:
        level = 0
    reason = f"Seen in {n} of {total_usable} measured attempt{'s' if total_usable != 1 else ''}"
    reason += ", all with high landmark confidence" if all_high else ", with at least medium landmark confidence"
    if not any(a.get("review_status") == "approved" for a, _ in supporting):
        level = max(0, level - 1)
        reason += "; none of these attempts has been confirmed by you yet, so confidence is reduced one level"
    return LEVELS[level], reason + "."


def _majority(pairs, test):
    hits = [(a, r) for a, r in pairs if test(r["value"])]
    needed = max(1, math.ceil(len(pairs) / 2))
    return hits if len(hits) >= needed and pairs else []


def _times(evidence):
    stamps = [e for e in evidence if e.get("time_s") is not None]
    return [{"attempt": e["attempt"], "time_s": e["time_s"], "frame": e["frame"], "label": e["label"]} for e in stamps]


def _range_text(pairs, unit):
    values = [r["value"] for _, r in pairs]
    if not values:
        return ""
    if len(values) == 1:
        return _fmt(values[0], unit)
    return f"{_fmt(min(values), unit)}-{_fmt(max(values), unit)}"


def _attempt_list(pairs):
    return ", ".join(str(a["attempt_index"]) for a, _ in pairs)


# --------------------------------------------------------------------------- rules
def _rule_arm_extension(ctx):
    pairs = usable_values(ctx["attempts"], "elbow_extension_peak_deg")
    out = []
    bent = _majority(pairs, lambda v: v < 150)
    full = _majority(pairs, lambda v: v >= 160)
    if bent:
        out.append(dict(
            id="arm_extension", kind="improvement", category="release", priority=60,
            title="Shooting arm stays bent after release",
            observed=f"The shooting elbow reached at most {_range_text(bent, '°')} in the half-second around release on attempts {_attempt_list(bent)}.",
            why="When the arm does not straighten through the ball, the shot is pushed rather than released along a repeatable line, which usually makes distance and arc harder to control.",
            action="Reach up and through the ball: finish with the arm long and the elbow at or above eyebrow height, then hold it.",
            drills=["one_hand_form", "follow_through_hold"], supporting=bent, total=len(pairs),
            success="Next session: arm extension of 160° or more on most attempts filmed from the same side view.",
            metric_keys=["elbow_extension_peak_deg"]))
    elif full:
        out.append(dict(
            id="arm_extension_good", kind="strength", category="release", priority=40,
            title="Arm extends fully through the release",
            observed=f"The shooting elbow reached {_range_text(full, '°')} around release on attempts {_attempt_list(full)}.",
            why="A fully extended arm gives a consistent release line and lets the wrist finish the shot.",
            action="Keep it: hold the finish so this stays automatic as distance increases.",
            drills=[], supporting=full, total=len(pairs), metric_keys=["elbow_extension_peak_deg"]))
    return out


def _rule_leg_load(ctx):
    pairs = usable_values(ctx["attempts"], "knee_flexion_min_deg")
    out = []
    stiff = _majority(pairs, lambda v: v > 165)
    loaded = _majority(pairs, lambda v: 95 <= v <= 160)
    if stiff:
        out.append(dict(
            id="leg_load", kind="improvement", category="lower_body", priority=80,
            title="Very little knee bend before the shot",
            observed=f"The knees stayed nearly straight - deepest bend {_range_text(stiff, '°')} - on attempts {_attempt_list(stiff)}.",
            why="The legs normally supply most of the power for a shot. With little bend, the arms have to do more of the work, which tends to reduce range and repeatability.",
            action="'Dip, then rise': sink into a comfortable quarter-squat as the ball comes down, then let the legs start the shot.",
            drills=["dip_and_rise", "legs_then_arm"], supporting=stiff, total=len(pairs),
            success="Next session: a clearly visible knee bend (deepest knee angle under about 160°) on most attempts.",
            metric_keys=["knee_flexion_min_deg"]))
    elif loaded:
        out.append(dict(
            id="leg_load_good", kind="strength", category="lower_body", priority=35,
            title="Knees bend to load the shot",
            observed=f"A clear knee bend ({_range_text(loaded, '°')} at the deepest point) on attempts {_attempt_list(loaded)}.",
            why="Loading the legs lets them, not just the arms, power the shot.",
            action="Keep the same depth on every attempt; it should not change with distance.",
            drills=[], supporting=loaded, total=len(pairs), metric_keys=["knee_flexion_min_deg"]))
    return out


def _rule_sequencing(ctx):
    pairs = usable_values(ctx["attempts"], "sequencing_lag_ms")
    out = []
    early = _majority(pairs, lambda v: v < -40)
    good = _majority(pairs, lambda v: 0 <= v <= 250)
    if early:
        out.append(dict(
            id="sequencing", kind="improvement", category="timing", priority=70,
            title="Arm straightens before the legs drive",
            observed=f"The elbow's fastest straightening came {_range_text(early, 'ms').replace('-', '')} before the knees' on attempts {_attempt_list(early)}.",
            why="When the arm fires before the legs, the leg power arrives too late to help the ball, so the arm compensates.",
            action="Let the legs start the shot and the arm finish it: 'one' (legs), 'two' (arm).",
            drills=["legs_then_arm", "dip_and_rise"], supporting=early, total=len(pairs),
            success="Next session: legs-to-arm timing of zero or positive (legs first) on most attempts.",
            metric_keys=["sequencing_lag_ms"]))
    elif good:
        out.append(dict(
            id="sequencing_good", kind="strength", category="timing", priority=45,
            title="Legs lead, arm follows",
            observed=f"The knees straightened fastest {_range_text(good, 'ms')} before the elbow on attempts {_attempt_list(good)}.",
            why="Legs-then-arm timing lets the lower body contribute to the shot.",
            action="Keep the rhythm; check it again when shooting from further out.",
            drills=[], supporting=good, total=len(pairs), metric_keys=["sequencing_lag_ms"]))
    return out


def _rule_torso(ctx):
    pairs = usable_values(ctx["attempts"], "torso_lean_change_deg")
    out = []
    moving = _majority(pairs, lambda v: v > 15)
    stable = _majority(pairs, lambda v: v <= 8)
    direction = "sideways" if ctx["camera_view"] in ("frontal", "rear") else "forward/back"
    if moving:
        out.append(dict(
            id="torso", kind="improvement", category="torso", priority=75,
            title="Upper body moves a lot during the shot",
            observed=f"The torso angle changed by {_range_text(moving, '°')} ({direction} in this view) between the start and just after release on attempts {_attempt_list(moving)}.",
            why="A moving torso changes where the release happens from shot to shot and can pull the landing off balance.",
            action="Chest tall, head still: jump straight up and land where you took off.",
            drills=["tall_chest_form", "land_and_freeze"], supporting=moving, total=len(pairs),
            success="Next session: torso movement under about 12° on most attempts from the same camera position.",
            metric_keys=["torso_lean_change_deg"]))
    elif stable:
        out.append(dict(
            id="torso_good", kind="strength", category="torso", priority=40,
            title="Upper body stays stable",
            observed=f"Torso angle changed by only {_range_text(stable, '°')} during attempts {_attempt_list(stable)}.",
            why="A quiet upper body keeps the release point in the same place from shot to shot.",
            action="Keep it; it's a good base for adding distance.",
            drills=[], supporting=stable, total=len(pairs), metric_keys=["torso_lean_change_deg"]))
    return out


def _landing_pairs(ctx):
    """Per attempt, the larger of hip drift and landing offset (both usable values only)."""
    out = []
    for attempt in _active(ctx["attempts"]):
        best = None
        for key in ("hip_drift_ratio", "landing_offset_ratio"):
            record = attempt["metrics"].get(key)
            if record and record.get("confidence") in USABLE and record.get("value") is not None:
                if best is None or record["value"] > best["value"]:
                    best = record
        if best:
            out.append((attempt, best))
    return out


def _rule_landing(ctx):
    pairs = _landing_pairs(ctx)
    out = []
    away = _majority(pairs, lambda v: v > 0.5)
    close = _majority(pairs, lambda v: v <= 0.25)
    if away:
        directions = sorted({r.get("detail") for _, r in away if r.get("detail")})
        out.append(dict(
            id="landing", kind="improvement", category="balance", priority=90,
            title="Landing away from the take-off spot",
            observed=f"You landed {_range_text(away, 'torso lengths')} from where you took off"
                     f"{' (' + ', '.join(directions) + ')' if directions else ''} on attempts {_attempt_list(away)}.",
            why="Drifting during the shot changes the release from attempt to attempt, and repeated off-balance landings are worth cleaning up for comfort and control.",
            action="Take off and land in the same spot, on both feet, knees soft. Shorten the distance until that feels easy.",
            drills=["land_and_freeze", "tall_chest_form"], supporting=away, total=len(pairs),
            success="Next session: landing within about a quarter of a torso length of the take-off spot on most attempts.",
            metric_keys=["hip_drift_ratio", "landing_offset_ratio"]))
    elif close:
        out.append(dict(
            id="landing_good", kind="strength", category="balance", priority=50,
            title="Lands close to the take-off spot",
            observed=f"Landing within {_range_text(close, 'torso lengths')} of the take-off spot on attempts {_attempt_list(close)}.",
            why="Going straight up and down keeps the shot repeatable and the landing controlled.",
            action="Keep it as you add distance.",
            drills=[], supporting=close, total=len(pairs), metric_keys=["hip_drift_ratio", "landing_offset_ratio"]))
    return out


def _rule_follow_through(ctx):
    pairs = usable_values(ctx["attempts"], "follow_through_hold_ms")
    out = []
    short = _majority(pairs, lambda v: v < 250)
    held = _majority(pairs, lambda v: v >= 500)
    if short:
        out.append(dict(
            id="follow_through", kind="improvement", category="follow_through", priority=50,
            title="Follow-through drops quickly",
            observed=f"The shooting hand fell below shoulder height {_range_text(short, 'ms')} after release on attempts {_attempt_list(short)}.",
            why="Pulling the arm down early often goes with a rushed or pushed release; holding the finish is a simple check that the arm went up and through.",
            action="Hold the finish - arm up, wrist relaxed - until the ball reaches the rim.",
            drills=["follow_through_hold", "one_hand_form"], supporting=short, total=len(pairs),
            success="Next session: follow-through held for at least half a second on most attempts.",
            metric_keys=["follow_through_hold_ms"]))
    elif held:
        out.append(dict(
            id="follow_through_good", kind="strength", category="follow_through", priority=30,
            title="Holds the follow-through",
            observed=f"The shooting hand stayed above shoulder height for {_range_text(held, 'ms')} after release on attempts {_attempt_list(held)}.",
            why="A held finish shows the arm went up and through the ball.",
            action="Keep holding it.",
            drills=[], supporting=held, total=len(pairs), metric_keys=["follow_through_hold_ms"]))
    return out


def _rule_elbow_alignment(ctx):
    pairs = usable_values(ctx["attempts"], "elbow_flare_ratio")
    out = []
    flared = _majority(pairs, lambda v: v > 0.3)
    aligned = _majority(pairs, lambda v: abs(v) <= 0.15)
    if flared:
        out.append(dict(
            id="elbow_alignment", kind="improvement", category="alignment", priority=40,
            title="Shooting elbow sits outside the shoulder line",
            observed=f"At the set position the shooting elbow was {_range_text(flared, '× shoulder width')} outside the shoulder on attempts {_attempt_list(flared)}.",
            why="An elbow well outside the shoulder can send the ball off line. Some flare is normal and many good shooters turn their stance slightly, so treat this as something to check, not a rule.",
            action="Line the elbow up under the ball at the set point; a slight turn of the feet toward your shooting side can make this comfortable.",
            drills=["elbow_under_ball", "one_hand_form"], supporting=flared, total=len(pairs),
            success="Next session (front view): elbow within about 0.2 shoulder widths of the shoulder line on most attempts.",
            metric_keys=["elbow_flare_ratio"]))
    elif aligned:
        out.append(dict(
            id="elbow_alignment_good", kind="strength", category="alignment", priority=35,
            title="Elbow lines up under the ball",
            observed=f"At the set position the shooting elbow was within {_range_text(aligned, '× shoulder width')} of the shoulder line on attempts {_attempt_list(aligned)}.",
            why="An aligned elbow helps the ball travel on a straight line to the rim.",
            action="Keep it.", drills=[], supporting=aligned, total=len(pairs), metric_keys=["elbow_flare_ratio"]))
    return out


CONSISTENCY_KEYS = ["elbow_angle_release_deg", "release_height_ratio", "knee_flexion_min_deg",
                    "elbow_extension_peak_deg", "torso_lean_release_deg"]


def _rule_consistency(ctx):
    consistency = ctx["consistency"]
    variable = [consistency[k] for k in CONSISTENCY_KEYS if consistency.get(k, {}).get("rating") == "variable"]
    steady = [consistency[k] for k in CONSISTENCY_KEYS if consistency.get(k, {}).get("rating") == "consistent"]
    out = []

    def as_evidence(entries):
        return [{"attempt": None, "metric": e["key"], "label": e["label"], "value": e["sd"], "unit": e["unit"],
                 "display": f"mean {_fmt(e['mean'], e['unit'])}, SD {_fmt(e['sd'], e['unit'])}, range {_fmt(e['min'], e['unit'])}-{_fmt(e['max'], e['unit'])}, n={e['n']}",
                 "attempts": e["attempts"], "frame": None, "time_s": None, "confidence": "medium", "confirmed": None}
                for e in entries]

    if variable:
        names = ", ".join(e["label"].lower() for e in variable)
        n = min(e["n"] for e in variable)
        out.append(dict(
            id="consistency", kind="improvement", category="consistency", priority=55,
            title="The shot changes from attempt to attempt",
            observed=f"Across attempts, these varied the most: {names}.",
            why="Repeatable mechanics usually come before accuracy; when the dip, release or finish changes every time, misses are hard to correct.",
            action="Pick one cue from your top priority and use it on every attempt; shoot close until the attempts look the same.",
            drills=["same_shot_ladder"], evidence=as_evidence(variable),
            confidence="medium" if n >= 5 else "low",
            confidence_reason=f"Spread computed from {n}-{max(e['n'] for e in variable)} attempts with usable measurements" + ("" if n >= 5 else "; fewer than five, so treat as a first look") + ".",
            success="Next session: the same metrics' standard deviation reduced, filmed from the same spot.",
            metric_keys=[e["key"] for e in variable]))
    elif len(steady) >= 2:
        n = min(e["n"] for e in steady)
        out.append(dict(
            id="consistency_good", kind="strength", category="consistency", priority=45,
            title="Repeatable mechanics across attempts",
            observed="These stayed within a narrow range across attempts: " + ", ".join(e["label"].lower() for e in steady) + ".",
            why="Repeatable mechanics make misses easier to diagnose and fix.",
            action="Keep the same routine as you move back.", drills=[], evidence=as_evidence(steady),
            confidence="medium" if n >= 5 else "low",
            confidence_reason=f"Spread computed from {n} or more attempts with usable measurements" + ("" if n >= 5 else "; fewer than five, so treat as a first look") + ".",
            metric_keys=[e["key"] for e in steady]))
    return out


RULES: list[Callable[[dict], list[dict]]] = [
    _rule_landing, _rule_leg_load, _rule_torso, _rule_sequencing, _rule_arm_extension,
    _rule_consistency, _rule_follow_through, _rule_elbow_alignment,
]


def _finalize(raw, ctx):
    supporting = raw.pop("supporting", None)
    total = raw.pop("total", None)
    if supporting is not None:
        evidence = _evidence(supporting)
        confidence, reason = _finding_confidence(supporting, total or len(supporting))
        raw.setdefault("evidence", evidence)
        raw.setdefault("confidence", confidence)
        raw.setdefault("confidence_reason", reason)
        raw["affected"] = f"{len(supporting)} of {total} measured attempts"
    raw["timestamps"] = _times(raw.get("evidence", []))

    # Metric profile weighting and priority boost
    weights = ctx.get("weights", {})
    metric_keys = raw.get("metric_keys", [])

    def _lookup_weight(k):
        if k in weights:
            return weights[k]
        from basketball.analysis.shooting_analysis import METRIC_ALIASES
        for alias_k, canonical_k in METRIC_ALIASES.items():
            if k == canonical_k and alias_k in weights:
                return weights[alias_k]
            if k == alias_k and canonical_k in weights:
                return weights[canonical_k]
        if k in ("landing_offset_ratio", "hip_drift_ratio") and "landing_displacement" in weights:
            return weights["landing_displacement"]
        if k in ("torso_lean_change_deg", "torso_lean_release_deg") and "torso_lean_deg" in weights:
            return weights["torso_lean_deg"]
        return 0.0

    weight = max((_lookup_weight(k) for k in metric_keys), default=0.0)
    base_priority = raw.get("priority", 50)
    raw["priority"] = round(base_priority * (1.0 + weight * 2.0), 2)
    raw["weight"] = weight

    # Experimental metrics check (e.g. arc_proxy, wrist_snap_proxy)
    has_experimental = any(k in ("arc_proxy", "wrist_snap_proxy") for k in metric_keys)
    if has_experimental:
        if not raw["title"].startswith("[experimental"):
            raw["title"] = f"[experimental - ball tracking required] {raw['title']}"
        raw["action"] = "Advisory only (single-camera estimate). Ball tracking is experimental; check replay rather than making technical changes based on this alone."
        raw["why"] = raw["why"] + " Note: This proxy is experimental and requires precise ball tracking; it is advisory only."

    # Associate metrics metadata and confidence with every drill
    raw["drills"] = [{"id": d, **{k: v for k, v in DRILLS[d].items() if k != "dose"},
                      "dose": DRILLS[d]["dose"].get(ctx["skill"], DRILLS[d]["dose"]["intermediate"]),
                      "related_metrics": [
                          f"{METRIC_DEFINITIONS.get(k, {}).get('label', k)} ({METRIC_DEFINITIONS.get(k, {}).get('unit', '')})".strip()
                          for k in metric_keys
                      ],
                      "measurement_confidence": raw.get("confidence", "medium")}
                     for d in raw.get("drills", [])]
    limitations = []
    for key in raw.get("metric_keys", []):
        definition = METRIC_DEFINITIONS.get(key)
        if definition:
            limitations.append(f"{definition['label']}: {definition['limitation']}")
    limitations.append("Thresholds are coaching heuristics for this prototype, not validated norms.")
    raw["limitations"] = limitations

    # Every single recommendation displays metric (with label and unit), attempt(s), timestamps/frames, and confidence
    raw["questions"] = {
        "what": raw["observed"],
        "evidence": "; ".join(f"attempt {e['attempt']} at {e['time_s']:.2f} s: {e['label']} {e['display']} ({e['confidence']} confidence)"
                              if e.get("attempt") and e.get("time_s") is not None else e.get("display", "")
                              for e in raw.get("evidence", [])[:6]),
        "why": raw["why"], "change": raw["action"],
        "practice": "; ".join(f"{d['name']} - {d['dose']}" for d in raw["drills"]) or "No change needed; keep doing it.",
    }
    return raw


def build_findings(analysis: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    raw_shot_type = analysis.get("shot_type_id") or profile.get("shot_type_id") or analysis.get("shot_type") or "catch_and_shoot"
    from basketball.configs.shot_types import resolve_shot_type_alias, get_shot_type
    shot_type_id = resolve_shot_type_alias(raw_shot_type)
    shot_type_cfg = get_shot_type(shot_type_id)
    metric_profile = shot_type_cfg.get("metric_profile", {})
    weights = metric_profile.get("weights", {})
    min_clip = shot_type_cfg.get("min_clip_requirements", {})

    ctx = {
        "attempts": analysis.get("attempts", []),
        "consistency": analysis.get("consistency", {}),
        "camera_view": analysis.get("camera_view"),
        "skill": profile.get("skill_level") if profile.get("skill_level") in SKILL_SETTINGS else "intermediate",
        "shot_style": profile.get("shot_style", "jump_shot"),
        "shot_type_id": shot_type_id,
        "weights": weights,
        "min_clip_requirements": min_clip,
        "metric_profile": metric_profile,
    }
    findings = []
    for rule in RULES:
        for raw in rule(ctx):
            findings.append(_finalize(raw, ctx))
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f["confidence"]], -f["priority"]))
    strengths = [f for f in findings if f["kind"] == "strength"]
    improvements = [f for f in findings if f["kind"] == "improvement"]
    confident = lambda items: [f for f in items if f["confidence"] in {"high", "medium"}]

    not_evaluated = []
    active = _active(ctx["attempts"])
    if len(active) == 0:
        not_evaluated.append({
            "metric": "all",
            "label": "All metrics",
            "reason": "not enough evidence to evaluate shooting mechanics (no approved attempts)",
        })
    else:
        for k in weights.keys():
            m_def = METRIC_DEFINITIONS.get(k, {})
            label = m_def.get("label", k)
            unit = m_def.get("unit", "")
            has_usable = any(
                attempt.get("metrics", {}).get(k, {}).get("confidence") in USABLE
                and attempt.get("metrics", {}).get(k, {}).get("value") is not None
                for attempt in active
            )
            if not has_usable:
                lbl_str = f"{label} ({unit})".strip() if unit else label
                not_evaluated.append({
                    "metric": k,
                    "label": label,
                    "reason": f"not enough evidence to evaluate {lbl_str}: fewer than required attempts or low tracking confidence",
                })

    return {
        "version": COACH_VERSION,
        "shot_type_id": shot_type_id,
        "findings": findings,
        "strengths": strengths,
        "improvements": improvements,
        "top_strengths": confident(strengths)[:3],
        "top_improvements": confident(improvements)[:3],
        "possible_issues": [f for f in improvements if f["confidence"] == "low"][:3],
        "not_evaluated": not_evaluated,
        "advisory_note": "Single-camera pose is an estimate. Analysis is advisory and prototype.",
    }


def first_focus(coaching: dict[str, Any]) -> Optional[dict[str, Any]]:
    candidates = coaching["top_improvements"] or coaching["possible_issues"]
    if not candidates:
        return None
    # Most certain first; within the same confidence level, foundations (balance, legs) first.
    rank = {"high": 2, "medium": 1, "low": 0}
    best = max(rank[f["confidence"]] for f in candidates)
    top = max((f for f in candidates if rank[f["confidence"]] == best), key=lambda f: f["priority"])
    foundation = {"balance": "balance and landing are the base every other correction is built on",
                  "lower_body": "the legs power the shot, so fixing them often improves the arm action too",
                  "torso": "a stable upper body keeps the release point in one place",
                  "timing": "timing ties the legs and arm together",
                  "release": "the release decides where the ball goes",
                  "consistency": "a repeatable motion makes every other fix easier to judge",
                  "follow_through": "it is a quick, visible check of the release",
                  "alignment": "alignment affects the ball's line"}
    reason = (f"It was seen in {top.get('affected', 'several attempts')} ({top['confidence']} confidence), "
              f"and {foundation.get(top['category'], 'it has the biggest expected effect')}.")
    if top["confidence"] == "low":
        reason += " Confidence is low, so check it in the replay before changing anything."
    return {"finding_id": top["id"], "title": top["title"], "action": top["action"], "reason": reason}


# --------------------------------------------------------------------------- practice plan
def build_practice_plan(coaching: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    skill = profile.get("skill_level") if profile.get("skill_level") in SKILL_SETTINGS else "intermediate"
    settings = SKILL_SETTINGS[skill]
    priorities = (coaching["top_improvements"] or coaching["possible_issues"])[:3]
    drill_ids = []
    for finding in priorities:
        for drill in finding["drills"]:
            if drill["id"] not in drill_ids:
                drill_ids.append(drill["id"])
    if not drill_ids:
        drill_ids = ["one_hand_form", "same_shot_ladder"]
    balance_needed = any(f["category"] in {"balance", "torso"} for f in priorities)
    blocks = [
        {"name": "Warm-up", "minutes": "8-10",
         "content": "Easy jog or skipping, leg swings, walking lunges, bodyweight squats, arm circles, then 10 relaxed one-hand shots at the rim."},
        {"name": "Form shooting (1-2 m)", "minutes": "10",
         "content": "; ".join(f"{DRILLS[d]['name']}: {DRILLS[d]['dose'].get(skill)}" for d in drill_ids[:2])},
    ]
    if balance_needed and "land_and_freeze" not in drill_ids[:2]:
        blocks.append({"name": "Balance and landing", "minutes": "5-8",
                       "content": f"{DRILLS['land_and_freeze']['name']}: {DRILLS['land_and_freeze']['dose'].get(skill)}. Add single-leg balance holds, 3 × 20 s per leg."})
    blocks.append({"name": "Close-range shooting with your cue", "minutes": "10",
                   "content": "Three spots 2-3 m from the rim, 5-10 shots each, using only your top cue: "
                              + (priorities[0]["action"] if priorities else "the same dip and finish every time.")})
    blocks.append({"name": "Progression", "minutes": "5-10",
                   "content": f"{DRILLS['same_shot_ladder']['name']}: move back one step only when 4 of 5 shots keep the cue. Stop the block when form breaks down."})
    blocks.append({"name": "Cool-down", "minutes": "5", "content": "Walk, light calf, quad, hip and shoulder stretches."})
    checklist = [f["action"] for f in priorities] + ["Landed on both feet, balanced, near the take-off spot.",
                                                     "No pain during or after the session."]
    compare_keys = []
    for f in priorities:
        compare_keys.extend(k for k in f.get("metric_keys", []) if k not in compare_keys)
    for key in ("elbow_extension_peak_deg", "knee_flexion_min_deg", "torso_lean_change_deg", "hip_drift_ratio"):
        if key not in compare_keys:
            compare_keys.append(key)
    consistency = analysis.get("consistency", {})
    baseline = [{"key": k, "label": METRIC_DEFINITIONS[k]["label"], "unit": METRIC_DEFINITIONS[k]["unit"],
                 "mean": consistency.get(k, {}).get("mean"), "sd": consistency.get(k, {}).get("sd"),
                 "n": consistency.get(k, {}).get("n", 0)} for k in compare_keys[:6]]
    return {
        "skill_level": skill,
        "frequency": settings["sessions"], "session_length": settings["minutes"],
        "volume_guidance": f"Up to about {settings['shot_cap']} shots per session to start. Increase volume in small steps from week to week, and only while the cue still holds and nothing hurts.",
        "rest": "Leave at least one easier or rest day between hard shooting days.",
        "blocks": blocks,
        "schedule": [
            {"week": "Week 1", "focus": "Close range only (1-3 m). Learn the cue at slow tempo."},
            {"week": "Week 2", "focus": "Same drills; start the ladder. Move back a step only after the checklist is met."},
            {"week": "Week 3", "focus": "Normal shooting distance for part of the session; keep the form block first. Record a new video."},
        ],
        "checklist": checklist,
        "comparison_method": [
            "Film from the same spot, height and camera view as this session.",
            "Same shot type and distance, similar lighting, one shooter in frame.",
            "Record at least five attempts and confirm them in Review.",
            "Compare the baseline metrics below; a change smaller than the spread (SD) here may just be normal variation.",
        ],
        "baseline_metrics": baseline,
    }


# --------------------------------------------------------------------------- injury-risk reduction
INJURY_TITLE = "Technique, Load Management, and Injury-Risk Reduction"

GENERAL_GUIDANCE = [
    {"topic": "Warm up first", "text": "Spend 8-10 minutes raising your heart rate and moving hips, knees, ankles and shoulders through their range before shooting hard or jumping."},
    {"topic": "Progress gradually", "text": "Increase shot volume, distance and intensity in small steps from week to week. Avoid sudden jumps in how much you practise."},
    {"topic": "Quality before quantity", "text": "Practise the movement well at close range before adding repetitions or distance."},
    {"topic": "Strength and conditioning", "text": "Regular lower-body (squats, lunges, calf raises), trunk and shoulder strength work supports controlled take-offs and landings. A qualified coach can tailor this to you."},
    {"topic": "Balanced take-off and landing", "text": "Aim to take off and land on both feet with soft knees, near the same spot."},
    {"topic": "Watch for fatigue", "text": "If your form changes late in a session (shorter follow-through, more drift, less knee bend), shorten the session or switch to close-range form work."},
    {"topic": "Rest and recovery", "text": "Plan easier days, sleep well, and avoid stacking many high-volume sessions back to back."},
    {"topic": "Comfortable motion", "text": "Use a smooth shooting motion that feels comfortable. Never force a joint into a position that hurts to match a 'perfect' form."},
]

INJURY_LIMITS = [
    "This is not a medical assessment. A single video cannot diagnose an injury or predict whether one will happen.",
    "Two-dimensional pose estimation cannot measure joint forces, loads or tissue stress; angles are image-based estimates.",
    "No injury-risk score is given because none could be validated from this footage.",
    "Normal differences in body shape and movement are not defects; a movement is only mentioned if it was clearly measured.",
]

PAIN_ADVICE = ("If you feel pain, lasting discomfort, have a previous injury, or have restricted movement, stop or modify "
               "the activity that hurts and get advice from a qualified healthcare professional such as a doctor or sports "
               "physiotherapist. For individual technique advice, work with a qualified basketball coach.")


def build_injury_section(analysis: dict[str, Any], coaching: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    ctx = {"attempts": analysis.get("attempts", []), "camera_view": analysis.get("camera_view")}
    observations = []
    landing = _majority(_landing_pairs(ctx), lambda v: v > 0.5)
    if landing:
        observations.append({
            "title": "Landings away from the take-off spot",
            "shows": f"On attempts {_attempt_list(landing)} you landed {_range_text(landing, 'torso lengths')} from where you took off.",
            "why": "Repeated landings while moving sideways or forward ask more of the ankles, knees and hips to stop the body, and they make the shot less repeatable.",
            "modification": "Practise controlled, balanced two-foot landings at low intensity (Land-and-freeze, 1-2 m) before increasing distance or volume.",
            "cannot_conclude": "The video cannot show whether these landings stress any joint or will lead to injury.",
            "evidence": _evidence(landing), "timestamps": _times(_evidence(landing)),
        })
    if ctx["camera_view"] in ("frontal", "rear"):
        lateral = _majority(usable_values(ctx["attempts"], "torso_lean_release_deg"), lambda v: v > 10)
        if lateral:
            observations.append({
                "title": "Sideways torso lean at release",
                "shows": f"The torso leaned {_range_text(lateral, '°')} sideways at release on attempts {_attempt_list(lateral)}.",
                "why": "A large sideways lean shifts weight to one leg on landing and changes the release line.",
                "modification": "Use Tall-chest form shooting at close range and land on both feet; add trunk strength work.",
                "cannot_conclude": "Camera tilt can add a few degrees, and the footage cannot show spinal loading or predict injury.",
                "evidence": _evidence(lateral), "timestamps": _times(_evidence(lateral)),
            })
        knees = _majority(usable_values(ctx["attempts"], "knee_inward_ratio"), lambda v: v > 0.25)
        if knees:
            observations.append({
                "title": "Knees moving inside the hip-to-ankle line at the dip",
                "shows": f"At the deepest knee bend, a knee sat {_range_text(knees, '× hip width')} inside the line from hip to ankle on attempts {_attempt_list(knees)}.",
                "why": "Many coaches cue knees to track over the toes during take-off and landing, because control in this position is trainable.",
                "modification": "Slow bodyweight squats and landings with the knees tracking over the toes, at low intensity; a qualified coach or physiotherapist can check this in person.",
                "cannot_conclude": "This is a 2D front-view estimate. It cannot measure knee load, and it does not mean an injury will occur.",
                "evidence": _evidence(knees), "timestamps": _times(_evidence(knees)),
            })
    torso_change = [f for f in coaching["improvements"] if f["id"] == "torso" and f["confidence"] != "low"]
    if torso_change and not any(o["title"].startswith("Sideways") for o in observations):
        f = torso_change[0]
        observations.append({
            "title": "Large upper-body movement during the shot",
            "shows": f["observed"],
            "why": "A lot of trunk movement during take-off and landing can make landings less controlled.",
            "modification": "Tall-chest form shooting at close range before adding distance; include trunk strength work.",
            "cannot_conclude": "The footage cannot show spinal loading and does not predict injury.",
            "evidence": f["evidence"], "timestamps": f["timestamps"],
        })
    pain = bool(profile.get("pain_reported"))
    return {
        "title": INJURY_TITLE,
        "pain_reported": pain,
        "pain_advice": PAIN_ADVICE,
        "observations": observations,
        "no_observation_note": None if observations else
            "No take-off, landing or posture pattern was clearly measured as worth flagging in this footage. The general guidance below still applies.",
        "general_guidance": GENERAL_GUIDANCE,
        "limits": INJURY_LIMITS,
    }


def evaluate_attempt(attempt: dict[str, Any]) -> dict[str, list[str]]:
    """Short per-attempt strengths/opportunities using the same thresholds as the session rules."""
    m = attempt["metrics"]

    def val(key):
        r = m.get(key) or {}
        return r.get("value") if r.get("confidence") in USABLE else None

    strengths, opportunities = [], []
    ext = val("elbow_extension_peak_deg")
    if ext is not None:
        (strengths if ext >= 160 else opportunities if ext < 150 else []).append(
            f"Arm extension {ext:.0f}°" + (" - full" if ext >= 160 else " - stays bent" if ext < 150 else ""))
    knee = val("knee_flexion_min_deg")
    if knee is not None:
        if knee > 165:
            opportunities.append(f"Little knee bend (deepest {knee:.0f}°)")
        elif 95 <= knee <= 160:
            strengths.append(f"Knee bend to {knee:.0f}°")
    lag = val("sequencing_lag_ms")
    if lag is not None:
        if lag < -40:
            opportunities.append(f"Arm before legs ({abs(lag):.0f} ms early)")
        elif 0 <= lag <= 250:
            strengths.append(f"Legs lead arm by {lag:.0f} ms")
    torso = val("torso_lean_change_deg")
    if torso is not None:
        if torso > 15:
            opportunities.append(f"Torso moved {torso:.0f}°")
        elif torso <= 8:
            strengths.append(f"Stable torso ({torso:.0f}° change)")
    landing = [v for v in (val("hip_drift_ratio"), val("landing_offset_ratio")) if v is not None]
    if landing:
        worst = max(landing)
        if worst > 0.5:
            opportunities.append(f"Landed {worst:.2f} torso lengths from take-off")
        elif worst <= 0.25:
            strengths.append("Landed near take-off spot")
    hold = val("follow_through_hold_ms")
    if hold is not None:
        if hold < 250:
            opportunities.append(f"Follow-through held {hold:.0f} ms")
        elif hold >= 500:
            strengths.append(f"Follow-through held {hold:.0f} ms")
    return {"strengths": strengths, "opportunities": opportunities}
