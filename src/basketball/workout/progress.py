"""Validation of workout player state/progress, and the honest end-of-workout summary.

The browser reports what happened set by set: completed (the guided count ran to the end or the
user marked the set done), partial (stopped part-way, with the count reached), or skipped. The
server never infers completion from elapsed time. The summary is computed here, from those
records, so skipped work cannot be shown as completed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

SET_STATUSES = {"completed", "partial", "skipped"}
PHASES = {"ready", "work", "rest", "done"}
FINAL_STATUSES = {"completed", "ended_early"}
DIFFICULTY = {"too_easy", "about_right", "too_hard"}


def set_count_target(item: dict[str, Any]) -> int:
    """The count a set runs to: repetitions (both sides for per-side exercises) or seconds."""
    return int(item["target"]) * (2 if item.get("per_side") else 1)


def spoken_numbers(target_count: int) -> list[int]:
    """Final-10% countdown: numbers spoken, in order, for a count of ``target_count``."""
    import math
    count = max(1, math.ceil(int(target_count) * 0.10))
    return list(range(min(count, int(target_count)), 0, -1))


def _int(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = int(value)
    if value < low or value > high:
        raise ValueError(f"{name} is out of range")
    return value


def validate_progress(plan: dict[str, Any], progress: Any) -> dict[str, Any]:
    if not isinstance(progress, dict):
        raise ValueError("progress must be an object")
    items = {item["uid"]: item for item in plan["items"]}
    raw_items = progress.get("items") or {}
    if not isinstance(raw_items, dict) or len(raw_items) > len(items):
        raise ValueError("progress.items must map plan steps to their sets")
    clean_items = {}
    for uid, record in raw_items.items():
        item = items.get(uid)
        if not item or not isinstance(record, dict):
            raise ValueError("progress refers to a step that is not in this plan")
        sets = record.get("sets") or []
        if not isinstance(sets, list) or len(sets) > item["sets"]:
            raise ValueError(f"Too many sets recorded for {item['name']}")
        target = set_count_target(item)
        clean_sets = []
        for entry in sets:
            if entry is None:
                clean_sets.append(None)
                continue
            if not isinstance(entry, dict) or entry.get("status") not in SET_STATUSES:
                raise ValueError("Each recorded set needs a status of completed, partial or skipped")
            count = _int(entry.get("count", 0), 0, target, "set count")
            status = entry["status"]
            if status == "completed":
                count = target
            elif status == "skipped":
                count = 0
            elif status == "partial" and count >= target:
                status = "completed"
            clean_sets.append({"status": status, "count": count})
        clean_items[uid] = {"sets": clean_sets, "skipped": bool(record.get("skipped"))}
    return {
        "items": clean_items,
        "active_s": _int(progress.get("active_s", 0), 0, 6 * 3600, "active_s"),
        "rest_added_s": _int(progress.get("rest_added_s", 0), 0, 6 * 3600, "rest_added_s"),
        "rest_skipped": _int(progress.get("rest_skipped", 0), 0, 1000, "rest_skipped"),
    }


def validate_state(plan: dict[str, Any], state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    uids = [item["uid"] for item in plan["items"]]
    index = _int(state.get("index", 0), 0, len(uids), "state.index")
    set_index = _int(state.get("set", 0), 0, 20, "state.set")
    phase = state.get("phase", "ready")
    if phase not in PHASES:
        raise ValueError("state.phase is invalid")
    announced = state.get("announced") or []
    if not isinstance(announced, list) or any(uid not in uids for uid in announced):
        raise ValueError("state.announced must list plan steps")
    spoken = state.get("spoken") or []
    if not isinstance(spoken, list) or len(spoken) > 50:
        raise ValueError("state.spoken is invalid")
    return {
        "index": index, "set": set_index, "phase": phase,
        "remaining_ms": _int(state.get("remaining_ms", 0), 0, 3 * 3600 * 1000, "state.remaining_ms"),
        "rest_total_ms": _int(state.get("rest_total_ms", 0), 0, 3 * 3600 * 1000, "state.rest_total_ms"),
        "count": _int(state.get("count", 0), 0, 10000, "state.count"),
        "elapsed_ms": _int(state.get("elapsed_ms", 0), 0, 3 * 3600 * 1000, "state.elapsed_ms"),
        "announced": list(dict.fromkeys(announced)),
        "spoken": [_int(n, 0, 1000, "state.spoken") for n in spoken],
        "paused": bool(state.get("paused", True)),
        "voice": bool(state.get("voice", True)),
        "rest_kind": state.get("rest_kind") if state.get("rest_kind") in ("set", "exercise") else None,
        "ending": state.get("ending") if state.get("ending") in FINAL_STATUSES else None,
    }


def validate_feedback(feedback: Any) -> Optional[dict[str, Any]]:
    if feedback is None:
        return None
    if not isinstance(feedback, dict):
        raise ValueError("feedback must be an object")
    difficulty = feedback.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTY:
        raise ValueError("difficulty must be too_easy, about_right or too_hard")
    return {"difficulty": difficulty, "felt_pain": bool(feedback.get("felt_pain")),
            "note": str(feedback.get("note") or "")[:500]}


def _parse_ts(value) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def build_summary(plan: dict[str, Any], progress: dict[str, Any], feedback: Optional[dict[str, Any]],
                  status: str, started_at=None, ended_at=None) -> dict[str, Any]:
    records = progress.get("items", {})
    exercises = []
    totals = {"sets_planned": 0, "sets_completed": 0, "sets_partial": 0, "sets_skipped": 0, "sets_not_reached": 0,
              "guided_reps": 0, "timed_work_s": 0, "completed_work_s": 0.0}
    for item in plan["items"]:
        record = records.get(item["uid"], {"sets": [], "skipped": False})
        target = set_count_target(item)
        sets = [s for s in record.get("sets", []) if s]
        done = sum(1 for s in sets if s["status"] == "completed")
        partial = sum(1 for s in sets if s["status"] == "partial")
        skipped = sum(1 for s in sets if s["status"] == "skipped")
        not_reached = item["sets"] - done - partial - skipped
        if record.get("skipped"):
            skipped += not_reached
            not_reached = 0
        counted = sum(s["count"] for s in sets if s["status"] in ("completed", "partial"))
        if item["mode"] == "reps":
            totals["guided_reps"] += counted
        else:
            totals["timed_work_s"] += counted
        totals["completed_work_s"] += item["work_s"] * (counted / target if target else 0)
        if done == item["sets"]:
            state = "completed"
        elif done or partial:
            state = "partial"
        elif skipped:
            state = "skipped"
        else:
            state = "not_reached"
        for key, value in (("sets_planned", item["sets"]), ("sets_completed", done), ("sets_partial", partial),
                           ("sets_skipped", skipped), ("sets_not_reached", not_reached)):
            totals[key] += value
        exercises.append({"uid": item["uid"], "name": item["name"], "phase": item["phase"], "status": state,
                          "sets_planned": item["sets"], "sets_completed": done, "sets_partial": partial,
                          "sets_skipped": skipped, "mode": item["mode"], "count_recorded": counted,
                          "count_per_set": target})
    start, end = _parse_ts(started_at), _parse_ts(ended_at)
    elapsed = int((end - start).total_seconds()) if start and end and end >= start else None
    main = [e for e in exercises if e["phase"] == "main"]
    by_status = lambda rows, s: [e["name"] for e in rows if e["status"] == s]
    planned_work = sum(item["sets"] * item["work_s"] for item in plan["items"])
    summary = {
        "status": status,
        "exercises": exercises,
        "counts": {
            "completed": len(by_status(exercises, "completed")), "partial": len(by_status(exercises, "partial")),
            "skipped": len(by_status(exercises, "skipped")), "not_reached": len(by_status(exercises, "not_reached")),
            "main_completed": len(by_status(main, "completed")), "main_total": len(main),
        },
        "sets": {k: totals[k] for k in ("sets_planned", "sets_completed", "sets_partial", "sets_skipped", "sets_not_reached")},
        "guided_reps": totals["guided_reps"],
        "timed_work_s": totals["timed_work_s"],
        "planned_total_s": int(plan["duration"]["total_s"]),
        "planned_work_s": int(planned_work),
        "completed_work_s": int(round(totals["completed_work_s"])),
        "active_s": progress.get("active_s", 0),
        "elapsed_s": elapsed,
        "rest_added_s": progress.get("rest_added_s", 0),
        "rest_skipped": progress.get("rest_skipped", 0),
        "counting_note": "Repetitions are guided counts at a planned pace; the app did not detect or verify your movement.",
        "next_session": next_session(plan, exercises, feedback, status),
    }
    return summary


def next_session(plan: dict[str, Any], exercises: list[dict], feedback: Optional[dict], status: str) -> list[str]:
    tips = []
    feedback = feedback or {}
    if feedback.get("felt_pain"):
        tips.append("You reported pain. Rest it, and have it assessed by a physiotherapist or doctor before repeating these exercises. Do not train through pain.")
    main = [e for e in exercises if e["phase"] == "main"]
    skipped = [e["name"] for e in main if e["status"] in ("skipped", "not_reached")]
    partial = [e["name"] for e in main if e["status"] == "partial"]
    items = {item["uid"]: item for item in plan["items"]}
    if feedback.get("difficulty") == "too_hard" or (skipped and not feedback.get("felt_pain")):
        easier = [f"{items[e['uid']]['name']}: {items[e['uid']]['regression']}" for e in main
                  if e["status"] in ("skipped", "partial", "not_reached")][:3]
        tips.append("Next time, use the easier versions" + (": " + "; ".join(easier) if easier else " shown for each exercise") + ".")
    elif feedback.get("difficulty") == "too_easy" and not skipped and not partial and status == "completed":
        harder = [f"{item['name']}: {item['progression']}" for item in plan["items"] if item["phase"] == "main"][:3]
        tips.append("You found it easy and completed everything. Progress gradually next time: " + "; ".join(harder) + ".")
    elif status == "completed" and not skipped and not partial:
        tips.append("Repeat this plan two or three times over the next two weeks before increasing the load or sets.")
    if status == "ended_early":
        tips.append("The workout was ended early; remaining exercises are recorded as not reached, not as done.")
    findings = [f for f in plan.get("findings_used", []) if not f.get("possible")]
    if findings:
        titles = "; ".join(f["title"].lower() for f in findings[:2])
        tips.append(f"Re-film a shooting session from the same camera position in two to three weeks to see whether these change: {titles}. "
                    "A change in the workout alone does not prove a change in your shot.")
    else:
        tips.append("Film another shooting session (side-on, whole body in frame) so the next workout can be based on measured findings.")
    return tips
