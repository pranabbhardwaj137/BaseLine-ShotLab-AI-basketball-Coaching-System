"""Drills catalog — 4 video-backed dribbling drills.

Each drill maps to a video file served from /drills/<video_file>.
Form feedback keys map to what the camera-based posture checker looks for.
"""

from __future__ import annotations
from typing import Any

CATALOG_VERSION = "drills-catalog-2.0"

DRILLS_CATALOG: list[dict[str, Any]] = [
    {
        "id": "pound_dribble",
        "name": "Pound Dribble",
        "category": "dribbling",
        "difficulty": "beginner",
        "duration": "1 min each hand",
        "video": "pound_dribble.mp4",
        "how": (
            "Dribble the ball as hard as you can straight down, one hand at a time. "
            "Start with your dominant hand, then switch. "
            "The ball should stay below your knee. Keep your eyes up and body still."
        ),
        "cues": [
            "Hammer it down hard",
            "Ball stays low — below the knee",
            "Eyes forward, not at the ball",
            "Body stays still",
        ],
        "form_checks": ["knees_bent", "eyes_up", "back_straight"],
        "counter": "dribble_wrist",
        "skills": ["ball control", "hand strength", "low dribble"],
    },
    {
        "id": "pound_plus_cross",
        "name": "Pound + Crossover",
        "category": "dribbling",
        "difficulty": "beginner",
        "duration": "2 min",
        "video": "pound_plus_cross.mp4",
        "how": (
            "Pound dribble twice with your right hand, then push the ball low across your body "
            "to your left hand. Pound twice with your left, then cross back. "
            "Keep the crossover below the waist and use a quick wrist snap."
        ),
        "cues": [
            "Two pounds, then cross",
            "Crossover stays low — below the waist",
            "Quick wrist snap on the cross",
            "Stay in an athletic stance",
        ],
        "form_checks": ["knees_bent", "back_straight", "low_dribble"],
        "counter": "dribble_wrist",
        "skills": ["ball handling", "crossover", "change of direction"],
    },
    {
        "id": "pound_plus_v_dribble",
        "name": "Pound + V-Dribble",
        "category": "dribbling",
        "difficulty": "intermediate",
        "duration": "2 min",
        "video": "pound_plus_v-dribble.mp4",
        "how": (
            "Pound dribble twice, then switch to a V-dribble: push the ball forward and pull it "
            "back in a V shape using your fingertips. "
            "Keep the V tight — ball never goes past your front foot. "
            "Alternate dominant and non-dominant hand."
        ),
        "cues": [
            "Tight V — don't let the ball escape",
            "Fingertips push forward and pull back",
            "Low and controlled throughout",
            "Soft knees, stay balanced",
        ],
        "form_checks": ["knees_bent", "back_straight", "low_dribble"],
        "counter": "dribble_wrist",
        "skills": ["ball control", "change of pace", "dribble footwork"],
    },
    {
        "id": "v_dribble_plus_cross",
        "name": "V-Dribble + Crossover",
        "category": "dribbling",
        "difficulty": "intermediate",
        "duration": "2 min",
        "video": "v-dribble_plus_cross.mp4",
        "how": (
            "V-dribble twice with your right hand, then explode into a low crossover to your left. "
            "V-dribble twice with your left, then cross back right. "
            "This combo trains switching from a change-of-pace move into a change-of-direction move."
        ),
        "cues": [
            "V tight, then cross low",
            "Explosive crossover after the V",
            "Eyes up through the whole combo",
            "Stay low — don't rise on the crossover",
        ],
        "form_checks": ["knees_bent", "eyes_up", "back_straight", "low_dribble"],
        "counter": "dribble_wrist",
        "skills": ["ball handling", "combo moves", "explosiveness"],
    },
]

DRILL_BY_ID: dict[str, dict[str, Any]] = {d["id"]: d for d in DRILLS_CATALOG}

CATEGORIES: dict[str, str] = {
    "dribbling": "Dribbling",
}

# What each form_check key means for the feedback card shown after a drill
FORM_CHECK_LABELS: dict[str, str] = {
    "knees_bent":   "Knees bent in athletic stance",
    "eyes_up":      "Head up, not looking at the ball",
    "back_straight":"Back flat, not hunching over",
    "low_dribble":  "Dribble kept low (below knee height)",
}


def get_catalog(category: str | None = None, difficulty: str | None = None) -> dict[str, Any]:
    drills = DRILLS_CATALOG
    if category:
        drills = [d for d in drills if d["category"] == category]
    if difficulty:
        drills = [d for d in drills if d["difficulty"] == difficulty]
    return {
        "version": CATALOG_VERSION,
        "categories": CATEGORIES,
        "form_check_labels": FORM_CHECK_LABELS,
        "drills": drills,
        "total": len(drills),
    }
