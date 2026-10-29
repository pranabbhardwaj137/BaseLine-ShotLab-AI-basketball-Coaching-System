"""
shot_types.py - Canonical Shot Type Registry and Per-Shot-Type Configuration.

Single source of truth for basketball shot type taxonomy, finite-state detector
profiles, biomechanical metric weighting profiles, and capture requirements.
All new thresholds are provisional prototype configurations and advisory only.
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional

CONFIG_VERSION = "shot-types-1.0"

# Backward-compatibility alias mapping
SHOT_TYPE_ALIASES: Dict[str, str] = {
    "off_the_dribble": "pull_up",
    "off_dribble": "pull_up",
}

DEFAULT_DETECTOR_THRESHOLDS: Dict[str, Any] = {
    "knee_flexion_drop_min_deg": 160.0,
    "min_upward_velocity": -0.50,
    "wrist_rel_shoulder_thresh": -0.10,
    "debounce_frames": 2,
    "min_load_duration_ms": 100,
    "elbow_extension_velocity_trigger": 60.0,
    "require_kinetic_sequencing": True,
}

SHOT_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # Stationary Group
    # -------------------------------------------------------------------------
    "catch_and_shoot": {
        "id": "catch_and_shoot",
        "label": "Catch & shoot",
        "subtitle": "Spot up, quick release",
        "group": "stationary",
        "coaching_focus_tags": ["Release", "Knees"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["jump_shot", "set_shot"],
        "status": "prototype",
        "camera_setup_tips": "Position the camera 3 to 4 meters away, side-on or at 45 degrees, capturing full body from feet through follow-through.",
        "min_clip_requirements": {
            "min_frames": 25,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_hip", "right_hip", "left_shoulder", "right_shoulder"],
        },
        "detector_profile": {
            "profile_id": "detector_catch_and_shoot",
            "expected_phases": ["stance", "load", "set", "release", "follow_through"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 100,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "small",
            "window_padding_ms": {"before": 300, "after": 500},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility", "excessive_lateral_jitter"],
        },
        "metric_profile": {
            "weights": {
                "load_to_release_ms": 0.25,
                "knee_flexion_min_deg": 0.20,
                "kinetic_sequence_order": 0.25,
                "elbow_angle_at_release": 0.15,
                "landing_displacement": 0.15,
            },
            "metrics": {
                "load_to_release_ms": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_flexion_min_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "kinetic_sequence_order": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_release": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "free_throw": {
        "id": "free_throw",
        "label": "Free throw",
        "subtitle": "Stationary charity stripe",
        "group": "stationary",
        "coaching_focus_tags": ["Elbow", "Timing"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["set_shot"],
        "status": "prototype",
        "camera_setup_tips": "Set camera side-on at free throw line distance to evaluate routine consistency and elbow angle.",
        "min_clip_requirements": {
            "min_frames": 30,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_hip", "right_hip", "left_shoulder", "right_shoulder"],
        },
        "detector_profile": {
            "profile_id": "detector_free_throw",
            "expected_phases": ["stance", "load", "set", "release", "follow_through"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 120,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "false",
            "window_padding_ms": {"before": 350, "after": 500},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "elbow_angle_at_set": 0.25,
                "knee_flexion_min_deg": 0.20,
                "release_timing_ms": 0.25,
                "elbow_flare_deg": 0.20,
                "landing_displacement": 0.10,
            },
            "metrics": {
                "elbow_angle_at_set": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_flexion_min_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "release_timing_ms": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "elbow_flare_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.10, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "form_shooting": {
        "id": "form_shooting",
        "label": "Form shooting",
        "subtitle": "Close range, one hand",
        "group": "stationary",
        "coaching_focus_tags": ["Elbow", "Arc"],
        "recommended_camera_views": ["frontal", "oblique_45", "side_90"],
        "compatible_shot_styles": ["set_shot"],
        "status": "prototype",
        "camera_setup_tips": "Record 1 to 2 meters from hoop. Frontal or 45-degree angle helps measure elbow alignment and wrist release.",
        "min_clip_requirements": {
            "min_frames": 25,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow"],
        },
        "detector_profile": {
            "profile_id": "detector_form_shooting",
            "expected_phases": ["stance", "load", "set", "release", "follow_through"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 150,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "false",
            "window_padding_ms": {"before": 300, "after": 600},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "elbow_angle_at_set": 0.30,
                "elbow_flare_deg": 0.30,
                "wrist_snap_proxy": 0.25,
                "release_height_relative": 0.15,
            },
            "metrics": {
                "elbow_angle_at_set": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
                "elbow_flare_deg": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
                "wrist_snap_proxy": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "release_height_relative": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    # -------------------------------------------------------------------------
    # Dynamic Group
    # -------------------------------------------------------------------------
    "pull_up": {
        "id": "pull_up",
        "label": "Pull-up jumper",
        "subtitle": "Dribble, stop, rise",
        "group": "dynamic",
        "coaching_focus_tags": ["Balance", "Knees"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["jump_shot"],
        "status": "prototype",
        "camera_setup_tips": "Frame wide enough to record the approach dribble, deceleration stop, and jump landing without leaving frame.",
        "min_clip_requirements": {
            "min_frames": 40,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_hip", "right_hip", "left_ankle", "right_ankle"],
        },
        "detector_profile": {
            "profile_id": "detector_pull_up",
            "expected_phases": ["dribble_or_approach", "stop_or_plant", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "forward",
                "expected_displacement_direction": "forward",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 80,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 400, "after": 600},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["motion_blur_at_plant", "low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "stop_balance_sway": 0.25,
                "knee_flexion_min_deg": 0.20,
                "elbow_angle_at_set": 0.15,
                "kinetic_sequence_order": 0.20,
                "landing_displacement": 0.20,
            },
            "metrics": {
                "stop_balance_sway": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_flexion_min_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_set": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "kinetic_sequence_order": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "step_back": {
        "id": "step_back",
        "label": "Step-back",
        "subtitle": "Create space, then shoot",
        "group": "dynamic",
        "coaching_focus_tags": ["Balance", "Lean"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["jump_shot"],
        "status": "prototype",
        "camera_setup_tips": "Step-back requires extra clearance behind the shooter in frame. Ensure camera field of view has space for backward push-off and landing.",
        "min_clip_requirements": {
            "min_frames": 45,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_hip", "right_hip", "left_ankle", "right_ankle"],
        },
        "detector_profile": {
            "profile_id": "detector_step_back",
            "expected_phases": ["step_back_motion", "stop_or_plant", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "backward",
                "expected_displacement_direction": "backward",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 70,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 500, "after": 600},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["shooter_exits_frame_rear", "low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "backward_displacement_px_normalized": 0.25,
                "stop_balance_sway": 0.20,
                "torso_lean_deg": 0.15,
                "knee_extension_velocity": 0.20,
                "landing_displacement": 0.20,
            },
            "metrics": {
                "backward_displacement_px_normalized": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "stop_balance_sway": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "torso_lean_deg": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "knee_extension_velocity": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "fadeaway": {
        "id": "fadeaway",
        "label": "Fadeaway",
        "subtitle": "Lean back, high release",
        "group": "dynamic",
        "coaching_focus_tags": ["Lean", "Arc"],
        "recommended_camera_views": ["side_90"],
        "compatible_shot_styles": ["jump_shot"],
        "status": "prototype",
        "camera_setup_tips": "Fadeaway needs room behind the shooter. A true 90-degree side view is best to isolate sagittal torso lean and apex release height.",
        "min_clip_requirements": {
            "min_frames": 40,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
        },
        "detector_profile": {
            "profile_id": "detector_fadeaway",
            "expected_phases": ["load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "backward",
                "expected_displacement_direction": "backward",
                "lean_back": True,
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 80,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 400, "after": 700},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility", "camera_pan_artifact"],
        },
        "metric_profile": {
            "weights": {
                "torso_lean_deg": 0.30,
                "release_height_relative": 0.25,
                "knee_extension_velocity": 0.20,
                "elbow_angle_at_release": 0.25,
            },
            "metrics": {
                "torso_lean_deg": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
                "release_height_relative": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_extension_velocity": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_release": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "turnaround": {
        "id": "turnaround",
        "label": "Turnaround jumper",
        "subtitle": "Pivot, then shoot",
        "group": "dynamic",
        "coaching_focus_tags": ["Rotation", "Balance"],
        "recommended_camera_views": ["oblique_45", "frontal"],
        "compatible_shot_styles": ["jump_shot"],
        "status": "prototype",
        "camera_setup_tips": "Position camera at 45-degree angle or front view to capture shoulder-hip rotational separation during the pivot and elevation.",
        "min_clip_requirements": {
            "min_frames": 45,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
        },
        "detector_profile": {
            "profile_id": "detector_turnaround",
            "expected_phases": ["pivot", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "lateral",
                "expected_displacement_direction": "rotational",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 90,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 500, "after": 600},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["rotational_occlusion", "low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "hip_shoulder_separation_deg": 0.30,
                "stop_balance_sway": 0.20,
                "elbow_angle_at_set": 0.20,
                "landing_displacement": 0.30,
            },
            "metrics": {
                "hip_shoulder_separation_deg": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
                "stop_balance_sway": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_set": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "off_screen": {
        "id": "off_screen",
        "label": "Off a screen",
        "subtitle": "Curl or fade, then shoot",
        "group": "dynamic",
        "coaching_focus_tags": ["Balance", "Timing"],
        "recommended_camera_views": ["oblique_45", "side_90"],
        "compatible_shot_styles": ["jump_shot"],
        "status": "prototype",
        "camera_setup_tips": "Frame wide enough to track the curl cut deceleration and catch-to-shoot transition.",
        "min_clip_requirements": {
            "min_frames": 40,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_hip", "right_hip", "left_ankle", "right_ankle"],
        },
        "detector_profile": {
            "profile_id": "detector_off_screen",
            "expected_phases": ["dribble_or_approach", "stop_or_plant", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "lateral",
                "expected_displacement_direction": "curvilinear",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": None,
                "min_load_duration_ms": 75,
                "needs_calibration": True,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 450, "after": 600},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["lateral_motion_blur", "low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "load_to_release_ms": 0.25,
                "knee_flexion_min_deg": 0.20,
                "stop_balance_sway": 0.25,
                "elbow_angle_at_release": 0.15,
                "landing_displacement": 0.15,
            },
            "metrics": {
                "load_to_release_ms": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_flexion_min_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "stop_balance_sway": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_release": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "landing_displacement": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    # -------------------------------------------------------------------------
    # Range Group
    # -------------------------------------------------------------------------
    "mid_range": {
        "id": "mid_range",
        "label": "Mid-range",
        "subtitle": "Elbow or baseline spot",
        "group": "range",
        "coaching_focus_tags": ["Knees", "Release"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["jump_shot", "set_shot"],
        "status": "prototype",
        "camera_setup_tips": "Set camera 4 to 5 meters away with clear view of feet to evaluate knee drive and vertical lift.",
        "min_clip_requirements": {
            "min_frames": 30,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_knee", "right_knee"],
        },
        "detector_profile": {
            "profile_id": "detector_mid_range",
            "expected_phases": ["stance", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 100,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 350, "after": 550},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "kinetic_sequence_order": 0.25,
                "knee_extension_velocity": 0.25,
                "elbow_angle_at_release": 0.20,
                "release_timing_ms": 0.15,
                "release_height_relative": 0.15,
            },
            "metrics": {
                "kinetic_sequence_order": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_extension_velocity": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_release": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "release_timing_ms": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "release_height_relative": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    "three_pointer": {
        "id": "three_pointer",
        "label": "Three-pointer",
        "subtitle": "Deep range",
        "group": "range",
        "coaching_focus_tags": ["Knees", "Arc"],
        "recommended_camera_views": ["side_90", "oblique_45"],
        "compatible_shot_styles": ["jump_shot", "set_shot"],
        "status": "prototype",
        "camera_setup_tips": "At deep range, ensure the camera is far enough back to catch the full arc trajectory and full jump extension.",
        "min_clip_requirements": {
            "min_frames": 35,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_knee", "right_knee"],
        },
        "detector_profile": {
            "profile_id": "detector_three_pointer",
            "expected_phases": ["stance", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 90,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 350, "after": 550},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "kinetic_sequence_order": 0.25,
                "knee_extension_velocity": 0.25,
                "elbow_angle_at_release": 0.20,
                "release_timing_ms": 0.15,
                "release_height_relative": 0.15,
            },
            "metrics": {
                "kinetic_sequence_order": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_extension_velocity": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "elbow_angle_at_release": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "release_timing_ms": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
                "release_height_relative": {"initial_weight": 0.15, "reference_range": None, "needs_calibration": True},
            },
            "compare_leg_drive_to_mid_range": True,
        },
    },

    "bank_shot": {
        "id": "bank_shot",
        "label": "Bank shot",
        "subtitle": "Angle off the glass",
        "group": "range",
        "coaching_focus_tags": ["Arc", "Elbow"],
        "recommended_camera_views": ["oblique_45", "side_90"],
        "compatible_shot_styles": ["jump_shot", "set_shot"],
        "status": "prototype",
        "camera_setup_tips": "An oblique 45-degree angle view is recommended to see the shooter, the backboard angle, and the ball flight path together.",
        "min_clip_requirements": {
            "min_frames": 30,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow"],
        },
        "detector_profile": {
            "profile_id": "detector_bank_shot",
            "expected_phases": ["stance", "load", "set", "release", "follow_through", "landing"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 100,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "full",
            "window_padding_ms": {"before": 300, "after": 550},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "elbow_angle_at_release": 0.30,
                "arc_proxy": 0.30,
                "release_height_relative": 0.20,
                "elbow_flare_deg": 0.20,
            },
            "metrics": {
                "elbow_angle_at_release": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True},
                "arc_proxy": {"initial_weight": 0.30, "reference_range": None, "needs_calibration": True, "advisory_only": True},
                "release_height_relative": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
                "elbow_flare_deg": {"initial_weight": 0.20, "reference_range": None, "needs_calibration": True},
            },
        },
    },

    # -------------------------------------------------------------------------
    # Fallback Group
    # -------------------------------------------------------------------------
    "other": {
        "id": "other",
        "label": "Other",
        "subtitle": "Custom practice",
        "group": "other",
        "coaching_focus_tags": ["Balance", "Timing"],
        "recommended_camera_views": ["side_90", "oblique_45", "frontal"],
        "compatible_shot_styles": ["jump_shot", "set_shot"],
        "status": "prototype",
        "camera_setup_tips": "Position camera side-on or at 45 degrees so whole body remains visible throughout the motion.",
        "min_clip_requirements": {
            "min_frames": 25,
            "min_pose_confidence": 0.50,
            "required_landmarks_visible": ["left_shoulder", "right_shoulder"],
        },
        "detector_profile": {
            "profile_id": "detector_default",
            "expected_phases": ["stance", "load", "set", "release", "follow_through"],
            "pre_shot_motion": {
                "expected_hip_displacement": "none",
                "expected_displacement_direction": "stationary",
            },
            "load_detection": {
                "knee_flexion_drop_min_deg": 160.0,
                "min_load_duration_ms": 100,
                "needs_calibration": False,
            },
            "release_detection": {
                "wrist_above_shoulder_required": True,
                "elbow_extension_velocity_trigger": None,
                "needs_calibration": True,
            },
            "jump_expected": "small",
            "window_padding_ms": {"before": 300, "after": 500},
            "reject_conditions": {
                "min_pose_confidence": 0.40,
                "max_occlusion": 0.60,
                "max_camera_motion": 0.30,
            },
            "confidence_downgrade_rules": ["low_visibility"],
        },
        "metric_profile": {
            "weights": {
                "elbow_angle_at_release": 0.25,
                "knee_flexion_min_deg": 0.25,
                "kinetic_sequence_order": 0.25,
                "release_timing_ms": 0.25,
            },
            "metrics": {
                "elbow_angle_at_release": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "knee_flexion_min_deg": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "kinetic_sequence_order": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
                "release_timing_ms": {"initial_weight": 0.25, "reference_range": None, "needs_calibration": True},
            },
        },
    },
}


def resolve_shot_type(raw_type: Optional[str]) -> str:
    """
    Resolve raw shot type string to canonical shot type ID.
    Supports aliases such as off_the_dribble and off_dribble -> pull_up.
    Defaults to 'other' if unknown or empty.
    """
    if not raw_type:
        return "other"
    cleaned = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in SHOT_TYPE_ALIASES:
        return SHOT_TYPE_ALIASES[cleaned]
    if cleaned in SHOT_TYPE_REGISTRY:
        return cleaned
    return "other"


def get_shot_type(shot_type_id: Optional[str]) -> Dict[str, Any]:
    """Retrieve the full shot type registry record for an ID or alias."""
    canonical_id = resolve_shot_type(shot_type_id)
    return SHOT_TYPE_REGISTRY.get(canonical_id, SHOT_TYPE_REGISTRY["other"])


def get_all_shot_types() -> Dict[str, Dict[str, Any]]:
    """Return dictionary of all registered shot types."""
    return SHOT_TYPE_REGISTRY


def validate_shot_types_config() -> List[str]:
    """
    Validate the shot types registry:
    - Verifies all weights sum to 1.0 (with 1e-4 tolerance).
    - Checks required schema keys.
    - Ensures all reference ranges are None and needs_calibration is True.
    Returns list of error messages (empty if valid).
    """
    errors: List[str] = []
    required_keys = [
        "id", "label", "subtitle", "group", "coaching_focus_tags",
        "recommended_camera_views", "compatible_shot_styles", "status",
        "detector_profile", "metric_profile", "min_clip_requirements"
    ]

    for st_id, entry in SHOT_TYPE_REGISTRY.items():
        for k in required_keys:
            if k not in entry:
                errors.append(f"Shot type '{st_id}' missing required key: {k}")

        metric_profile = entry.get("metric_profile", {})
        weights = metric_profile.get("weights", {})
        total_weight = sum(weights.values())
        if not math.isclose(total_weight, 1.0, rel_tol=1e-4, abs_tol=1e-4):
            errors.append(f"Shot type '{st_id}' weights do not sum to 1.0 (got {total_weight})")

        metrics = metric_profile.get("metrics", {})
        for m_name, m_spec in metrics.items():
            if m_spec.get("reference_range") is not None:
                errors.append(f"Shot type '{st_id}' metric '{m_name}' has non-null reference_range")
            if not m_spec.get("needs_calibration", False):
                errors.append(f"Shot type '{st_id}' metric '{m_name}' must have needs_calibration=True")

    return errors


resolve_shot_type_alias = resolve_shot_type
