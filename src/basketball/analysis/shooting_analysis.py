"""Per-attempt shooting biomechanics measured from the cached MediaPipe pose series.

Everything here is computed from the pose cache written by ``video_analysis_service``:
normalised image coordinates (x, y), landmark visibility and validity for each frame,
plus MediaPipe's estimated world coordinates when the cache has them (format 2).

Design rules (see METRIC_DEFINITIONS for per-metric limits):
- Image-plane angles are labelled ``image_2d``; they are projections, not true joint
  angles, and are only trusted from the camera views listed for each metric.
- World-coordinate angles are labelled ``world_3d_estimate``: monocular model estimates.
- Ratios are normalised by the player's own torso length or shoulder width in the image;
  nothing is converted to centimetres.
- Every metric carries a confidence label. ``low`` values are shown but are excluded
  from coaching and consistency statistics; ``not_measurable`` values have no number.
- Nothing is filled in when landmarks are missing.
"""

from __future__ import annotations

import gzip
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Optional

ANALYSIS_VERSION = "shooting-analysis-1.4"

# MediaPipe Pose landmark indices.
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_FOOT, R_FOOT = 31, 32

SIDE_JOINTS = {
    "right": {"shoulder": R_SHOULDER, "elbow": R_ELBOW, "wrist": R_WRIST, "hip": R_HIP,
              "knee": R_KNEE, "ankle": R_ANKLE},
    "left": {"shoulder": L_SHOULDER, "elbow": L_ELBOW, "wrist": L_WRIST, "hip": L_HIP,
             "knee": L_KNEE, "ankle": L_ANKLE},
}

GOOD, FAIR, UNSUPPORTED = "good", "fair", "unsupported"
SIDE_VIEWS = {"side_90": GOOD, "oblique_45": FAIR, "frontal": UNSUPPORTED, "rear": UNSUPPORTED}
FRONT_VIEWS = {"side_90": UNSUPPORTED, "oblique_45": FAIR, "frontal": GOOD, "rear": GOOD}
ALL_VIEWS = {"side_90": GOOD, "oblique_45": GOOD, "frontal": GOOD, "rear": GOOD}
ALL_VIEWS_FAIR = {"side_90": FAIR, "oblique_45": FAIR, "frontal": FAIR, "rear": FAIR}
FRONTAL_LIKE = {"frontal", "rear"}

CONFIDENCE_ORDER = {"not_measurable": 0, "low": 1, "medium": 2, "high": 3}
USABLE = {"medium", "high"}

# Every metric the engine can report. ``views`` gives how trustworthy the metric is
# from each declared camera view. Thresholds used for coaching live in shot_coach.py.
METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "knee_flexion_min_deg": {
        "label": "Deepest knee bend", "category": "lower_body", "unit": "°", "basis": "image_2d",
        "plausible": (40, 180), "views": SIDE_VIEWS,
        "definition": "Smallest hip–knee–ankle angle between the start of the attempt and the release (the 'dip'). 180° is a straight leg.",
        "limitation": "Image-plane projection; reads as a straighter leg than reality when the camera is not side-on. Light smoothing can round off a very sharp dip by a degree or two.",
    },
    "hip_flexion_min_deg": {
        "label": "Deepest hip bend", "category": "lower_body", "unit": "°", "basis": "image_2d",
        "plausible": (40, 180), "views": SIDE_VIEWS,
        "definition": "Smallest shoulder–hip–knee angle between start and release.",
        "limitation": "Image-plane projection; trunk rotation changes the apparent angle.",
    },
    "knee_extension_range_deg": {
        "label": "Leg drive (knee extension)", "category": "lower_body", "unit": "°", "basis": "image_2d",
        "plausible": (0, 140), "views": SIDE_VIEWS,
        "definition": "Largest knee angle between the dip and the release, minus the knee angle at the dip.",
        "limitation": "Describes how much the knee straightens in the image, not force or jump height.",
    },
    "elbow_angle_set_deg": {
        "label": "Elbow angle when loaded", "category": "preparation", "unit": "°", "basis": "image_2d",
        "plausible": (25, 180), "views": SIDE_VIEWS,
        "definition": "Smallest shoulder–elbow–wrist angle of the shooting arm between the dip and the release (the set position).",
        "limitation": "The ball and hand often hide the wrist; check confidence.",
    },
    "elbow_angle_release_deg": {
        "label": "Elbow angle at release", "category": "release", "unit": "°", "basis": "image_2d",
        "plausible": (25, 180), "views": SIDE_VIEWS,
        "definition": "Shooting-arm shoulder–elbow–wrist angle at the release frame: your corrected release if you set one, otherwise the first frame where the arm is within 8° of full extension with the wrist above the shoulder.",
        "limitation": "The ball is not tracked, so the release is inferred from the arm; one frame early or late can change this by several degrees.",
    },
    "elbow_angle_release_3d_deg": {
        "label": "Elbow angle at release (3D estimate)", "category": "release", "unit": "°",
        "basis": "world_3d_estimate", "plausible": (25, 180), "views": ALL_VIEWS_FAIR,
        "definition": "Same joint angle from MediaPipe's estimated 3D world coordinates.",
        "limitation": "Monocular depth is inferred by the model, not measured; treat as an estimate.",
    },
    "elbow_extension_peak_deg": {
        "label": "Arm extension through release", "category": "release", "unit": "°", "basis": "image_2d",
        "plausible": (40, 180), "views": SIDE_VIEWS,
        "definition": "Largest shooting-arm elbow angle from 0.1 s before to 0.5 s after release.",
        "limitation": "Image-plane projection; foreshortening makes an extended arm pointing at the camera look bent.",
    },
    "shoulder_elevation_release_deg": {
        "label": "Arm elevation at release", "category": "release", "unit": "°", "basis": "image_2d",
        "plausible": (10, 200), "views": SIDE_VIEWS,
        "definition": "Hip–shoulder–elbow angle of the shooting side at release (how high the upper arm is raised).",
        "limitation": "Image-plane projection.",
    },
    "release_height_ratio": {
        "label": "Release height", "category": "release", "unit": "torso lengths", "basis": "image_ratio",
        "plausible": (-1.5, 2.5), "views": ALL_VIEWS,
        "definition": "How far the shooting wrist is above the shooting shoulder at release, divided by your torso length in the image.",
        "limitation": "Relative to your own body in the image, not a real height; a jump does not change it much.",
    },
    "torso_lean_release_deg": {
        "label": "Torso lean at release", "category": "torso", "unit": "°", "basis": "image_2d",
        "plausible": (0, 60), "views": ALL_VIEWS,
        "definition": "Angle between the hip-centre→shoulder-centre line and vertical at release. Side view shows forward/back lean; front view shows sideways lean.",
        "limitation": "Assumes the camera is level; a tilted phone adds a constant offset.",
    },
    "torso_lean_change_deg": {
        "label": "Torso movement during the shot", "category": "torso", "unit": "°", "basis": "image_2d",
        "plausible": (0, 90), "views": ALL_VIEWS,
        "definition": "Range of the torso-lean angle from the start of the attempt to 0.3 s after release.",
        "limitation": "Some forward lean on the way up and back on landing is normal; compare attempts rather than chasing zero.",
    },
    "hip_drift_ratio": {
        "label": "Body drift (dip to landing)", "category": "balance", "unit": "torso lengths", "basis": "image_ratio",
        "views": ALL_VIEWS,
        "definition": "Horizontal movement of the hip centre from the dip to the landing window (0.4–0.8 s after release), divided by torso length.",
        "limitation": "Side view shows forward/back drift; front view shows sideways drift. A moving camera invalidates it.",
    },
    "landing_offset_ratio": {
        "label": "Landing spot vs take-off spot", "category": "balance", "unit": "torso lengths", "basis": "image_ratio",
        "views": ALL_VIEWS,
        "definition": "Horizontal distance between the ankle centre before the attempt and in the landing window, divided by torso length.",
        "limitation": "Needs both ankles in frame; side view cannot show sideways landing and front view cannot show forward landing.",
    },
    "stance_width_ratio": {
        "label": "Stance width", "category": "stance", "unit": "× shoulder width", "basis": "image_ratio",
        "views": FRONT_VIEWS,
        "definition": "Distance between the ankles divided by the distance between the shoulders, before the attempt starts.",
        "limitation": "Only meaningful from the front or an angle; from the side the feet overlap.",
    },
    "elbow_flare_ratio": {
        "label": "Shooting elbow position", "category": "alignment", "unit": "× shoulder width", "basis": "image_ratio",
        "views": FRONT_VIEWS,
        "definition": "How far the shooting elbow sits outside (+) or inside (−) the shooting shoulder at the set position, divided by shoulder width.",
        "limitation": "Front view only. Many good shooters have a slightly turned stance and elbow; this is a style marker, not an error by itself.",
    },
    "knee_inward_ratio": {
        "label": "Knee position over the foot at the dip", "category": "lower_body", "unit": "× hip width", "basis": "image_ratio",
        "views": FRONT_VIEWS,
        "definition": "How far a knee sits inside (+) the straight line from hip to ankle at the dip, divided by hip width (larger of the two legs).",
        "limitation": "2D front-view estimate only; it cannot measure joint load and is not a medical assessment.",
    },
    "sequencing_lag_ms": {
        "label": "Legs-to-arm timing", "category": "timing", "unit": "ms", "basis": "timing",
        "plausible": (-600, 800), "views": SIDE_VIEWS,
        "definition": "Between the dip and the release: time from the fastest knee straightening to the fastest elbow straightening. Positive means the legs lead and the arm follows.",
        "limitation": "Resolution is one frame (≈33 ms at 30 fps); smoothing of the pose can shift peaks by a frame.",
    },
    "release_vs_leg_extension_ms": {
        "label": "Release timing vs leg extension", "category": "timing", "unit": "ms", "basis": "timing",
        "plausible": (-200, 1500), "views": SIDE_VIEWS,
        "definition": "Release frame minus the frame where the knee is straightest between the dip and the release. Near zero means the release comes as the legs finish extending; large positive values mean a pause between leg drive and release.",
        "limitation": "Depends on the release frame; uses pose only, so the exact moment the ball leaves the hand is not seen.",
    },
    "follow_through_hold_ms": {
        "label": "Follow-through hold", "category": "follow_through", "unit": "ms", "basis": "timing",
        "views": ALL_VIEWS,
        "definition": "How long the shooting wrist stays above the shooting shoulder after release (capped at 1.5 s).",
        "limitation": "Ends early if the next action starts or the arm leaves the frame.",
    },
    "prep_duration_ms": {
        "label": "Shot preparation time", "category": "timing", "unit": "ms", "basis": "timing",
        "views": ALL_VIEWS,
        "definition": "Time from the detected start of the attempt to the release.",
        "limitation": "The start is a detector estimate; correct it in Review if needed.",
    },
}


# --------------------------------------------------------------------------- cache io
def load_pose_cache(path: str | Path) -> dict[str, Any]:
    """Read a gzip pose cache written by video_analysis_service (format 1 or 2)."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    if "frames" not in data or "landmark_indices" not in data:
        raise ValueError("Pose cache is missing frames or landmark indices")
    return data


class PoseSeries:
    """Convenient access to one clip's cached landmarks in pixel units."""

    def __init__(self, cache: dict[str, Any]):
        self.fps = float(cache.get("fps") or 30.0)
        self.width = float(cache.get("width") or 1.0)
        self.height = float(cache.get("height") or 1.0)
        self.frames = cache["frames"]
        self.world = cache.get("world")
        self.indices = {int(joint): pos for pos, joint in enumerate(cache["landmark_indices"])}
        self.n = len(self.frames)
        self.format = int(cache.get("format") or 1)
        # Format 1 caches hold causally smoothed (time-lagged) landmarks; format 2 holds raw
        # landmarks, which get a centred 3-frame average here (reduces jitter, adds no lag).
        self.lagged = self.format < 2
        if not self.lagged:
            self.frames = _centred_smooth(self.frames)

    def has(self, joint: int) -> bool:
        return joint in self.indices

    def raw(self, frame: int, joint: int):
        if not 0 <= frame < self.n or joint not in self.indices:
            return None
        points = self.frames[frame]
        if not points:
            return None
        return points[self.indices[joint]]

    def point(self, frame: int, joint: int, min_visibility: float = 0.0):
        """Pixel (x, y) and visibility, or None when absent/invalid/below min_visibility."""
        value = self.raw(frame, joint)
        if not value or not value[3] or value[2] < min_visibility:
            return None
        return (value[0] * self.width, value[1] * self.height, float(value[2]))

    def visibility(self, frame: int, joint: int) -> float:
        value = self.raw(frame, joint)
        if not value or not value[3]:
            return 0.0
        return float(value[2])

    def world_point(self, frame: int, joint: int):
        if not self.world or not 0 <= frame < len(self.world) or joint not in self.indices:
            return None
        points = self.world[frame]
        if not points:
            return None
        value = points[self.indices[joint]]
        return tuple(value) if value else None

    def clamp(self, frame: float) -> int:
        return int(max(0, min(self.n - 1, round(frame))))

    def window(self, start: float, end: float) -> range:
        a, b = self.clamp(start), self.clamp(end)
        return range(a, b + 1) if b >= a else range(0)

    def time_s(self, frame: Optional[int]) -> Optional[float]:
        return None if frame is None else round(frame / self.fps, 3)


def _centred_smooth(frames):
    """Weighted 1-2-1 average of x, y over frames f-1..f+1 (present, valid joints); keeps vis/valid.

    Centred, so it adds no time lag; it slightly rounds off very sharp turning points
    (about 3° on a synthetic 6°-per-frame V-shaped dip; under 1° on a smooth dip).
    """
    out = []
    n = len(frames)
    for f in range(n):
        current = frames[f]
        if not current:
            out.append(current)
            continue
        smoothed = []
        for j, value in enumerate(current):
            if not value or not value[3]:
                smoothed.append(value)
                continue
            sx = sy = total = 0.0
            for g, weight in ((f - 1, 1.0), (f, 2.0), (f + 1, 1.0)):
                if 0 <= g < n and frames[g] and j < len(frames[g]):
                    other = frames[g][j]
                    if other and other[3]:
                        sx += weight * other[0]
                        sy += weight * other[1]
                        total += weight
            smoothed.append([sx / total, sy / total, value[2], value[3]])
        out.append(smoothed)
    return out


# --------------------------------------------------------------------------- geometry
def angle_2d(a, b, c) -> Optional[float]:
    """Angle ABC in degrees from 2D points."""
    if not a or not b or not c:
        return None
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def angle_3d(a, b, c) -> Optional[float]:
    if not a or not b or not c:
        return None
    v1 = [a[i] - b[i] for i in range(3)]
    v2 = [c[i] - b[i] for i in range(3)]
    n1 = math.sqrt(sum(x * x for x in v1))
    n2 = math.sqrt(sum(x * x for x in v2))
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos = max(-1.0, min(1.0, sum(v1[i] * v2[i] for i in range(3)) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def midpoint(p, q):
    if not p or not q:
        return None
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, min(p[2], q[2]))


def lean_from_vertical(hip_mid, shoulder_mid) -> Optional[float]:
    """Signed angle (degrees) of hip→shoulder line from image vertical; + means shoulders to the right."""
    if not hip_mid or not shoulder_mid:
        return None
    dx = shoulder_mid[0] - hip_mid[0]
    dy = hip_mid[1] - shoulder_mid[1]  # image y grows downward
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return None
    return math.degrees(math.atan2(dx, dy))


def _median(values: Iterable[float]) -> Optional[float]:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(values) if values else None


def _smooth(series: list[Optional[float]], radius: int = 1) -> list[Optional[float]]:
    out = []
    for i in range(len(series)):
        window = [v for v in series[max(0, i - radius): i + radius + 1] if v is not None]
        out.append(sum(window) / len(window) if window and series[i] is not None else None)
    return out


# --------------------------------------------------------------------------- confidence
def _confidence(series: PoseSeries, frames: Iterable[int], joints: Iterable[int], view_support: str):
    """Return (label, mean_visibility, coverage) for the joints over the frames used."""
    frames = list(frames)
    joints = list(joints)
    if not frames or not joints:
        return "not_measurable", 0.0, 0.0
    if any(not series.has(j) for j in joints):
        return "not_measurable", 0.0, 0.0
    per_joint = [statistics.mean(series.visibility(f, j) for f in frames) for j in joints]
    complete = sum(1 for f in frames if all(series.point(f, j) for j in joints))
    coverage = complete / len(frames)
    vis = min(per_joint)
    if coverage < 0.5 or vis < 0.3:
        return "low" if coverage > 0 else "not_measurable", round(vis, 2), round(coverage, 2)
    if vis >= 0.75 and coverage >= 0.85 and view_support == GOOD:
        label = "high"
    elif vis >= 0.55 and coverage >= 0.6:
        label = "medium"
    else:
        label = "low"
    if view_support == FAIR and label == "high":
        label = "medium"
    return label, round(vis, 2), round(coverage, 2)


SUPPORT_RANK = {UNSUPPORTED: 0, FAIR: 1, GOOD: 2}


def view_support_for(definition, camera_view, estimated_view=None):
    """Support level for a metric: the weaker of the declared view and the view seen in the footage."""
    declared = definition["views"].get(camera_view, UNSUPPORTED)
    if not estimated_view or estimated_view == camera_view:
        return declared, None
    seen = definition["views"].get(estimated_view, UNSUPPORTED)
    if SUPPORT_RANK[seen] < SUPPORT_RANK[declared]:
        return seen, estimated_view
    return declared, None


def _metric(key: str, camera_view: str, series: PoseSeries, value, frame, frames, joints,
            detail: Optional[str] = None, reason: Optional[str] = None, estimated_view: Optional[str] = None) -> dict[str, Any]:
    definition = METRIC_DEFINITIONS[key]
    view_support, limited_by = view_support_for(definition, camera_view, estimated_view)
    record = {
        "key": key, "label": definition["label"], "category": definition["category"],
        "unit": definition["unit"], "basis": definition["basis"], "view_support": view_support,
        "value": None, "frame": frame, "time_s": series.time_s(frame), "confidence": "not_measurable",
        "visibility": 0.0, "coverage": 0.0, "detail": detail, "reason": reason,
    }
    if view_support == UNSUPPORTED:
        shown = limited_by or camera_view
        prefix = (f"The footage looks like a {VIEW_NAMES.get(shown, shown)} (you selected {VIEW_NAMES.get(camera_view, camera_view)}), "
                  "so this is not measurable; it needs ") if limited_by else \
            f"Not measurable from a {VIEW_NAMES.get(camera_view, camera_view)}; needs "
        record["reason"] = prefix + " or ".join(VIEW_NAMES[v] for v, s in definition["views"].items() if s != UNSUPPORTED) + "."
        record["frame"], record["time_s"] = None, None
        return record
    if value is None:
        record["reason"] = reason or "The landmarks needed for this measurement were not visible."
        return record
    label, vis, coverage = _confidence(series, frames, joints, view_support)
    if label == "not_measurable":
        record["reason"] = reason or "The landmarks needed for this measurement were not visible."
        return record
    if isinstance(value, float):
        value = round(value, 2 if definition["basis"] == "image_ratio" else 1)
    record.update({"value": value, "confidence": label, "visibility": vis, "coverage": coverage})
    bounds = definition.get("plausible")
    if bounds and not bounds[0] <= value <= bounds[1]:
        record["confidence"] = "low"
        record["reason"] = (f"{value}{definition['unit']} is outside the plausible range ({bounds[0]}–{bounds[1]}); "
                            "a landmark was probably misplaced (often the wrist behind the ball). Not used for coaching.")
    elif label == "low":
        record["reason"] = "Low landmark visibility or coverage; shown for reference and not used for coaching."
    return record


VIEW_NAMES = {"side_90": "side view", "oblique_45": "45° angled view", "frontal": "front view", "rear": "view from behind"}


# --------------------------------------------------------------------------- per attempt
def determine_shooting_side(series: PoseSeries, release_frame: Optional[int], handedness: str = "unspecified"):
    if handedness in {"right", "left"}:
        return handedness, "profile"
    frames = series.window((release_frame or 0) - 2, (release_frame or 0) + 2) if release_frame is not None else range(0)
    left = [series.point(f, L_WRIST) for f in frames]
    right = [series.point(f, R_WRIST) for f in frames]
    left_y = _median(p[1] for p in left if p)
    right_y = _median(p[1] for p in right if p)
    if left_y is None and right_y is None:
        return "right", "default (wrists not visible)"
    if left_y is None:
        return "right", "higher wrist at release"
    if right_y is None:
        return "left", "higher wrist at release"
    return ("left" if left_y < right_y else "right"), "higher wrist at release"


RELEASE_EXTENSION_MARGIN = 8.0


def estimate_release_frame(series: PoseSeries, arm: dict, first: int, last: float) -> Optional[int]:
    """Pose-only release estimate (the ball itself is not tracked); None if the arm is not visible."""
    window = list(series.window(first, last))
    angles = []
    for f in window:
        angle = angle_2d(series.point(f, arm["shoulder"], 0.4), series.point(f, arm["elbow"], 0.4),
                         series.point(f, arm["wrist"], 0.4))
        angles.append(angle)
    valid = [a for a in angles if a is not None]
    if len(valid) < max(3, len(window) // 3):
        return None
    peak = max(valid)
    for f, angle in zip(window, angles):
        if angle is None or angle < peak - RELEASE_EXTENSION_MARGIN:
            continue
        wrist, shoulder = series.point(f, arm["wrist"]), series.point(f, arm["shoulder"])
        if wrist and shoulder and wrist[1] < shoulder[1]:
            return f
    return None


def _choose_leg(series: PoseSeries, frames: range) -> tuple[str, dict]:
    def score(side):
        joints = SIDE_JOINTS[side]
        return sum(series.visibility(f, joints[k]) for f in frames for k in ("hip", "knee", "ankle"))
    side = "left" if score("left") > score("right") else "right"
    return side, SIDE_JOINTS[side]


def _torso_length(series: PoseSeries, frames: Iterable[int]) -> Optional[float]:
    lengths = []
    for f in frames:
        sm = midpoint(series.point(f, L_SHOULDER), series.point(f, R_SHOULDER))
        hm = midpoint(series.point(f, L_HIP), series.point(f, R_HIP))
        if sm and hm:
            lengths.append(math.hypot(sm[0] - hm[0], sm[1] - hm[1]))
    value = _median(lengths)
    return value if value and value > 1.0 else None


def _facing(series: PoseSeries, frames: Iterable[int]) -> int:
    """+1 if the player faces image-right, -1 if image-left, 0 if unknown (side views)."""
    offsets = []
    for f in frames:
        nose = series.point(f, NOSE)
        sm = midpoint(series.point(f, L_SHOULDER), series.point(f, R_SHOULDER))
        if nose and sm:
            offsets.append(nose[0] - sm[0])
    value = _median(offsets)
    if value is None or abs(value) < 2:
        return 0
    return 1 if value > 0 else -1


def analyze_attempt(series: PoseSeries, shot: dict[str, Any], camera_view: str, *,
                    handedness: str = "unspecified", next_start: Optional[int] = None,
                    attempt_index: int = 1, estimated_view: Optional[str] = None) -> dict[str, Any]:
    """Measure one attempt. ``shot`` uses annotated boundaries when present, else machine ones."""
    def boundary(name):
        value = shot.get(f"annotated_{name}_frame")
        return value if value is not None else shot.get(f"machine_{name}_frame")

    start, set_frame, release, end = boundary("start"), boundary("set"), boundary("release"), boundary("end")
    machine_release = shot.get("machine_release_frame")
    annotated_release = shot.get("annotated_release_frame")
    release_source = "you" if annotated_release is not None and annotated_release != machine_release else "detector"
    detector_release = release
    fps = series.fps
    metrics: dict[str, dict[str, Any]] = {}
    if start is None:
        start = 0
    if end is None:
        end = release if release is not None else start
    landing_cap = series.n - 1 if next_start is None else max(end, next_start - 1)
    side, side_basis = determine_shooting_side(series, release, handedness)
    arm = SIDE_JOINTS[side]
    attempt_frames = series.window(start - 0.3 * fps, min(landing_cap, (release or end) + 0.8 * fps))
    torso = _torso_length(series, attempt_frames)
    facing = _facing(series, attempt_frames) if camera_view not in FRONTAL_LIKE else 0

    def put(key, *args, **kwargs):
        metrics[key] = _metric(key, camera_view, series, *args, estimated_view=estimated_view, **kwargs)

    if release is None:
        for key in METRIC_DEFINITIONS:
            put(key, None, None, [], [], reason="No release frame is marked for this attempt; add one in Review.")
        return _attempt_record(series, shot, attempt_index, start, None, end, side, side_basis, None, metrics)

    # The detector's "release" is the transition into its releasing phase, which is usually
    # the start of the arm's rise. Unless you corrected it, estimate the release-like moment
    # from the pose: first frame where the shooting arm is within RELEASE_EXTENSION_MARGIN
    # degrees of its peak extension with the wrist above the shoulder.
    if release_source == "detector":
        refined = estimate_release_frame(series, arm, release, min(landing_cap, release + 0.6 * fps))
        if refined is not None and refined != release:
            release = refined
            release_source = "estimated from arm extension"
    rise = series.window(start, release)
    leg_side, leg = _choose_leg(series, rise)

    def knee_angle(f):
        return angle_2d(series.point(f, leg["hip"]), series.point(f, leg["knee"]), series.point(f, leg["ankle"]))

    def elbow_angle(f):
        return angle_2d(series.point(f, arm["shoulder"]), series.point(f, arm["elbow"]), series.point(f, arm["wrist"]))

    knee_series = {f: knee_angle(f) for f in series.window(start, release + 0.5 * fps)}
    elbow_series = {f: elbow_angle(f) for f in series.window(start, release + 0.5 * fps)}

    # Lower body ------------------------------------------------------------------
    rise_knees = [(f, knee_series.get(f)) for f in rise if knee_series.get(f) is not None]
    dip = min(rise_knees, key=lambda item: item[1])[0] if rise_knees else None
    leg_joints = [leg["hip"], leg["knee"], leg["ankle"]]
    put("knee_flexion_min_deg", knee_series.get(dip) if dip is not None else None, dip, [dip] if dip is not None else [],
        leg_joints, detail=f"{leg_side} leg")
    hip_values = [(f, angle_2d(series.point(f, arm["shoulder"]), series.point(f, leg["hip"]), series.point(f, leg["knee"])))
                  for f in rise]
    hip_values = [item for item in hip_values if item[1] is not None]
    hip_min = min(hip_values, key=lambda item: item[1]) if hip_values else (None, None)
    put("hip_flexion_min_deg", hip_min[1], hip_min[0], [hip_min[0]] if hip_min[0] is not None else [],
        [arm["shoulder"], leg["hip"], leg["knee"]])
    peak_knee = None
    if dip is not None:
        # Take-off phase only: after release the knees straighten again when you land and stand up.
        after = [(f, knee_series.get(f)) for f in series.window(dip, release + 2) if knee_series.get(f) is not None]
        if after:
            peak_knee = max(after, key=lambda item: item[1])
    put("knee_extension_range_deg",
        (peak_knee[1] - knee_series[dip]) if peak_knee and dip is not None else None,
        peak_knee[0] if peak_knee else None,
        series.window(dip, peak_knee[0]) if peak_knee and dip is not None else [], leg_joints)

    # Arm -----------------------------------------------------------------------
    arm_joints = [arm["shoulder"], arm["elbow"], arm["wrist"]]
    loaded = [(f, elbow_series.get(f)) for f in series.window(dip if dip is not None else start, release)
              if elbow_series.get(f) is not None]
    loaded_min = min(loaded, key=lambda item: item[1]) if loaded else (set_frame, None)
    put("elbow_angle_set_deg", loaded_min[1], loaded_min[0],
        [loaded_min[0]] if loaded_min[0] is not None else [], arm_joints)
    put("elbow_angle_release_deg", elbow_series.get(release), release, series.window(release - 1, release + 1), arm_joints)
    world_angle = angle_3d(series.world_point(release, arm["shoulder"]), series.world_point(release, arm["elbow"]),
                           series.world_point(release, arm["wrist"]))
    put("elbow_angle_release_3d_deg", world_angle, release, [release], arm_joints,
        reason=None if series.world else "This session's pose data has no 3D estimates (analysed before 2026-10-25). Use 'Refresh pose data' to add them.")
    ext_window = series.window(release - 0.1 * fps, min(landing_cap, release + 0.5 * fps))
    ext = [(f, elbow_series.get(f) if f in elbow_series else elbow_angle(f)) for f in ext_window]
    ext = [item for item in ext if item[1] is not None]
    ext_peak = max(ext, key=lambda item: item[1]) if ext else (None, None)
    put("elbow_extension_peak_deg", ext_peak[1], ext_peak[0], ext_window, arm_joints)
    put("shoulder_elevation_release_deg",
        angle_2d(series.point(release, arm["hip"]), series.point(release, arm["shoulder"]), series.point(release, arm["elbow"])),
        release, [release], [arm["hip"], arm["shoulder"], arm["elbow"]])
    wrist, shoulder = series.point(release, arm["wrist"]), series.point(release, arm["shoulder"])
    height = ((shoulder[1] - wrist[1]) / torso) if wrist and shoulder and torso else None
    nose = series.point(release, NOSE)
    put("release_height_ratio", height, release, [release], [arm["wrist"], arm["shoulder"], L_HIP, R_HIP],
        detail=("wrist above head" if nose and wrist and wrist[1] < nose[1] else "wrist below head") if wrist and nose else None)

    # Torso -----------------------------------------------------------------------
    torso_joints = [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]

    def lean(f):
        return lean_from_vertical(midpoint(series.point(f, L_HIP), series.point(f, R_HIP)),
                                  midpoint(series.point(f, L_SHOULDER), series.point(f, R_SHOULDER)))

    lean_release = lean(release)
    detail = None
    if lean_release is not None:
        if camera_view in FRONTAL_LIKE:
            detail = "leaning to image " + ("right" if lean_release > 0 else "left")
        elif facing:
            detail = "leaning forward" if (lean_release > 0) == (facing > 0) else "leaning back"
    put("torso_lean_release_deg", abs(lean_release) if lean_release is not None else None, release,
        [release], torso_joints, detail=detail)
    lean_window = series.window(start, min(landing_cap, release + 0.3 * fps))
    leans = [lean(f) for f in lean_window]
    leans = [v for v in leans if v is not None]
    put("torso_lean_change_deg", (max(leans) - min(leans)) if len(leans) >= 3 else None, release,
        lean_window, torso_joints)

    # Balance and landing ------------------------------------------------------------
    landing_window = series.window(release + 0.4 * fps, min(landing_cap, release + 0.8 * fps))
    drift_dir = None
    if not torso:
        drift = None
    else:
        hip_at = lambda f: midpoint(series.point(f, L_HIP), series.point(f, R_HIP))
        dip_hip = hip_at(dip) if dip is not None else None
        landing_hips = [hip_at(f) for f in landing_window]
        landing_x = _median(p[0] for p in landing_hips if p)
        drift = abs(landing_x - dip_hip[0]) / torso if dip_hip and landing_x is not None else None
        if drift is not None and landing_x is not None:
            dx = landing_x - dip_hip[0]
            if camera_view in FRONTAL_LIKE:
                drift_dir = "sideways to image " + ("right" if dx > 0 else "left")
            elif facing:
                drift_dir = "forward" if (dx > 0) == (facing > 0) else "backward"
    put("hip_drift_ratio", drift, landing_window[-1] if len(landing_window) else None,
        list(landing_window) + ([dip] if dip is not None else []), [L_HIP, R_HIP],
        detail=drift_dir,
        reason=None if len(landing_window) else "The clip ends (or the next attempt starts) before the landing.")
    setup_window = series.window(start - 0.3 * fps, start)
    ankle_mid = lambda f: midpoint(series.point(f, L_ANKLE), series.point(f, R_ANKLE))
    setup_x = _median(p[0] for p in (ankle_mid(f) for f in setup_window) if p)
    landing_ankle_x = _median(p[0] for p in (ankle_mid(f) for f in landing_window) if p)
    offset = abs(landing_ankle_x - setup_x) / torso if torso and setup_x is not None and landing_ankle_x is not None else None
    put("landing_offset_ratio", offset, landing_window[-1] if len(landing_window) else None,
        list(setup_window) + list(landing_window), [L_ANKLE, R_ANKLE],
        reason=None if len(landing_window) else "The clip ends (or the next attempt starts) before the landing.")

    # Front-view alignment ----------------------------------------------------------
    widths, stances = [], []
    for f in setup_window:
        ls, rs = series.point(f, L_SHOULDER), series.point(f, R_SHOULDER)
        la, ra = series.point(f, L_ANKLE), series.point(f, R_ANKLE)
        if ls and rs and la and ra and torso and abs(ls[0] - rs[0]) >= 0.25 * torso:
            stances.append(abs(la[0] - ra[0]) / abs(ls[0] - rs[0]))
    put("stance_width_ratio", _median(stances), start, setup_window, [L_SHOULDER, R_SHOULDER, L_ANKLE, R_ANKLE])
    flare = None
    flare_frame = loaded_min[0]
    if flare_frame is not None:
        ls, rs = series.point(flare_frame, L_SHOULDER), series.point(flare_frame, R_SHOULDER)
        sh, el = series.point(flare_frame, arm["shoulder"]), series.point(flare_frame, arm["elbow"])
        if ls and rs and sh and el and torso and abs(ls[0] - rs[0]) >= 0.25 * torso:
            outward = 1 if sh[0] >= (ls[0] + rs[0]) / 2 else -1
            flare = outward * (el[0] - sh[0]) / abs(ls[0] - rs[0])
    put("elbow_flare_ratio", flare, flare_frame, [flare_frame] if flare_frame is not None else [],
        [L_SHOULDER, R_SHOULDER, arm["elbow"]])
    inward = None
    if dip is not None:
        lh, rh = series.point(dip, L_HIP), series.point(dip, R_HIP)
        if lh and rh and torso and abs(lh[0] - rh[0]) >= 0.15 * torso:
            mid_x = (lh[0] + rh[0]) / 2
            values = []
            for s in ("left", "right"):
                j = SIDE_JOINTS[s]
                hip, knee, ankle = series.point(dip, j["hip"]), series.point(dip, j["knee"]), series.point(dip, j["ankle"])
                if hip and knee and ankle and abs(ankle[1] - hip[1]) > 1:
                    t = (knee[1] - hip[1]) / (ankle[1] - hip[1])
                    line_x = hip[0] + t * (ankle[0] - hip[0])
                    toward_mid = 1 if mid_x > line_x else -1
                    values.append(toward_mid * (knee[0] - line_x) / abs(lh[0] - rh[0]))
            inward = max(values) if values else None
    put("knee_inward_ratio", inward, dip, [dip] if dip is not None else [],
        [L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE])

    # Timing --------------------------------------------------------------------------
    timing_frames = list(series.window(dip if dip is not None else start, release + 2))
    knee_vals = _smooth([knee_series.get(f) if f in knee_series else knee_angle(f) for f in timing_frames])
    elbow_vals = _smooth([elbow_series.get(f) if f in elbow_series else elbow_angle(f) for f in timing_frames])

    def peak_velocity(values):
        best = None
        for i in range(1, len(values)):
            if values[i] is None or values[i - 1] is None:
                continue
            velocity = values[i] - values[i - 1]
            if best is None or velocity > best[1]:
                best = (timing_frames[i], velocity)
        return best if best and best[1] > 0 else None

    knee_peak, elbow_peak = peak_velocity(knee_vals), peak_velocity(elbow_vals)
    lag = (elbow_peak[0] - knee_peak[0]) * 1000.0 / fps if knee_peak and elbow_peak else None
    put("sequencing_lag_ms", round(lag) if lag is not None else None, elbow_peak[0] if elbow_peak else None,
        timing_frames, leg_joints + arm_joints)
    put("release_vs_leg_extension_ms", round((release - peak_knee[0]) * 1000.0 / fps) if peak_knee else None,
        release, timing_frames, leg_joints)
    hold_frames = 0
    hold_window = series.window(release, min(landing_cap, release + 1.5 * fps))
    for f in hold_window:
        w, s = series.point(f, arm["wrist"]), series.point(f, arm["shoulder"])
        if not w or not s or w[1] >= s[1]:
            break
        hold_frames += 1
    put("follow_through_hold_ms", round(hold_frames * 1000.0 / fps) if hold_window else None,
        release + hold_frames if hold_window else None, list(hold_window)[: max(1, hold_frames)],
        [arm["wrist"], arm["shoulder"]])
    put("prep_duration_ms", round((release - start) * 1000.0 / fps), start, [start, release], [arm["wrist"]])

    return _attempt_record(series, shot, attempt_index, start, release, end, side, side_basis, dip, metrics,
                           leg_side=leg_side, torso_px=torso, facing=facing, release_source=release_source,
                           detector_release_frame=detector_release,
                           detector_release_s=series.time_s(detector_release))


def _attempt_record(series, shot, attempt_index, start, release, end, side, side_basis, dip, metrics, **extra):
    frames = series.window(start, end)
    with_pose = sum(1 for f in frames if series.frames[f] and any(series.frames[f])) if len(frames) else 0
    return {
        "analysis_version": ANALYSIS_VERSION,
        "shot_id": shot.get("shot_id"),
        "attempt_index": attempt_index,
        "start_frame": start, "release_frame": release, "end_frame": end, "dip_frame": dip,
        "start_s": series.time_s(start), "release_s": series.time_s(release), "end_s": series.time_s(end),
        "dip_s": series.time_s(dip),
        "shooting_side": side, "shooting_side_basis": side_basis,
        "review_status": shot.get("review_status") or "quarantined",
        "outcome": shot.get("outcome") or "unknown",
        "manually_added": shot.get("outcome_source") == "manual_attempt" or (
            shot.get("machine_start_frame") is None and shot.get("annotated_start_frame") is not None),
        "pose_coverage": round(with_pose / len(frames), 2) if len(frames) else 0.0,
        "metrics": metrics,
        **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in extra.items()},
    }


# --------------------------------------------------------------------------- session
def assess_video_quality(series: PoseSeries, camera_view: str, metadata: Optional[dict] = None) -> dict[str, Any]:
    """Recording-condition checks from the pose series; returns a grade and plain reasons."""
    n = series.n
    detected = sum(1 for points in series.frames if points and any(points))
    in_frame = 0
    key_vis = []
    ratios = []
    sizes = []
    for f in range(n):
        if not series.frames[f]:
            continue
        top = series.point(f, NOSE, 0.5) if series.has(NOSE) else midpoint(series.point(f, L_SHOULDER, 0.5), series.point(f, R_SHOULDER, 0.5))
        la, ra = series.point(f, L_ANKLE, 0.5), series.point(f, R_ANKLE, 0.5)
        if top and (la or ra):
            ys = [top[1]] + [p[1] for p in (la, ra) if p]
            if min(ys) > 0.01 * series.height and max(ys) < 0.99 * series.height:
                in_frame += 1
        key_vis.append(statistics.mean(series.visibility(f, j) for j in (L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW,
                                                                         L_WRIST, R_WRIST, L_HIP, R_HIP, L_KNEE, R_KNEE)))
        ls, rs = series.point(f, L_SHOULDER, 0.4), series.point(f, R_SHOULDER, 0.4)
        lh, rh = series.point(f, L_HIP, 0.4), series.point(f, R_HIP, 0.4)
        sm, hm = midpoint(ls, rs), midpoint(lh, rh)
        if sm and hm:
            torso = math.hypot(sm[0] - hm[0], sm[1] - hm[1])
            if torso > 1:
                ratios.append(abs(ls[0] - rs[0]) / torso)
                sizes.append(torso / series.height)
    pose_ratio = detected / n if n else 0.0
    body_ratio = in_frame / detected if detected else 0.0
    mean_vis = statistics.mean(key_vis) if key_vis else 0.0
    ratio = _median(ratios)
    subject = _median(sizes)
    estimated = None
    if ratio is not None:
        estimated = "side_90" if ratio < 0.35 else ("oblique_45" if ratio < 0.6 else "frontal")
        if estimated == "frontal" and series.has(NOSE):
            nose_vis = _median(series.visibility(f, NOSE) for f in range(n) if series.frames[f])
            if nose_vis is not None and nose_vis < 0.5:
                estimated = "rear"
    fps = (metadata or {}).get("fps") or series.fps
    issues, notes = [], []
    if pose_ratio < 0.6:
        issues.append(f"A body was found in only {pose_ratio:.0%} of frames.")
    if detected and body_ratio < 0.6:
        issues.append(f"{'Head' if series.has(NOSE) else 'Shoulders'} and feet were both clearly in frame in only {body_ratio:.0%} of pose frames; landing and stance measurements may be missing.")
    if mean_vis < 0.6:
        issues.append(f"Average visibility of the main joints was {mean_vis:.2f} (of 1.0); lighting, distance or occlusion may be limiting tracking.")
    if subject is not None and subject < 0.12:
        issues.append("You appear small in the frame; move the camera closer or zoom in so your body fills more of the height.")
    if fps and fps < 24:
        issues.append(f"Frame rate is {fps:.0f} fps; timing measurements are coarse below 24 fps.")
    view_match = None
    if estimated:
        pair = {estimated, camera_view}
        view_match = (estimated == camera_view
                      or pair == {"frontal", "rear"}
                      or (pair == {"side_90", "oblique_45"} and 0.28 <= ratio <= 0.42)
                      or (len(pair & FRONTAL_LIKE) == 1 and "oblique_45" in pair and 0.52 <= ratio <= 0.68))
        if not view_match:
            issues.append(f"You selected {VIEW_NAMES.get(camera_view, camera_view)}, but the footage looks closer to a {VIEW_NAMES[estimated]} "
                          f"(shoulder width is {ratio:.2f}× torso length). View-specific measurements may be misleading.")
    if series.lagged:
        notes.append("This session was analysed before 2026-10-25: its pose data is time-smoothed (it lags fast arm movement "
                     "by a few frames) and has no head, feet or 3D data. Use 'Refresh pose data' for full measurements.")
    if not issues:
        notes.append("Recording conditions look suitable for pose-based measurement.")
    grade = "good" if not issues else ("fair" if len(issues) == 1 and pose_ratio >= 0.6 else "poor")
    return {
        "grade": grade, "issues": issues, "notes": notes,
        "pose_detected_ratio": round(pose_ratio, 3), "full_body_ratio": round(body_ratio, 3),
        "mean_key_visibility": round(mean_vis, 3), "subject_height_ratio": round(subject, 3) if subject else None,
        "declared_view": camera_view, "estimated_view": estimated,
        "shoulder_to_torso_ratio": round(ratio, 3) if ratio is not None else None,
        "view_matches": view_match, "fps": fps, "frames": n,
        "width": int(series.width), "height": int(series.height),
        "has_world_coordinates": bool(series.world), "cache_format": series.format, "pose_lagged": series.lagged,
        "has_feet_and_head": series.has(NOSE) and series.has(L_HEEL),
    }


CONSISTENCY_SPREAD = {
    # (tight, loose) sample-standard-deviation bands used only to describe variability.
    "°": (5.0, 10.0),
    "torso lengths": (0.08, 0.2),
    "× shoulder width": (0.08, 0.2),
    "× hip width": (0.08, 0.2),
    "ms": (60.0, 150.0),
}
MIN_CONSISTENCY_ATTEMPTS = 3


def summarize_consistency(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean/SD/range per metric across non-discarded attempts with usable confidence."""
    summary = {}
    for key, definition in METRIC_DEFINITIONS.items():
        values = [(a["attempt_index"], a["metrics"][key]["value"]) for a in attempts
                  if a.get("review_status") != "discarded" and a["metrics"].get(key, {}).get("confidence") in USABLE]
        entry = {"key": key, "label": definition["label"], "unit": definition["unit"], "n": len(values),
                 "minimum_attempts": MIN_CONSISTENCY_ATTEMPTS, "attempts": [i for i, _ in values]}
        if len(values) >= MIN_CONSISTENCY_ATTEMPTS:
            numbers = [v for _, v in values]
            sd = statistics.stdev(numbers)
            tight, loose = CONSISTENCY_SPREAD.get(definition["unit"], (None, None))
            rating = None
            if tight is not None:
                rating = "consistent" if sd <= tight else ("variable" if sd >= loose else "moderate")
            entry.update({"mean": round(statistics.mean(numbers), 2), "sd": round(sd, 2),
                          "min": round(min(numbers), 2), "max": round(max(numbers), 2), "rating": rating,
                          "bands": {"tight": tight, "loose": loose}})
        summary[key] = entry
    return summary


def summarize_by_outcome(attempts: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Descriptive make vs miss means when the player has labelled at least two of each."""
    labelled = [a for a in attempts if a.get("review_status") == "approved" and a.get("outcome") in {"make", "miss"}]
    makes = [a for a in labelled if a["outcome"] == "make"]
    misses = [a for a in labelled if a["outcome"] == "miss"]
    if len(makes) < 2 or len(misses) < 2:
        return None
    result = {}
    for key, definition in METRIC_DEFINITIONS.items():
        mv = [a["metrics"][key]["value"] for a in makes if a["metrics"].get(key, {}).get("confidence") in USABLE]
        xv = [a["metrics"][key]["value"] for a in misses if a["metrics"].get(key, {}).get("confidence") in USABLE]
        if len(mv) >= 2 and len(xv) >= 2:
            result[key] = {"label": definition["label"], "unit": definition["unit"],
                           "make_mean": round(statistics.mean(mv), 2), "make_n": len(mv),
                           "miss_mean": round(statistics.mean(xv), 2), "miss_n": len(xv)}
    return {"makes": len(makes), "misses": len(misses), "metrics": result,
            "note": "Descriptive comparison of your labelled attempts; it does not show that a mechanic caused a make or miss."}


def analyze_session(cache: dict[str, Any], shots: list[dict[str, Any]], camera_view: str, *,
                    handedness: str = "unspecified", metadata: Optional[dict] = None) -> dict[str, Any]:
    """Measure every attempt in a session and summarise quality and consistency."""
    series = PoseSeries(cache)

    def start_of(shot):
        value = shot.get("annotated_start_frame")
        value = value if value is not None else shot.get("machine_start_frame")
        return value if value is not None else 0

    ordered = sorted(shots, key=start_of)
    quality = assess_video_quality(series, camera_view, metadata)
    estimated = quality.get("estimated_view") if quality.get("view_matches") is False else None
    attempts = []
    for index, shot in enumerate(ordered):
        next_start = start_of(ordered[index + 1]) if index + 1 < len(ordered) else None
        attempts.append(analyze_attempt(series, shot, camera_view, handedness=handedness,
                                        next_start=next_start, attempt_index=index + 1, estimated_view=estimated))
    return {
        "analysis_version": ANALYSIS_VERSION,
        "camera_view": camera_view,
        "effective_view_limit": estimated,
        "quality": quality,
        "attempts": attempts,
        "consistency": summarize_consistency(attempts),
        "by_outcome": summarize_by_outcome(attempts),
        "fps": series.fps,
        "duration_s": round(series.n / series.fps, 2) if series.fps else None,
    }
