"""SYNTHETIC pose fixtures for unit tests only.

Builds a pose cache (format 2) for a stick figure whose joint angles are set exactly, so
tests can check the measurement engine against known values. These are not real
recordings and must never be reported as evaluation results.
"""

import math

W, H = 1000.0, 1000.0
THIGH = SHIN = 160.0
UPPER_ARM = 140.0
FOREARM = 130.0


def _rotate(vx, vy, degrees):
    r = math.radians(degrees)
    return vx * math.cos(r) - vy * math.sin(r), vx * math.sin(r) + vy * math.cos(r)


def side_view_pose(knee_deg, elbow_deg, arm_elevation_deg=70.0, hip_x=500.0, torso_lean_deg=0.0):
    """Return {joint: (x_px, y_px)} for a right-handed shooter facing image-right, side view."""
    hip = (hip_x, 600.0)
    d = 2 * THIGH * math.sin(math.radians(knee_deg) / 2)
    ankle = (hip_x, 600.0 + d)
    knee = (hip_x + THIGH * math.cos(math.radians(knee_deg) / 2), 600.0 + d / 2)
    lean = math.radians(torso_lean_deg)
    shoulder = (hip[0] + 250 * math.sin(lean), hip[1] - 250 * math.cos(lean))
    a = math.radians(arm_elevation_deg)
    elbow = (shoulder[0] + UPPER_ARM * math.cos(a), shoulder[1] - UPPER_ARM * math.sin(a))
    # direction elbow->shoulder rotated so that angle shoulder-elbow-wrist == elbow_deg
    ex, ey = shoulder[0] - elbow[0], shoulder[1] - elbow[1]
    n = math.hypot(ex, ey)
    rx, ry = _rotate(ex / n, ey / n, -elbow_deg)
    wrist = (elbow[0] + FOREARM * rx, elbow[1] + FOREARM * ry)
    nose = (shoulder[0] + 18, shoulder[1] - 40)
    pose = {0: nose}
    # Side view: left and right joints almost overlap (small offset keeps them distinct).
    for left, right, point, offset in ((11, 12, shoulder, 8), (13, 14, elbow, 8), (15, 16, wrist, 8),
                                       (23, 24, hip, 6), (25, 26, knee, 6), (27, 28, ankle, 6),
                                       (29, 30, (ankle[0] - 15, ankle[1] + 10), 6), (31, 32, (ankle[0] + 25, ankle[1] + 12), 6)):
        pose[right] = point
        pose[left] = (point[0] - offset, point[1] + 2)
    if pose[15][1] > pose[16][1] - 1:  # keep the right wrist (shooting hand) highest
        pose[15] = (pose[15][0], pose[16][1] + 20)
    return pose


def front_view_pose(stance_ratio=1.0, elbow_offset_ratio=0.0, knee_inward_ratio=0.0):
    shoulder_w = 200.0
    pose = {0: (500, 300), 11: (600, 350), 12: (400, 350), 23: (560, 600), 24: (440, 600)}
    ankle_half = stance_ratio * shoulder_w / 2
    pose[27], pose[28] = (500 + ankle_half, 900), (500 - ankle_half, 900)
    hip_w = 120.0
    for left_hip, knee, ankle, side in ((23, 25, 27, 1), (24, 26, 28, -1)):
        hx, hy = pose[left_hip]
        ax, ay = pose[ankle]
        t = (750 - hy) / (ay - hy)
        line_x = hx + t * (ax - hx)
        pose[knee] = (line_x - side * knee_inward_ratio * hip_w, 750)
    pose[29], pose[30], pose[31], pose[32] = pose[27], pose[28], pose[27], pose[28]
    pose[14] = (400 - elbow_offset_ratio * shoulder_w, 300)  # right (shooting) elbow
    pose[16] = (pose[14][0], 200)
    pose[13], pose[15] = (620, 450), (630, 520)
    return pose


def make_cache(poses, fps=30.0, visibility=None, missing=None):
    """poses: list of {joint: (x, y)}; visibility: {joint: vis}; missing: set of (frame, joint)."""
    frames, world = [], []
    for f, pose in enumerate(poses):
        if pose is None:
            frames.append([])
            world.append(None)
            continue
        points, wpoints = [], []
        for j in range(33):
            if j not in pose or (missing and (f, j) in missing):
                points.append(None)
                wpoints.append(None)
                continue
            x, y = pose[j]
            vis = (visibility or {}).get(j, 0.95)
            points.append([x / W, y / H, vis, True])
            wpoints.append([(x - 500) / 400, (y - 600) / 400, 0.0])
        frames.append(points)
        world.append(wpoints)
    return {"format": 2, "fps": fps, "frame_count": len(poses), "width": W, "height": H,
            "landmark_indices": list(range(33)), "frames": frames, "world": world}


def shot_sequence(n_frames=75, knee_min=110.0, elbow_peak=178.0, drift_px=0.0, lean_change=0.0, legs_first=True):
    """One jump-shot-like attempt: stand, dip (f10-20), rise (f20-30), arm extends, hold, land."""
    poses = []
    for f in range(n_frames):
        ease = lambda t: (1 - math.cos(math.pi * t)) / 2  # smooth like real motion, no sharp corner
        if f < 10:
            knee = 170.0
        elif f <= 20:
            knee = 170.0 - (170.0 - knee_min) * ease((f - 10) / 10)
        elif f <= 30:
            knee = knee_min + (175.0 - knee_min) * ease((f - 20) / 10)
        else:
            knee = 175.0
        arm_start, arm_end = (24, 30) if legs_first else (14, 20)
        if f < arm_start:
            elbow, elevation = 70.0, 40.0 + min(f, arm_start) * 1.0
        elif f <= arm_end:
            elbow = 70.0 + (elbow_peak - 70.0) * (f - arm_start) / (arm_end - arm_start)
            elevation = 64.0 + 40.0 * (f - arm_start) / (arm_end - arm_start)
        elif f <= 50:
            elbow, elevation = elbow_peak, 104.0
        else:
            elbow, elevation = 90.0, 20.0
        hip_x = 500.0 + (drift_px * min(1.0, max(0.0, (f - 30) / 15)) if f > 30 else 0.0)
        lean = lean_change * math.sin(math.pi * min(1.0, max(0.0, (f - 10) / 30)))
        poses.append(side_view_pose(knee, elbow, elevation, hip_x=hip_x, torso_lean_deg=lean))
    return poses


def shot_row(shot_id="shot_synth_1", start=8, release=24, end=40, status="quarantined", outcome="unknown", **extra):
    row = {"shot_id": shot_id, "machine_start_frame": start, "machine_set_frame": None,
           "machine_release_frame": release, "machine_end_frame": end,
           "annotated_start_frame": start, "annotated_set_frame": None,
           "annotated_release_frame": release, "annotated_end_frame": end,
           "review_status": status, "outcome": outcome, "outcome_source": "unlabeled"}
    row.update(extra)
    return row
