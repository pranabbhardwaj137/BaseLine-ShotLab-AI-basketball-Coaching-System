"""Drills catalog — 4 video-backed dribbling drills.

Each drill maps to a video file served from /drills/<video_file>.
Contains real reference biomechanical measurements extracted from reference videos
for live posture verification and ball bounce tracking.
"""

from __future__ import annotations
from typing import Any

CATALOG_VERSION = "drills-catalog-2.2"

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
        "counter": "yolo_ball_bounce",
        "skills": ["ball control", "hand strength", "low dribble"],
        "target_sequence": ["POUND"],
        "sequence_description": "Continuous rhythmic pound dribbles",
        "reference_biomechanics": {
            "knee_angle_mean": 153.5,
            "knee_angle_range": [145.0, 163.0],
            "hip_angle_mean": 121.6,
            "hip_angle_range": [110.0, 130.0],
            "head_pitch_threshold": 0.04,
            "dribble_height_max": "knee",
            "ball_apex_y": 0.494,
            "ball_ground_y": 0.753,
            "vertical_excursion": 0.259,
            "lateral_span": 0.08,
        },
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
        "counter": "yolo_ball_bounce",
        "skills": ["ball handling", "crossover", "change of direction"],
        "target_sequence": ["POUND", "POUND", "CROSSOVER"],
        "sequence_description": "2 Pounds + 1 Crossover",
        "reference_biomechanics": {
            "knee_angle_mean": 160.5,
            "knee_angle_range": [148.0, 166.0],
            "hip_angle_mean": 119.0,
            "hip_angle_range": [105.0, 135.0],
            "head_pitch_threshold": 0.04,
            "dribble_height_max": "knee",
            "ball_apex_y": 0.470,
            "ball_ground_y": 0.745,
            "vertical_excursion": 0.275,
            "lateral_span": 0.689,
        },
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
        "counter": "yolo_ball_bounce",
        "skills": ["ball control", "change of pace", "dribble footwork"],
        "target_sequence": ["POUND", "POUND", "V_DRIBBLE"],
        "sequence_description": "2 Pounds + 1 V-Dribble",
        "reference_biomechanics": {
            "knee_angle_mean": 155.8,
            "knee_angle_range": [147.0, 162.0],
            "hip_angle_mean": 117.5,
            "hip_angle_range": [100.0, 135.0],
            "head_pitch_threshold": 0.04,
            "dribble_height_max": "knee",
            "ball_apex_y": 0.483,
            "ball_ground_y": 0.751,
            "vertical_excursion": 0.268,
            "lateral_span": 0.733,
        },
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
        "counter": "yolo_ball_bounce",
        "skills": ["ball handling", "combo moves", "explosiveness"],
        "target_sequence": ["V_DRIBBLE", "V_DRIBBLE", "CROSSOVER"],
        "sequence_description": "2 V-Dribbles + 1 Crossover",
        "reference_biomechanics": {
            "knee_angle_mean": 163.2,
            "knee_angle_range": [153.0, 172.0],
            "hip_angle_mean": 118.6,
            "hip_angle_range": [105.0, 136.0],
            "head_pitch_threshold": 0.04,
            "dribble_height_max": "knee",
            "ball_apex_y": 0.492,
            "ball_ground_y": 0.749,
            "vertical_excursion": 0.258,
            "lateral_span": 0.719,
        },
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


def get_drill_by_id(drill_id: str) -> dict[str, Any] | None:
    """Return drill dict by ID, or None if not found."""
    return DRILL_BY_ID.get(drill_id)
