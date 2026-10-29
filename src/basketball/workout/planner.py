"""Deterministic, report-driven workout planner.

Inputs: the persisted shooting report for ONE session, the user's equipment and preferences, and
the exercise catalog. Output: an ordered plan (warm-up, main block, cool-down) whose duration is
calculated from its own sets, work periods and rests, and is never below 20 minutes.

Rules of honesty built in here:
* Only findings from the given report are used; low-confidence findings are down-weighted and
  labelled "possible".
* The report never measures jump height, shooting power or fitness; the plan says so instead of
  implying it.
* If no finding supports a focus area, exercises are labelled as coming from the user's stated
  goal or as general basketball-support work.
* Equipment, fitness level, reported pain and movements to avoid are hard filters.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from basketball.workout.catalog import LEVELS

PLAN_VERSION = "workout-planner-1.0"
MIN_DURATION_S = 20 * 60
DURATION_CHOICES = (20, 25, 30, 35, 40, 45, 50, 60)
GOALS = {
    "jump": "Jumping and leg power",
    "stamina": "Stamina and conditioning",
    "upper": "Upper-body strength",
    "mobility": "Mobility",
}
AVOID = {
    "knee": "Knee-heavy movements",
    "lower_back": "Lower-back loading",
    "shoulder": "Shoulder-loading movements",
    "overhead": "Overhead positions",
    "wrist": "Weight on the wrists",
    "ankle": "Ankle-loading movements",
    "floor": "Getting down on the floor or kneeling",
    "jumping": "Jumping or impact",
}
CONF_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.3}
IMPACT_ORDER = ["none", "low", "moderate", "high"]

# Which training areas a report finding can motivate, and how strongly.
FINDING_AREAS = {
    "leg_load": {"lower_strength": 1.0, "mobility": 0.3},
    "sequencing": {"hip_drive": 1.0, "lower_strength": 0.5},
    "torso": {"core": 1.0, "balance": 0.3},
    "landing": {"balance": 1.0, "core": 0.3},
    "consistency": {"core": 0.6, "balance": 0.5},
    "arm_extension": {"shoulder": 0.6, "arm": 0.6},
    "elbow_alignment": {"shoulder": 0.8},
}
TECHNIQUE_ONLY = {"follow_through": "Follow-through is a timing and habit cue; it is practised on court (hold the finish), not with gym exercises."}
GOAL_AREAS = {
    "jump": {"lower_strength": 0.9, "hip_drive": 0.5, "power_low": 0.6},
    "stamina": {"conditioning": 0.9},
    "upper": {"upper_push": 0.9, "shoulder": 0.4},
    "mobility": {"mobility": 0.8},
}

# Why an area can help, and what the report cannot establish about it.
AREA_BENEFIT = {
    "lower_strength": "Builds leg strength and a controlled knee and hip bend, so the legs can contribute more to the shot.",
    "hip_drive": "Trains the hips and legs to extend powerfully, the movement that starts a jump shot from the floor.",
    "core": "Practises keeping the trunk steady while the arms and legs move, which supports a repeatable release position.",
    "balance": "Trains single-leg control of the knee, hip and ankle, which supports balanced take-offs and landings.",
    "shoulder": "Strengthens the muscles that hold the shoulder blade and upper arm in position, supporting a consistent shooting-arm line.",
    "arm": "Builds strength through elbow extension, the motion that finishes the shot.",
    "upper_push": "General upper-body strength you asked for; it supports physical play and holding positions.",
    "conditioning": "Builds stamina you asked for, so technique holds up later in a session.",
    "mobility": "Keeps the hips, ankles and upper back moving comfortably.",
    "power_low": "Low-intensity elastic work for the ankles and calves, progressed carefully before any harder jumping.",
}
FINDING_LIMIT = {
    "leg_load": "The report measured knee bend from 2D video. It does not show that your legs are weak; a straight-legged shot is often a habit, so practise the 'dip, then rise' cue on court too. Jump height is not measured by this app.",
    "sequencing": "Legs-to-arm timing is estimated from joint speeds in 2D video. It shows the order of movement, not muscle strength; timing is also practised on court.",
    "torso": "Torso angle is measured in the image plane. The report does not establish that a core weakness causes the movement; habit, balance and footwork can all play a part.",
    "landing": "Landing position is estimated relative to your body size in the image. It does not establish a balance deficit or any injury risk.",
    "consistency": "Variation between attempts can come from technique, fatigue, distance or camera position, not only strength or balance.",
    "arm_extension": "Elbow extension at release is mostly a technique pattern; strength work supports it but the change itself happens on court.",
    "elbow_alignment": "Elbow position is measured from one camera view and depends on your natural build and grip; it is not a defect to correct with strength alone.",
}
NOT_ASSESSED = [
    "Jump height is not measured by Shot Lab, so the plan does not claim to fix a jumping deficit.",
    "Shooting power is not measured; a shot that looks short can come from technique, distance or timing, not only strength.",
    "Fitness and stamina are not measured from a short shooting clip; conditioning work is included only if you ask for it.",
]
SAFETY_NOTES = [
    "This workout supports general strength, movement quality and conditioning. It is not a substitute for advice from a qualified coach, physiotherapist or healthcare professional.",
    "Stop any exercise that causes pain. Never push through pain; use the easier version or skip it.",
    "Choose loads and ranges you can control for every repetition, and keep good form over speed.",
    "The rep counter is a guided pace: it counts the planned repetitions, it does not detect or verify your movement.",
]
PAIN_NOTE = ("You told us you have pain, an injury or a movement limitation. This plan avoids impact and heavier loading and uses "
             "beginner volumes, but it is not rehabilitation. Please get it assessed by a physiotherapist or doctor before "
             "training through it, and stop anything that hurts.")

MAX_SETS = {"beginner": 3, "intermediate": 4, "advanced": 4}
MAIN_EXERCISES_FOR = [(20, 4), (25, 5), (30, 5), (40, 6), (60, 7)]
OVERSHOOT_TOLERANCE_S = 180  # trim plans that exceed the requested length by more than this


# --------------------------------------------------------------------------- preferences
def validate_preferences(raw: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Normalise and validate the user's choices; raise ValueError with a user-facing message."""
    if not isinstance(raw, dict):
        raise ValueError("Preferences must be a JSON object.")
    equipment = raw.get("equipment")
    if not isinstance(equipment, list) or not equipment:
        raise ValueError("Select at least one type of equipment (choose Bodyweight if you have none).")
    equipment = sorted({str(item) for item in equipment})
    unknown = [item for item in equipment if item not in catalog["equipment"]]
    if unknown:
        raise ValueError(f"Unknown equipment: {', '.join(unknown)}.")
    level = raw.get("fitness_level", "beginner")
    if level not in LEVELS:
        raise ValueError("Fitness level must be beginner, intermediate or advanced.")
    try:
        duration = int(raw.get("duration_min", 20))
    except (TypeError, ValueError):
        raise ValueError("Workout duration must be a whole number of minutes.")
    if duration < 20:
        raise ValueError("Workouts are planned for at least 20 minutes.")
    if duration > 60:
        raise ValueError("Choose a workout of 60 minutes or less.")
    avoid = raw.get("avoid") or []
    if not isinstance(avoid, list) or any(item not in AVOID for item in avoid):
        raise ValueError("Unknown movement limitation.")
    goals = raw.get("goals") or []
    if not isinstance(goals, list) or any(item not in GOALS for item in goals):
        raise ValueError("Unknown workout goal.")
    notes = str(raw.get("limitations_note") or "")[:300]
    return {
        "equipment": equipment, "fitness_level": level, "duration_min": duration,
        "avoid": sorted(set(avoid)), "pain": bool(raw.get("pain")), "goals": sorted(set(goals)),
        "limitations_note": notes,
    }


# --------------------------------------------------------------------------- report findings
def extract_findings(report: dict[str, Any]) -> dict[str, Any]:
    """Summarise the report's findings that matter for training, keeping evidence and limits."""
    findings = report.get("findings") or []
    used, strengths, technique = [], [], []
    for finding in findings:
        entry = {
            "id": finding.get("id"), "title": finding.get("title"), "kind": finding.get("kind"),
            "category": finding.get("category"), "confidence": finding.get("confidence"),
            "confidence_reason": finding.get("confidence_reason"), "observed": finding.get("observed"),
            "affected": finding.get("affected"),
            "timestamps": [{"attempt": t.get("attempt"), "time_s": t.get("time_s"), "label": t.get("label")}
                           for t in (finding.get("timestamps") or [])[:4]],
            "limitations": list(finding.get("limitations") or [])[:4],
        }
        if finding.get("kind") == "strength":
            if finding.get("confidence") in ("high", "medium"):
                strengths.append(entry)
            continue
        if finding.get("id") in TECHNIQUE_ONLY:
            entry["note"] = TECHNIQUE_ONLY[finding["id"]]
            technique.append(entry)
            continue
        if finding.get("id") in FINDING_AREAS and finding.get("confidence") in CONF_WEIGHT:
            entry["possible"] = finding.get("confidence") == "low"
            entry["training_note"] = FINDING_LIMIT.get(finding["id"])
            used.append(entry)
    overview = report.get("overview") or {}
    meta = report.get("meta") or {}
    uncertainty = list((overview.get("limitations") or [])[:4])
    return {
        "session_id": meta.get("session_id"), "player_id": meta.get("player_id"),
        "session_date": overview.get("session_date"), "video_filename": overview.get("video_filename"),
        "report_generated_at": meta.get("generated_at"), "analysis_status": overview.get("analysis_status"),
        "skill_level": overview.get("skill_level"), "improvements": used, "strengths": strengths,
        "technique_only": technique, "uncertainty": uncertainty, "not_assessed": NOT_ASSESSED,
        "attempts_total": overview.get("attempts_total"), "attempts_confirmed": overview.get("attempts_confirmed"),
    }


def summary_sentence(extracted: dict[str, Any], catalog: dict[str, Any]) -> str:
    """One or two sentences, built from the actual findings, explaining why a workout is suggested."""
    confident = [f for f in extracted["improvements"] if not f.get("possible")]
    possible = [f for f in extracted["improvements"] if f.get("possible")]
    if confident:
        titles = [f["title"].rstrip(".").lower() for f in confident[:2]]
        areas = []
        for finding in confident[:2]:
            for area, weight in sorted(FINDING_AREAS[finding["id"]].items(), key=lambda kv: -kv[1]):
                label = catalog["areas"][area].lower()
                if weight >= 0.6 and label not in areas:
                    areas.append(label)
        text = f"Your shooting analysis found: {' and '.join(titles)} ({confident[0]['affected']}). "
        text += f"This workout focuses on {', '.join(areas[:3])} to support that, alongside your on-court practice."
        return text
    if possible:
        return (f"Your report only suggests a possible issue ({possible[0]['title'].lower()}, low confidence). "
                "The workout treats it as a low priority; add your own goals or film a clearer clip for a more personal plan.")
    return ("Your report has no improvement area supported with enough confidence to personalise training. "
            "The workout below is general basketball-support work, plus any goals you choose.")


# --------------------------------------------------------------------------- selection
def _family(exercise_id: str) -> str:
    for token, family in (("split_squat", "split"), ("lunge", "split"), ("step_up", "step"), ("step_down", "step"),
                          ("pistol", "split"), ("squat", "squat"), ("leg_press", "squat"), ("rdl", "hinge"),
                          ("deadlift", "hinge"), ("hip_thrust", "bridge"), ("glute_bridge", "bridge"),
                          ("calf", "calf"), ("face_pull", "rear_shoulder"), ("reverse_fly", "rear_shoulder"),
                          ("external_rotation", "cuff"), ("row", "row"), ("tricep", "triceps"),
                          ("push_up", "push"), ("press", "push"), ("plank", "plank"), ("side_bridge", "side"),
                          ("dead_bug", "dead_bug"), ("pallof", "anti_rotation"), ("body_saw", "plank")):
        if token in exercise_id:
            return family
    return exercise_id


def _eligible(exercise: dict, prefs: dict, phase: str) -> bool:
    if phase not in exercise["phases"]:
        return False
    if phase == "main" and exercise["equipment"] not in prefs["equipment"]:
        return False
    if phase in ("warmup", "cooldown") and not (exercise.get("equipment_free") or exercise["equipment"] in prefs["equipment"]):
        return False
    if LEVELS.index(exercise["min_level"]) > LEVELS.index(prefs["fitness_level"]):
        return False
    impact = IMPACT_ORDER.index(exercise["impact"])
    if prefs["pain"] and impact > IMPACT_ORDER.index("low"):
        return False
    if "jumping" in prefs["avoid"] and impact > IMPACT_ORDER.index("low"):
        return False
    if prefs["fitness_level"] == "beginner" and impact >= IMPACT_ORDER.index("high"):
        return False
    if set(exercise.get("stresses", [])) & set(prefs["avoid"]):
        return False
    if prefs["pain"] and exercise["kind"] == "strength_compound" and exercise["equipment"] in ("barbell", "smith"):
        return False
    return True


def _rank(exercise: dict, area: str, prefs: dict, video_available) -> float:
    score = 0.0
    if exercise.get("video") and video_available(exercise["id"]):
        score += 2.0
    if exercise["areas"][0] == area:
        score += 1.5
    level_gap = LEVELS.index(prefs["fitness_level"]) - LEVELS.index(exercise["min_level"])
    score += 0.5 if level_gap == 0 else (0.2 if level_gap == 1 else 0.0)
    loaded = exercise["equipment"] not in ("bodyweight", "stretching")
    if area in ("lower_strength", "hip_drive", "upper_push", "arm") and loaded:
        score += 0.7 if prefs["fitness_level"] != "beginner" else 0.2
    if prefs["fitness_level"] == "beginner" and exercise["equipment"] in ("bodyweight", "band", "trx", "machine"):
        score += 0.3
    if prefs["pain"] and exercise["impact"] == "none":
        score += 0.3
    return score


def _area_scores(extracted: dict, prefs: dict) -> dict[str, dict]:
    areas: dict[str, dict] = {}

    def add(area, value, source):
        entry = areas.setdefault(area, {"score": 0.0, "sources": []})
        entry["score"] += value
        entry["sources"].append(source)

    for finding in extracted["improvements"]:
        weight = CONF_WEIGHT[finding["confidence"]]
        for area, strength in FINDING_AREAS[finding["id"]].items():
            add(area, strength * weight, {"type": "finding", "id": finding["id"], "title": finding["title"],
                                          "confidence": finding["confidence"], "possible": finding.get("possible", False),
                                          "affected": finding.get("affected"), "weight": round(strength * weight, 3)})
    for goal in prefs["goals"]:
        for area, strength in GOAL_AREAS[goal].items():
            add(area, strength, {"type": "goal", "id": goal, "title": GOALS[goal], "weight": strength})
    if "stretching" in prefs["equipment"]:
        add("mobility", 0.5, {"type": "equipment", "id": "stretching", "title": "You selected stretching and mobility", "weight": 0.5})
    return areas


def _dose(exercise: dict, catalog: dict, prefs: dict) -> dict:
    level = "beginner" if prefs["pain"] else prefs["fitness_level"]
    base = dict(catalog["dosing"][exercise["kind"]][level])
    cadence = float(catalog["cadence_seconds_per_rep"].get(exercise["kind"], 3.0))
    if exercise["mode"] == "time":
        target = int(base.get("seconds", 30))
        work = target * (2 if exercise["per_side"] else 1)
    else:
        target = int(base.get("reps", 10))
        work = int(math.ceil(target * cadence * (2 if exercise["per_side"] else 1)))
    sets = int(base["sets"])
    if prefs["pain"]:
        sets = min(sets, 2)
    return {"sets": sets, "target": target, "cadence_s": cadence, "work_s": work,
            "rest_between_sets_s": int(base["rest_between_sets"]), "rest_after_s": int(base["rest_after"])}


def item_duration(item: dict) -> int:
    """Planned seconds for one plan item: all sets, the rests between sets, and the rest after it."""
    return item["sets"] * item["work_s"] + (item["sets"] - 1) * item["rest_between_sets_s"] + item["rest_after_s"]


def plan_duration(items: list[dict]) -> dict[str, int]:
    """Total planned duration of a plan, by phase, with work and rest separated (no double counting)."""
    totals = {"warmup_s": 0, "main_s": 0, "cooldown_s": 0, "work_s": 0, "rest_s": 0}
    for item in items:
        seconds = item_duration(item)
        totals[f"{item['phase']}_s"] += seconds
        totals["work_s"] += item["sets"] * item["work_s"]
        totals["rest_s"] += (item["sets"] - 1) * item["rest_between_sets_s"] + item["rest_after_s"]
    totals["total_s"] = totals["warmup_s"] + totals["main_s"] + totals["cooldown_s"]
    return totals


HEAVY_EQUIPMENT = {"barbell", "smith", "machine"}
REST_CAP_BETWEEN_S = 180
REST_CAP_AFTER_S = 120


def _finalize_rest(items: list[dict], prefs: dict) -> None:
    """Exercise-specific rest. The catalog gives a base rest per exercise type and fitness level
    (``dosing``); it is then adjusted for intensity and volume:

    * +15 s between sets for moderate/high-impact work (landing and plyometric stress);
    * +15 s between sets for compound strength with heavier external load (barbell, Smith, machine);
    * +10 s between sets when an exercise has 4 or more sets (accumulated fatigue);
    * +15 s between sets and after the exercise when pain or a limitation was reported.

    Capped at 180 s between sets and 120 s after an exercise. Single-set items (warm-up drills,
    stretches) keep their short transition rest.
    """
    for item in items:
        between = int(item["_rest_between_base"])
        after = int(item["_rest_after_base"])
        reasons = []
        if item["sets"] > 1 and between > 0:
            if item["impact"] in ("moderate", "high"):
                between += 15
                reasons.append("+15 s for impact")
            if item["kind"] == "strength_compound" and item["equipment"] in HEAVY_EQUIPMENT:
                between += 15
                reasons.append("+15 s for heavier load")
            if item["sets"] >= 4:
                between += 10
                reasons.append("+10 s for 4+ sets")
            if prefs["pain"]:
                between += 15
                reasons.append("+15 s because you reported pain")
        if prefs["pain"] and after > 0 and item["phase"] == "main":
            after += 15
        item["rest_between_sets_s"] = min(between, REST_CAP_BETWEEN_S) if item["sets"] > 1 else 0
        item["_rest_after_default"] = min(after, REST_CAP_AFTER_S)
        level = "beginner" if prefs["pain"] else prefs["fitness_level"]
        kind = item["kind"].replace("_", " ")
        item["rest_basis"] = (f"{item['rest_between_sets_s']} s between sets: base for {kind} at {level} level"
                              + (f" ({', '.join(reasons)})" if reasons else "") + "."
                              if item["sets"] > 1 else "Single set; short transition only.")


def _set_phase_transitions(items: list[dict], catalog: dict) -> None:
    """Rest after an item depends on what follows: no rest after the last main item (straight to cool-down)."""
    for index, item in enumerate(items):
        nxt = items[index + 1] if index + 1 < len(items) else None
        if nxt is None:
            item["rest_after_s"] = 0
        elif item["phase"] == "warmup" and nxt["phase"] != "warmup":
            item["rest_after_s"] = int(catalog.get("transition_to_main_seconds", 30))
        elif item["phase"] == "main" and nxt["phase"] == "cooldown":
            item["rest_after_s"] = 0
        else:
            item["rest_after_s"] = item["_rest_after_default"]


def _make_item(exercise: dict, catalog: dict, prefs: dict, phase: str, area: Optional[str], rationale: dict,
               video_available) -> dict:
    dose = _dose(exercise, catalog, prefs)
    has_video = bool(exercise.get("video")) and video_available(exercise["id"])
    return {
        "exercise_id": exercise["id"], "name": exercise["name"], "phase": phase, "area": area,
        "area_label": catalog["areas"].get(area) if area else None, "kind": exercise["kind"], "mode": exercise["mode"],
        "per_side": exercise["per_side"], "target": dose["target"], "sets": dose["sets"], "cadence_s": dose["cadence_s"],
        "work_s": dose["work_s"], "rest_between_sets_s": dose["rest_between_sets_s"], "rest_after_s": dose["rest_after_s"],
        "_rest_after_default": dose["rest_after_s"],
        "_rest_between_base": dose["rest_between_sets_s"], "_rest_after_base": dose["rest_after_s"],
        "video": has_video, "video_missing": bool(exercise.get("video")) and not has_video,
        "media_url": f"/api/workout-media/{exercise['id']}" if has_video else None,
        "equipment": exercise["equipment"], "equipment_label": catalog["equipment"][exercise["equipment"]]["label"],
        "needs": exercise.get("needs"), "muscles": exercise["muscles"], "description": exercise["description"],
        "instructions": exercise["instructions"], "cues": exercise["cues"], "mistakes": exercise["mistakes"],
        "safety": exercise["safety"], "regression": exercise["regression"], "progression": exercise["progression"],
        "impact": exercise["impact"], "rationale": rationale,
    }


def _rationale(exercise: dict, area: str, area_info: dict, prefs: dict, catalog: dict) -> dict:
    level = prefs["fitness_level"]
    equipment_label = catalog["equipment"][exercise["equipment"]]["label"].lower()
    fit = (f"Uses {equipment_label}, which you selected, at a {level}-appropriate dose"
           + (" (reduced because you reported pain)." if prefs["pain"] else "."))
    findings = sorted([s for s in area_info["sources"] if s["type"] == "finding"], key=lambda s: -s["weight"])
    goals = [s for s in area_info["sources"] if s["type"] == "goal"]
    if findings:
        top = findings[0]
        label = "a possible issue" if top.get("possible") else "this"
        reason = (f"Selected because your report found {label}: “{top['title']}” ({top.get('affected') or 'measured attempts'}, "
                  f"{top['confidence']} confidence).")
        limit = FINDING_LIMIT.get(top["id"], "")
        source = {"type": "finding", "id": top["id"], "title": top["title"], "confidence": top["confidence"]}
    elif goals:
        reason = f"Selected because you asked to work on {goals[0]['title'].lower()}. It is not based on a report finding."
        limit = "Your report did not measure this area; the exercise follows your stated goal."
        if goals[0]["id"] == "jump":
            limit += " Jump height is not measured by this app."
        source = {"type": "goal", "id": goals[0]["id"], "title": goals[0]["title"]}
    else:
        reason = "General basketball-support exercise; it is not based on a report finding."
        limit = "No finding in your report points to this area."
        source = {"type": "general"}
    return {"reason": reason, "benefit": AREA_BENEFIT.get(area, ""), "fit": fit, "evidence_limit": limit,
            "cue": exercise["cues"][0], "regression": exercise["regression"], "progression": exercise["progression"],
            "source": source}


def _support_rationale(text: str, exercise: dict) -> dict:
    return {"reason": text, "benefit": "", "fit": "Needs no equipment.", "evidence_limit": "", "cue": exercise["cues"][0],
            "regression": exercise["regression"], "progression": exercise["progression"], "source": {"type": "structure"}}


def build_plan(report: dict[str, Any], prefs: dict[str, Any], catalog: dict[str, Any], *,
               video_available=lambda exercise_id: True) -> dict[str, Any]:
    """Build a workout plan. ``prefs`` must come from validate_preferences()."""
    extracted = extract_findings(report)
    all_exercises = catalog["exercises"]
    # Video-demonstrated exercises only: an exercise is prescribed only if its demonstration file is
    # mapped in the catalog AND present in the workout folder. Text-only exercises are never used.
    exercises = [e for e in all_exercises if e.get("video") and video_available(e["id"])]
    by_id = {e["id"]: e for e in exercises}
    left_out = [e["name"] for e in all_exercises if e["id"] not in by_id]
    target_s = max(MIN_DURATION_S, prefs["duration_min"] * 60)
    used_ids: set[str] = set()
    used_families: set[str] = set()

    # ---- focus areas, ranked by evidence (findings weighted by confidence) and stated goals
    area_scores = _area_scores(extracted, prefs)
    ranked = sorted(area_scores.items(), key=lambda kv: (-kv[1]["score"], kv[0]))
    general = not any(s["type"] == "finding" for _, info in ranked for s in info["sources"]) and not prefs["goals"]
    if general or len([a for a, _ in ranked if any(e for e in exercises if a in e["areas"] and _eligible(e, prefs, "main"))]) < 2:
        # Balanced general support so even an empty report yields a sensible session; clearly labelled.
        for area, value in (("lower_strength", 0.25), ("core", 0.2), ("balance", 0.15), ("shoulder", 0.1)):
            if area not in area_scores:
                area_scores[area] = {"score": value, "sources": [{"type": "general", "weight": value}]}
        ranked = sorted(area_scores.items(), key=lambda kv: (-kv[1]["score"], kv[0]))

    def candidates(area):
        """Eligible exercises for an area; exercises whose primary purpose is the area come first,
        secondary ones only when no primary option fits (so push-ups are never picked as 'core')."""
        pool = [e for e in exercises if area in e["areas"] and _eligible(e, prefs, "main")
                and e["id"] not in used_ids and _family(e["id"]) not in used_families]
        primary = [e for e in pool if e["areas"][0] == area]
        pool = primary or pool
        return sorted(pool, key=lambda e: (-_rank(e, area, prefs, video_available), exercises.index(e)))

    focus, unaddressed = [], []
    for area, info in ranked:
        if candidates(area):
            focus.append((area, info))
        else:
            any_level = [e for e in exercises if area in e["areas"] and "main" in e["phases"]
                         and e["equipment"] in prefs["equipment"]]
            text_only = [e for e in all_exercises if e["id"] not in by_id and area in e["areas"]
                         and _eligible(e, prefs, "main")]
            if text_only and not any_level:
                reason = ("The exercises that fit this area with your choices have no demonstration video, and "
                          "workouts only use video-demonstrated exercises. Add other equipment to include it.")
            elif not any_level:
                reason = "No exercise for this area fits your equipment. Add Bodyweight or another option to include it."
            else:
                reason = "No exercise for this area fits your level, reported pain or movements to avoid."
            unaddressed.append({"area": area, "label": catalog["areas"][area], "reason": reason,
                                "from_findings": [s["title"] for s in info["sources"] if s["type"] == "finding"]})
    max_areas = 4 if prefs["duration_min"] >= 30 else 3
    focus = focus[:max_areas]
    n_main = next(count for limit, count in MAIN_EXERCISES_FOR if prefs["duration_min"] <= limit)

    # ---- main block: share exercises between focus areas in proportion to their evidence weight
    main: list[dict] = []
    weights = dict(focus)

    def area_load(area, extra=1):
        return (sum(1 for item in main if item["area"] == area) + extra) / max(weights[area]["score"], 0.05)

    while len(main) < n_main and focus:
        open_areas = [area for area, _ in focus if candidates(area)
                      and sum(1 for item in main if item["area"] == area) < 3]
        if not open_areas:
            break
        area = min(open_areas, key=lambda a: (area_load(a), -weights[a]["score"], a))
        exercise = candidates(area)[0]
        used_ids.add(exercise["id"])
        used_families.add(_family(exercise["id"]))
        main.append(_make_item(exercise, catalog, prefs, "main", area,
                               _rationale(exercise, area, weights[area], prefs, catalog), video_available))
    # Order: power/compound first, then accessory/balance, then core, conditioning last.
    order = {"power_low": 0, "strength_compound": 1, "balance": 2, "strength_accessory": 3, "core_dynamic": 4,
             "core_static": 5, "conditioning": 6, "mobility": 7, "stretch": 8, "warmup": 9}
    main.sort(key=lambda item: order[item["kind"]])

    # ---- warm-up: pulse raiser(s) + mobility matched to the main block
    lower = any(item["area"] in ("lower_strength", "hip_drive", "balance", "power_low", "conditioning") for item in main)
    upper = any(item["area"] in ("shoulder", "arm", "upper_push") for item in main)
    warm_ids = ["running_in_place", "march_in_place"]
    if prefs["fitness_level"] != "beginner":
        warm_ids.insert(1, "butt_kicks")
    warm_ids += ["leg_swings" if lower else "hip_circles", "arm_circles" if upper else "hip_circles", "ankle_rocks", "cat_cow"]
    warmup = []
    for exercise_id in warm_ids:
        exercise = by_id.get(exercise_id)
        if exercise and exercise_id not in used_ids and _eligible(exercise, prefs, "warmup") and len(warmup) < 4:
            if exercise_id == "march_in_place" and any(w["exercise_id"] in ("running_in_place", "butt_kicks") for w in warmup):
                continue
            used_ids.add(exercise_id)
            warmup.append(_make_item(exercise, catalog, prefs, "warmup", None, _support_rationale(
                "Warm-up: raises your temperature and prepares the joints for the main block.", exercise), video_available))

    if len(warmup) < 3:
        # Few video-demonstrated warm-up moves fit (e.g. ankle or floor limits): start with gentle,
        # video-demonstrated mobility instead of skipping the warm-up.
        for exercise_id in ("lunging_calf_stretch", "rear_delt_stretch", "knee_to_chest_stretch", "standing_quad_stretch",
                            "side_lunge_stretch", "side_tilt"):
            exercise = by_id.get(exercise_id)
            if exercise and exercise_id not in used_ids and _eligible(exercise, prefs, "cooldown") and len(warmup) < 3:
                used_ids.add(exercise_id)
                warmup.append(_make_item(exercise, catalog, prefs, "warmup", None, _support_rationale(
                    "Warm-up: gentle mobility to prepare the joints (few warm-up drills with a video fit your choices).",
                    exercise), video_available))

    # ---- cool-down: stretches for the areas worked
    cool_ids = []
    if lower:
        cool_ids += ["lunging_calf_stretch", "standing_quad_stretch", "kneeling_hamstring_stretch", "hip_flexor_stretch", "lying_glute_stretch"]
    if any(item["area"] in ("core",) for item in main):
        cool_ids += ["childs_pose", "knee_to_chest_stretch"]
    if upper:
        cool_ids += ["rear_delt_stretch", "doorway_chest_stretch", "overhead_tricep_stretch"]
    cool_ids += ["standing_forward_bend", "side_lunge_stretch", "side_tilt", "knee_to_chest_stretch", "rear_delt_stretch"]
    cool_pool = []
    for exercise_id in cool_ids:
        exercise = by_id.get(exercise_id)
        if exercise and exercise_id not in used_ids and exercise_id not in [e["id"] for e in cool_pool] \
                and _eligible(exercise, prefs, "cooldown"):
            cool_pool.append(exercise)
    cooldown = []

    def add_cooldown():
        if not cool_pool:
            return False
        exercise = cool_pool.pop(0)
        used_ids.add(exercise["id"])
        cooldown.append(_make_item(exercise, catalog, prefs, "cooldown", None, _support_rationale(
            "Cool-down: gentle stretching to finish the session.", exercise), video_available))
        return True

    for _ in range(4):
        add_cooldown()

    def assemble():
        items = warmup + main + cooldown
        _finalize_rest(items, prefs)
        _set_phase_transitions(items, catalog)
        return items

    # ---- reach the planned duration (>= 20 min) with low-risk additions, never by forcing intensity
    adjustments = []
    max_main = 8 if prefs["duration_min"] <= 40 else 10
    items = assemble()
    guard = 0
    while plan_duration(items)["total_s"] < target_s and guard < 60:
        guard += 1
        added = False
        deficit = target_s - plan_duration(items)["total_s"]
        # 0) small gap: prefer a cool-down stretch over a whole new exercise
        if deficit <= 150 and len(cooldown) < 7:
            added = add_cooldown()
            if added:
                adjustments.append("Added a cool-down stretch to reach the planned duration.")
        # 1) another relevant exercise, from the focus area with the fewest exercises for its weight
        if not added and len(main) < max_main and deficit > 150:
            for area, info in sorted(focus, key=lambda ai: (area_load(ai[0]), -ai[1]["score"])):
                pool = candidates(area)
                if pool:
                    exercise = pool[0]
                    used_ids.add(exercise["id"])
                    used_families.add(_family(exercise["id"]))
                    main.append(_make_item(exercise, catalog, prefs, "main", area,
                                           _rationale(exercise, area, info, prefs, catalog), video_available))
                    main.sort(key=lambda item: order[item["kind"]])
                    adjustments.append(f"Added {exercise['name']} ({catalog['areas'][area].lower()}) to reach the planned duration.")
                    added = True
                    break
        # 1b) focus areas exhausted: a general basketball-support exercise from another area (labelled general)
        if not added and len(main) < max_main and deficit > 150:
            for area in ("lower_strength", "core", "balance", "hip_drive", "shoulder", "conditioning", "mobility",
                         "arm", "upper_push"):
                if area in weights:
                    continue
                pool = candidates(area)
                if pool:
                    exercise = pool[0]
                    used_ids.add(exercise["id"])
                    used_families.add(_family(exercise["id"]))
                    info = {"score": 0.0, "sources": []}
                    main.append(_make_item(exercise, catalog, prefs, "main", area,
                                           _rationale(exercise, area, info, prefs, catalog), video_available))
                    main.sort(key=lambda item: order[item["kind"]])
                    adjustments.append(f"Added {exercise['name']} (general support, {catalog['areas'][area].lower()}) "
                                       "to reach the planned duration.")
                    added = True
                    break
        # 2) one more set of a low-intensity main exercise
        if not added:
            for item in sorted(main, key=lambda i: (i["kind"] not in ("core_static", "core_dynamic", "balance", "strength_accessory", "mobility"), i["sets"])):
                if item["sets"] < (2 if prefs["pain"] else MAX_SETS[prefs["fitness_level"]]) and item["kind"] != "power_low":
                    item["sets"] += 1
                    adjustments.append(f"Added a set of {item['name']} to reach the planned duration.")
                    added = True
                    break
        # 3) another cool-down stretch
        if not added and len(cooldown) < 7:
            added = add_cooldown()
            if added:
                adjustments.append("Added a cool-down stretch to reach the planned duration.")
        # 4) any remaining video-demonstrated stretch (no limit on count)
        if not added:
            added = add_cooldown()
            if added:
                adjustments.append("Added a cool-down stretch to reach the planned duration.")
        # 5) easy running in place as active recovery, if it fits the player's limits
        if not added:
            exercise = by_id.get("running_in_place")
            if exercise and _eligible(exercise, prefs, "warmup"):
                item = _make_item(exercise, catalog, prefs, "cooldown", None, _support_rationale(
                    "Easy active recovery to reach the planned duration without adding intensity.", exercise), video_available)
                item["target"] = 60
                item["work_s"] = 60
                cooldown.insert(0, item)
                adjustments.append("Added easy running in place (active recovery) to reach the planned duration.")
                added = True
        if not added:
            break
        items = assemble()

    # ---- trim a large overshoot (heavier doses for stronger levels can exceed a short request) while
    # staying at or above the target: drop extra stretches/warm-ups or a set, never a focus area's only item.
    min_sets = 2
    guard = 0
    while plan_duration(items)["total_s"] - target_s > OVERSHOOT_TOLERANCE_S and guard < 40:
        guard += 1
        options = []
        for item in main:
            if item["sets"] > min_sets:
                options.append(("set", item))
        if len(cooldown) > 2:
            options.append(("cooldown", cooldown[-1]))
        if len(warmup) > 3:
            options.append(("warmup", warmup[-1]))
        for item in main:
            if len(main) > 3 and sum(1 for other in main if other["area"] == item["area"]) > 1:
                options.append(("main", item))
        best = None
        for kind, item in options:
            if kind == "set":
                item["sets"] -= 1
                trial = assemble()
                item["sets"] += 1
            else:
                group = {"cooldown": cooldown, "warmup": warmup, "main": main}[kind]
                group.remove(item)
                trial = assemble()
                group.append(item)
                if kind == "main":
                    main.sort(key=lambda i: order[i["kind"]])
            total = plan_duration(trial)["total_s"]
            if total >= target_s and (best is None or total < best[0]):
                best = (total, kind, item)
        if best is None:
            break
        _, kind, item = best
        if kind == "set":
            item["sets"] -= 1
            adjustments.append(f"One fewer set of {item['name']} to stay close to the planned duration.")
        else:
            {"cooldown": cooldown, "warmup": warmup, "main": main}[kind].remove(item)
            adjustments.append(f"Left out {item['name']} to stay close to the planned duration.")
        items = assemble()

    items = assemble()  # recompute rests/transitions after any trial changes above
    for index, item in enumerate(items):
        item["uid"] = f"s{index + 1:02d}-{item['exercise_id']}"
        item["planned_s"] = item_duration(item)
        item.pop("_rest_after_default", None)
        item.pop("_rest_between_base", None)
        item.pop("_rest_after_base", None)
    duration = plan_duration(items)
    duration["target_s"] = target_s
    duration["method"] = ("Each item counts sets × work time, plus rest between sets, plus the rest after it. Repetition sets "
                          "use a configured cadence (seconds per repetition, doubled for exercises done on each side). Rest after "
                          "the last main exercise is 0 because the cool-down starts straight away.")

    summary = summary_sentence(extracted, catalog)
    # Name the focus areas the plan actually covers (the sentence above names the strongest ones).
    covered = [catalog["areas"][area].lower() for area, info in focus
               if any(s["type"] in ("finding", "goal") for s in info["sources"])]
    if covered:
        summary += f" Plan focus: {', '.join(covered)}."
    missed = [u for u in unaddressed if u["from_findings"]]
    if missed:
        summary += (" Not covered with your current choices: " + ", ".join(u["label"].lower() for u in missed)
                    + " (see the note below the plan).")
    if general:
        summary += " Exercises are labelled as general where no finding supports them."
    focus_out = [{"area": area, "label": catalog["areas"][area], "score": round(info["score"], 3), "sources": info["sources"]}
                 for area, info in focus]
    title_areas = [catalog["areas"][area] for area, _ in focus[:2]]
    title = "Personalized workout: " + " + ".join(title_areas) if title_areas else "Workout"
    safety = list(SAFETY_NOTES)
    if prefs["avoid"]:
        safety.append("Movements you asked to avoid were filtered out: " + ", ".join(AVOID[a].lower() for a in prefs["avoid"]) + ".")
    return {
        "plan_version": PLAN_VERSION, "catalog_version": catalog.get("catalog_version"),
        "title": title, "general": general,
        "source": {k: extracted[k] for k in ("session_id", "player_id", "session_date", "video_filename", "report_generated_at")},
        "summary": summary, "preferences": prefs,
        "equipment_labels": [catalog["equipment"][e]["label"] for e in prefs["equipment"]],
        "focus": focus_out, "unaddressed": unaddressed, "findings_used": extracted["improvements"],
        "strengths": extracted["strengths"], "technique_only": extracted["technique_only"],
        "not_assessed": extracted["not_assessed"], "uncertainty": extracted["uncertainty"],
        "items": items, "duration": duration, "adjustments": adjustments,
        "video_policy": {"rule": "Only exercises with a demonstration video in your workout folder are prescribed.",
                         "excluded_count": len(left_out)},
        "safety": safety, "pain_note": PAIN_NOTE if prefs["pain"] else None,
        "counting": "Guided repetition mode: the counter follows a planned pace. It does not detect or verify your movement.",
    }
