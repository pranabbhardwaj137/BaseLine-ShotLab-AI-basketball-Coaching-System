"""
demo_athletes.py - Canonical Demo Accounts for 1-Click Practice and Testing.

Provides prefilled profiles for:
- Pranab (Right-handed, Intermediate, Jump Shot, 182 cm, 188 cm wingspan)
- Pavan (Right-handed, Advanced, Jump Shot, 186 cm, 192 cm wingspan)
- Pracheth (Left-handed, Intermediate, Set Shot, 178 cm, 180 cm wingspan)
- Puneeth (Right-handed, Developing, Jump Shot, 175 cm, 178 cm wingspan, Pain/Soreness noted)
"""

from typing import Dict, Any, List

DEMO_ATHLETES: List[Dict[str, Any]] = [
    {
        "id": "usr_demo_pranab",
        "name": "Pranab",
        "player_id": "pranab",
        "email": "bhardwajpranab1312@gmail.com",
        "alt_email": "pranab@shotlab.local",
        "password": "123456",
        "handedness": "right",
        "skill_level": "intermediate",
        "shot_style": "jump_shot",
        "height_cm": 182.0,
        "wingspan_cm": 188.0,
        "goals": "Consistent release arc, smooth dip-to-set transfer, and repeatable balance.",
        "pain_reported": False,
        "avatar": "PB",
        "tag": "Right handed, Jump shot",
        "highlights": "Intermediate, 182 cm, Balanced release",
    },
    {
        "id": "usr_demo_pavan",
        "name": "Pavan",
        "player_id": "pavan",
        "email": "pavan@shotlab.local",
        "alt_email": None,
        "password": "123456",
        "handedness": "right",
        "skill_level": "advanced",
        "shot_style": "jump_shot",
        "height_cm": 186.0,
        "wingspan_cm": 192.0,
        "goals": "Fast catch & shoot release off screens and high-elevation pull-up jump shots.",
        "pain_reported": False,
        "avatar": "PK",
        "tag": "Right handed, Advanced",
        "highlights": "Advanced, 186 cm, Quick release",
    },
    {
        "id": "usr_demo_pracheth",
        "name": "Pracheth",
        "player_id": "pracheth",
        "email": "pracheth@shotlab.local",
        "alt_email": None,
        "password": "123456",
        "handedness": "left",
        "skill_level": "intermediate",
        "shot_style": "set_shot",
        "height_cm": 178.0,
        "wingspan_cm": 180.0,
        "goals": "Free throw routine consistency, tight elbow alignment under ball, and high follow-through.",
        "pain_reported": False,
        "avatar": "PR",
        "tag": "Left handed, Set shot",
        "highlights": "Intermediate, 178 cm, Southpaw form",
    },
    {
        "id": "usr_demo_puneeth",
        "name": "Puneeth",
        "player_id": "puneeth",
        "email": "puneeth@shotlab.local",
        "alt_email": None,
        "password": "123456",
        "handedness": "right",
        "skill_level": "developing",
        "shot_style": "jump_shot",
        "height_cm": 175.0,
        "wingspan_cm": 178.0,
        "goals": "Landing stability and knee flexion rhythm without shoulder or back strain.",
        "pain_reported": True,
        "avatar": "PG",
        "tag": "Right handed, Soreness noted",
        "highlights": "Developing, 175 cm, Injury care",
    },
]

