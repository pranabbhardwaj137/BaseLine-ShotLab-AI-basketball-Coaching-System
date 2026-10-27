"""Ball and rim trajectory geometry primitives.

Supports spatial parabolic fitting y(x) = ax^2 + bx + c and parametric time-based
trajectory fitting y(t) = at^2 + bt + c for basketball shots.
Handles frame-gap spacing gracefully when detect_every > 1.
"""

from __future__ import annotations
import math
from typing import Optional, List, Tuple, Dict, Any, Union
import numpy as np


class ParabolaFit(dict):
    """
    Dictionary representing fitted parabola (a, b, c, r2, apex) that also
    supports legacy 4-tuple indexing (a, b, c, r2).
    """
    def __init__(self, a: float, b: float, c: float, r2: float, apex: Tuple[float, float]):
        super().__init__(a=a, b=b, c=c, r2=r2, apex=apex)
        self._tuple = (a, b, c, r2)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._tuple[key]
        return super().__getitem__(key)

    def __len__(self) -> int:
        return 4

    def __iter__(self):
        return iter(self._tuple)


def box_center(box: Optional[List[float]]) -> Optional[Tuple[float, float]]:
    """Return (cx, cy) for an xyxy bounding box [x1, y1, x2, y2]."""
    if box is None or len(box) < 4:
        return None
    return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)


def point_distance(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> Optional[float]:
    """Euclidean distance between two 2D points (x, y)."""
    if a is None or b is None:
        return None
    return float(math.hypot(b[0] - a[0], b[1] - a[1]))


def box_to_point_distance(box: Optional[List[float]], point: Optional[Tuple[float, float]]) -> Optional[float]:
    """Distance from bounding box center to a pixel coordinate (x, y)."""
    center = box_center(box)
    if center is None or point is None:
        return None
    return point_distance(center, point)


def last_valid_box(boxes: List[Optional[List[float]]]) -> Optional[List[float]]:
    """Most recent non-None box prior to the latest slot."""
    if not boxes or len(boxes) < 2:
        return None
    for i in range(len(boxes) - 2, -1, -1):
        if boxes[i] is not None:
            return boxes[i]
    return None


def ball_under_rim(
    ball_box_or_pt: Union[List[float], Tuple[float, float]],
    rim_box_or_pt: Union[List[float], Tuple[float, float]],
    x_threshold: float = 70.0
) -> bool:
    """
    True if ball center is vertically below rim center and horizontally aligned within x_threshold.
    Heuristic for ball passing through or under the hoop aperture.
    """
    ball = box_center(ball_box_or_pt) if isinstance(ball_box_or_pt, (list, np.ndarray)) and len(ball_box_or_pt) == 4 else ball_box_or_pt
    rim = box_center(rim_box_or_pt) if isinstance(rim_box_or_pt, (list, np.ndarray)) and len(rim_box_or_pt) == 4 else rim_box_or_pt

    if ball is None or rim is None:
        return False
    horiz_aligned = abs(ball[0] - rim[0]) < x_threshold
    vert_below = (ball[1] - rim[1]) > 0
    return horiz_aligned and vert_below


def release_angle_deg(
    current_box_or_pt: Union[List[float], Tuple[float, float]],
    previous_box_or_pt: Union[List[float], Tuple[float, float]],
    dt: Optional[float] = None
) -> Optional[float]:
    """
    Compute launch angle (in degrees) vs horizontal using two ball bounding boxes or centers.
    Image y grows downward, so dy is inverted (prev_y - now_y) to measure elevation above horizontal.
    Returns angle in [0°, 90°], or None if points are collinear or invalid.
    """
    now = box_center(current_box_or_pt) if isinstance(current_box_or_pt, (list, np.ndarray)) and len(current_box_or_pt) == 4 else current_box_or_pt
    prev = box_center(previous_box_or_pt) if isinstance(previous_box_or_pt, (list, np.ndarray)) and len(previous_box_or_pt) == 4 else previous_box_or_pt

    if now is None or prev is None:
        return None

    dx = now[0] - prev[0]
    dy = prev[1] - now[1]  # Invert image y so up is positive

    if abs(dx) < 1e-5 and abs(dy) < 1e-5:
        return None

    angle = abs(float(np.degrees(np.arctan2(dy, dx))))
    if angle > 90.0:
        angle = abs(180.0 - angle)
    if angle > 90.0:
        angle = abs(90.0 - angle)

    return round(angle, 1)


def fit_parabola(centers: List[Optional[Tuple[float, float]]], timestamps: Optional[List[float]] = None) -> Optional[ParabolaFit]:
    """
    Fit parabolic flight path y = ax^2 + bx + c to recorded ball centers.
    Handles frame skips (non-uniform time spacing) and checks goodness-of-fit (R^2).
    Returns ParabolaFit object (supporting dict and tuple indexing) or None if points are insufficient.
    """
    pts = [c for c in centers if c is not None]
    if len(pts) < 4:
        return None

    xs = np.array([float(p[0]) for p in pts], dtype=float)
    ys = np.array([float(p[1]) for p in pts], dtype=float)

    # Check horizontal span to prevent ill-conditioned polyfit on vertical drop
    x_range = float(np.ptp(xs))
    if x_range < 15.0:
        # Near-vertical shot: fit y as function of frame index / time instead
        t = np.arange(len(ys), dtype=float)
        try:
            coeffs_t = np.polyfit(t, ys, 2)
            apex_idx = int(np.clip(-coeffs_t[1] / (2.0 * coeffs_t[0] + 1e-6), 0, len(pts) - 1))
            apex = (float(xs[apex_idx]), float(np.min(ys)))
            return ParabolaFit(0.0, 0.0, float(np.mean(ys)), 0.50, apex)
        except (np.linalg.LinAlgError, ValueError):
            return None

    try:
        coeffs, residuals, _, _, _ = np.polyfit(xs, ys, 2, full=True)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

        # Compute R^2 goodness of fit
        y_mean = float(np.mean(ys))
        ss_tot = float(np.sum((ys - y_mean) ** 2))
        if ss_tot > 1e-6 and len(residuals) > 0:
            r2 = max(0.0, min(1.0, 1.0 - (float(residuals[0]) / ss_tot)))
        else:
            r2 = 0.85

        # Apex of parabola (derivative dy/dx = 2ax + b = 0 => x_apex = -b / (2a))
        if abs(a) > 1e-6:
            apex_x = -b / (2.0 * a)
            apex_y = a * (apex_x ** 2) + b * apex_x + c
        else:
            min_pt = min(pts, key=lambda p: p[1])
            apex_x, apex_y = float(min_pt[0]), float(min_pt[1])

        return ParabolaFit(a, b, c, round(r2, 2), (float(apex_x), float(apex_y)))
    except (np.linalg.LinAlgError, ValueError):
        return None


def sample_parabola(
    coeffs_or_fit: Union[ParabolaFit, Tuple[float, float, float], List[float]],
    x_start: float,
    x_end: float,
    steps: int = 60
) -> List[Tuple[float, float]]:
    """Generate (x, y) coordinates along fitted parabola between x_start and x_end."""
    if coeffs_or_fit is None:
        return []
    if isinstance(coeffs_or_fit, (dict, ParabolaFit)):
        a, b, c = coeffs_or_fit["a"], coeffs_or_fit["b"], coeffs_or_fit["c"]
    elif len(coeffs_or_fit) >= 3:
        a, b, c = coeffs_or_fit[0], coeffs_or_fit[1], coeffs_or_fit[2]
    else:
        return []

    if abs(a) < 1e-7 and abs(b) < 1e-7:
        return []
    xs = np.linspace(x_start, x_end, steps)
    return [(float(x), float(a * x * x + b * x + c)) for x in xs]


def arc_peak(centers: List[Optional[Tuple[float, float]]]) -> Optional[Tuple[float, float]]:
    """
    Find highest point on ball flight path (smallest image y coordinate).
    Returns (peak_x, peak_y) or None.
    """
    pts = [c for c in centers if c is not None]
    if not pts:
        return None
    min_pt = min(pts, key=lambda p: p[1])
    return (float(min_pt[0]), float(min_pt[1]))


def calculate_entry_angle(
    coeffs_or_fit: Union[ParabolaFit, Tuple[float, float, float], List[float], Dict[str, Any]],
    rim_box_or_pt: Union[List[float], Tuple[float, float]]
) -> Optional[float]:
    """
    Calculate descent angle (degrees vs horizontal) as ball approaches rim level.
    Optimal basketball entry angle is >= 45° for maximum effective target aperture.
    """
    if coeffs_or_fit is None or rim_box_or_pt is None:
        return None

    if isinstance(coeffs_or_fit, dict):
        a, b = coeffs_or_fit.get("a", 0.0), coeffs_or_fit.get("b", 0.0)
    elif len(coeffs_or_fit) >= 2:
        a, b = coeffs_or_fit[0], coeffs_or_fit[1]
    else:
        return None

    rim_center = box_center(rim_box_or_pt) if isinstance(rim_box_or_pt, (list, np.ndarray)) and len(rim_box_or_pt) == 4 else rim_box_or_pt
    if rim_center is None:
        return None

    rim_x = float(rim_center[0])
    # Derivative dy/dx = 2ax + b
    slope = 2.0 * a * rim_x + b
    # Invert slope because image y increases downward
    entry_angle = float(np.degrees(np.arctan(abs(slope))))
    return round(entry_angle, 1)
