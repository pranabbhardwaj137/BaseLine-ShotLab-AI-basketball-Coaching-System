"""Exercise catalog and safe demonstration-video lookup.

The catalog lives in ``configs/workout_catalog.json`` and is the editable source of truth: each
exercise has an id, coaching text, equipment, level and impact rules, and an optional ``video``
path relative to the project's ``workout/`` folder. Browsers never see filesystem paths; they ask
for ``/api/workout-media/<exercise_id>`` and the server resolves the id through this module.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "configs" / "workout_catalog.json"
DEFAULT_WORKOUT_DIR = PROJECT_ROOT / "workout"

EXERCISE_ID = re.compile(r"[a-z0-9_]{1,64}")
LEVELS = ["beginner", "intermediate", "advanced"]
IMPACTS = ["none", "low", "moderate", "high"]
KINDS = {"strength_compound", "strength_accessory", "core_static", "core_dynamic", "balance", "power_low",
         "conditioning", "mobility", "warmup", "stretch"}
PHASES = {"warmup", "main", "cooldown"}
STRESSES = {"knee", "lower_back", "shoulder", "wrist", "ankle", "overhead", "floor"}

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


class CatalogError(ValueError):
    pass


def validate_catalog(catalog: dict[str, Any]) -> None:
    """Raise CatalogError if the catalog JSON is structurally unusable."""
    equipment = catalog.get("equipment") or {}
    areas = catalog.get("areas") or {}
    dosing = catalog.get("dosing") or {}
    seen = set()
    for exercise in catalog.get("exercises", []):
        eid = exercise.get("id")
        if not isinstance(eid, str) or not EXERCISE_ID.fullmatch(eid):
            raise CatalogError(f"Invalid exercise id: {eid!r}")
        if eid in seen:
            raise CatalogError(f"Duplicate exercise id: {eid}")
        seen.add(eid)
        if exercise.get("equipment") not in equipment:
            raise CatalogError(f"{eid}: unknown equipment {exercise.get('equipment')!r}")
        if exercise.get("kind") not in KINDS or exercise["kind"] not in dosing:
            raise CatalogError(f"{eid}: unknown kind {exercise.get('kind')!r}")
        if exercise.get("min_level") not in LEVELS:
            raise CatalogError(f"{eid}: unknown level {exercise.get('min_level')!r}")
        if exercise.get("impact") not in IMPACTS:
            raise CatalogError(f"{eid}: unknown impact {exercise.get('impact')!r}")
        if exercise.get("mode") not in {"reps", "time"}:
            raise CatalogError(f"{eid}: mode must be reps or time")
        if not set(exercise.get("phases", [])) <= PHASES or not exercise.get("phases"):
            raise CatalogError(f"{eid}: invalid phases")
        if not set(exercise.get("areas", [])) <= set(areas):
            raise CatalogError(f"{eid}: unknown area in {exercise.get('areas')}")
        if not set(exercise.get("stresses", [])) <= STRESSES:
            raise CatalogError(f"{eid}: unknown stress tag in {exercise.get('stresses')}")
        video = exercise.get("video")
        if video is not None:
            parts = Path(video).parts
            if (not isinstance(video, str) or Path(video).is_absolute() or ".." in parts
                    or Path(video).suffix.lower() != ".mp4"):
                raise CatalogError(f"{eid}: video must be a relative .mp4 path inside workout/")
        for key in ("instructions", "cues", "mistakes"):
            if not exercise.get(key):
                raise CatalogError(f"{eid}: {key} must not be empty")


def load_catalog(path: Optional[Path] = None) -> dict[str, Any]:
    """Load (and cache by modification time) the exercise catalog."""
    path = Path(path or DEFAULT_CATALOG_PATH)
    stamp = path.stat().st_mtime
    with _lock:
        cached = _cache.get(str(path))
        if cached and cached[0] == stamp:
            return cached[1]
        with path.open("r", encoding="utf-8") as fh:
            catalog = json.load(fh)
        validate_catalog(catalog)
        catalog["_by_id"] = {exercise["id"]: exercise for exercise in catalog["exercises"]}
        _cache[str(path)] = (stamp, catalog)
        return catalog


def exercise_by_id(catalog: dict[str, Any], exercise_id: str) -> Optional[dict[str, Any]]:
    if not isinstance(exercise_id, str) or not EXERCISE_ID.fullmatch(exercise_id):
        return None
    return catalog["_by_id"].get(exercise_id)


def media_path(catalog: dict[str, Any], exercise_id: str, workout_dir: Path) -> Optional[Path]:
    """Return the demonstration file for an exercise id, or None.

    Only ids from the catalog are accepted; the stored relative path is resolved and must stay
    inside ``workout_dir`` (no traversal, no symlink escape) and be an existing .mp4 file.
    """
    exercise = exercise_by_id(catalog, exercise_id)
    if not exercise or not exercise.get("video"):
        return None
    root = Path(workout_dir).resolve()
    candidate = (root / exercise["video"]).resolve()
    if root not in candidate.parents or candidate.suffix.lower() != ".mp4" or not candidate.is_file():
        return None
    return candidate


def video_status(catalog: dict[str, Any], workout_dir: Path) -> dict[str, list[str]]:
    """Which catalog videos exist on disk, which are missing, and which files are not mapped yet."""
    root = Path(workout_dir).resolve()
    mapped, present, missing = set(), [], []
    for exercise in catalog["exercises"]:
        if not exercise.get("video"):
            continue
        mapped.add(exercise["video"])
        (present if media_path(catalog, exercise["id"], root) else missing).append(exercise["id"])
    unmapped = []
    if root.is_dir():
        for file in sorted(root.rglob("*")):
            if file.is_file() and file.suffix.lower() == ".mp4":
                relative = file.relative_to(root).as_posix()
                if relative not in mapped:
                    unmapped.append(relative)
    return {"present": present, "missing": missing, "unmapped_files": unmapped}
