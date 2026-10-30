"""
outcome_estimator.py

Make/miss estimation from a ball track and a rim anchor.

STATUS: prototype and advisory. Every weight and threshold below is a provisional
design choice, NOT a measured value. Do not present the output as a calibrated
probability until it has been fitted and checked on human-reviewed M/X/U labels
(see calibrate_from_reviews at the bottom). Never overwrite human labels with this.

Coordinates are image pixels, y grows downward.
Why this replaces y(x) parabola + "|dx| < 80px and below rim":
  1. Fit in TIME: x(t) linear, y(t) quadratic. A head-on (0 deg) camera sees almost
     no x change, so a y(x) fit is ill-conditioned there.
  2. Measure where the ball crosses the rim PLANE, scaled by the rim width.
  3. Use post-rim evidence (ball below the rim in the column vs bouncing back up).
  4. Report an evidence-quality-shrunk confidence, and "unknown" when evidence is weak.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ----------------------------------------------------------------------------
# Data types
# ----------------------------------------------------------------------------
@dataclass
class BallPt:
    t: float      # seconds (frame_idx / fps)
    x: float
    y: float
    w: float      # ball bbox width in px
    conf: float


@dataclass
class RimAnchor:
    cx: float
    cy: float
    w: float          # rim bbox width in px (~ rim diameter in the image)
    stability: float  # max std of rim centre across detections, divided by w

    @classmethod
    def from_user_click(cls, cx: float, cy: float, w: float) -> "RimAnchor":
        """One confirmed click per camera setup. Most reliable anchor."""
        return cls(cx, cy, w, 0.0)


@dataclass
class Fit:
    x_coef: np.ndarray  # np.polyfit order: [vx, x0]
    y_coef: np.ndarray  # [a, b, c], a > 0 (gravity, y down)
    n_inliers: int
    rmse: float
    t0: float           # absolute time of local t = 0


@dataclass
class Outcome:
    label: str                      # "make" | "miss" | "unknown"
    p_make: float | None            # uncalibrated score in [0, 1]
    confidence: float | None        # shrunk toward 0.5 by evidence quality
    evidence_quality: float         # 0..1
    reason: str
    features: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Provisional config (tunable, uncalibrated)
# ----------------------------------------------------------------------------
import hashlib
import json
import os

ESTIMATOR_VERSION = "1.0.0"
USE_LEGACY_OUTCOME = os.environ.get("BASKETBALL_USE_LEGACY_OUTCOME", "0") in ("1", "true", "True")

CFG = dict(
    weights=dict(bias=-0.2, margin=2.6, below=1.6, bounce=-2.4, sideways=-1.8),
    make_thr=0.65,        # p >= this and quality ok -> make
    miss_thr=0.35,        # p <= this and quality ok -> miss
    min_quality=0.40,     # below this -> unknown
    conf_cap=0.90,        # single camera sees one axis only, never claim more
    rim_stability_bad=0.25,
    ransac_iters=150,
    ransac_tol_ball_d=0.6,
)


def get_cfg_hash() -> str:
    """Return deterministic short hash of current CFG for audit and reproducibility."""
    cfg_str = json.dumps(CFG, sort_keys=True)
    return hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()[:12]


def _sigmoid(z: float) -> float:
    return float(1.0 / (1.0 + np.exp(-z)))


def _clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


# ----------------------------------------------------------------------------
# Rim anchor: consensus over the whole clip (the rim never moves on a tripod)
# ----------------------------------------------------------------------------
def consensus_rim(dets, frame_w, frame_h, min_conf=0.20, min_votes=3):
    """dets: iterable of (cx, cy, w, h, conf) for every frame of the clip.
    Returns RimAnchor or None. Ask the user to click the rim when this is None
    or stability is poor."""
    cand = []
    is_portrait = frame_w < frame_h
    max_w_ratio = 0.55 if is_portrait else 0.35
    for cx, cy, w, h, conf in dets:
        if conf < min_conf or h <= 0 or w <= 0:
            continue
        aspect = w / h
        if not (0.6 <= aspect <= 9.0):          # accommodate steep angles and elliptical rims
            continue
        if aspect > 4.5 and (cy - h / 2.0) < 0.01 * frame_h:  # reject thin strips glued to top edge
            continue
        if w > max_w_ratio * frame_w:           # sky or backboard sized boxes
            continue
        if cy < 0 or cy > frame_h:
            continue
        cand.append((cx, cy, w, h))
    if len(cand) < min_votes:
        if len(cand) >= 1:
            a = np.asarray(cand, float)
            cx, cy, w, _ = np.median(a, axis=0)
            return RimAnchor(float(cx), float(cy), float(w), 0.10)
        return None

    a = np.asarray(cand, float)
    r = 0.5 * float(np.median(a[:, 2]))
    d = np.linalg.norm(a[:, None, :2] - a[None, :, :2], axis=2)
    votes = (d < r).sum(axis=1)
    seed = int(np.argmax(votes))
    if votes[seed] < min_votes:
        cx, cy, w, _ = np.median(a, axis=0)
        return RimAnchor(float(cx), float(cy), float(w), 0.12)
    cluster = a[d[seed] < r]
    cx, cy, w, _ = np.median(cluster, axis=0)
    stability = float(np.std(cluster[:, :2], axis=0).max() / max(1.0, w))
    return RimAnchor(float(cx), float(cy), float(w), stability)


# ----------------------------------------------------------------------------
# Shot window: only release -> rim plane (+ short tail for post-rim evidence)
# ----------------------------------------------------------------------------
def shot_window(pts, release_t, rim, max_after=2.0):
    """Drops dribbles, floor bounces and rebounds that would poison the fit."""
    pts = sorted((p for p in pts if p.t >= release_t - 0.05), key=lambda p: p.t)
    out, min_y = [], float("inf")
    for p in pts:
        if p.t - release_t > max_after:
            break
        min_y = min(min_y, p.y)
        passed_apex = (p.y - min_y) > rim.w
        # release is usually BELOW the rim in the image, so only stop once the
        # ball is past its apex and falling well below the rim
        if passed_apex and p.y > rim.cy + 4.0 * rim.w:
            break
        out.append(p)
    return out


def split_fit_and_post(win, rim):
    """Fit uses points up to the first descent through the rim plane.
    Everything after is evidence (in the net column, or bouncing away)."""
    if len(win) < 4:
        return win, []
    apex = int(np.argmin([p.y for p in win]))
    if win[apex].y >= rim.cy:                  # never rose to rim height
        return win, []
    for i in range(apex, len(win)):
        if win[i].y >= rim.cy:
            return win[: i + 1], win[i + 1:]
    return win, []


# ----------------------------------------------------------------------------
# Ballistic fit in time (RANSAC to ignore YOLO outliers)
# ----------------------------------------------------------------------------
def fit_ballistic(pts, ball_d, iters=None, seed=0):
    iters = iters or CFG["ransac_iters"]
    if len(pts) < 5:
        return None
    rng = np.random.default_rng(seed)
    t0 = pts[0].t
    t = np.array([p.t - t0 for p in pts])
    x = np.array([p.x for p in pts])
    y = np.array([p.y for p in pts])
    tol = CFG["ransac_tol_ball_d"] * ball_d

    best_mask, best_n = None, 0
    for _ in range(iters):
        idx = rng.choice(len(pts), 4, replace=False)
        if np.ptp(t[idx]) < 1e-3:
            continue
        try:
            cx = np.polyfit(t[idx], x[idx], 1)
            cy = np.polyfit(t[idx], y[idx], 2)
        except np.linalg.LinAlgError:
            continue
        if cy[0] <= 0:                          # must accelerate downward
            continue
        res = np.hypot(np.polyval(cx, t) - x, np.polyval(cy, t) - y)
        mask = res < tol
        n = int(mask.sum())
        if n > best_n:
            best_mask, best_n = mask, n
    if best_mask is None or best_n < 5:
        return None

    cx = np.polyfit(t[best_mask], x[best_mask], 1)
    cy = np.polyfit(t[best_mask], y[best_mask], 2)
    if cy[0] <= 0:
        return None
    res = np.hypot(np.polyval(cx, t[best_mask]) - x[best_mask],
                   np.polyval(cy, t[best_mask]) - y[best_mask])
    return Fit(cx, cy, best_n, float(np.sqrt(np.mean(res ** 2))), t0)


def rim_crossing(fit, rim):
    """Local time when the descending ball passes rim height, or None if the
    fitted path never reaches rim height (short / air ball)."""
    a, b, c = fit.y_coef
    disc = b * b - 4 * a * (c - rim.cy)
    if disc < 0:
        return None
    return float((-b + np.sqrt(disc)) / (2 * a))   # larger root = descending


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def estimate_outcome(pts, release_t, rim: RimAnchor | None) -> Outcome:
    if rim is None:
        return Outcome("unknown", None, None, 0.0, "RIM_NOT_ANCHORED")
    if len(pts) < 5:
        return Outcome("unknown", None, None, 0.0, "TRACK_TOO_SPARSE")

    win = shot_window(pts, release_t, rim)
    fit_pts, post = split_fit_and_post(win, rim)
    if len(fit_pts) < 5:
        return Outcome("unknown", None, None, 0.0, "TRACK_TOO_SPARSE")

    ball_d = float(np.median([p.w for p in fit_pts]))
    fit = fit_ballistic(fit_pts, ball_d)
    if fit is None:
        return Outcome("unknown", None, None, 0.0, "NO_BALLISTIC_FIT")

    a, b, _ = fit.y_coef
    t_apex = -b / (2 * a)
    n_desc = sum(1 for p in fit_pts if (p.t - fit.t0) > t_apex)
    if n_desc < 2:
        return Outcome("unknown", None, None, 0.0, "NO_DESCENT_OBSERVED")

    ball_r, rim_r = ball_d / 2.0, rim.w / 2.0
    clearance = max(rim_r - ball_r, 0.25 * rim_r)    # clean-pass half width

    tc = rim_crossing(fit, rim)
    feats = dict(n_inliers=fit.n_inliers, rmse_px=round(fit.rmse, 2),
                 ball_d=round(ball_d, 1), rim_w=round(rim.w, 1),
                 rim_stability=round(rim.stability, 3), n_desc=n_desc)

    # --- evidence quality (weakest link, not an average) ---
    track_q = _clip01(fit.n_inliers / 8) * _clip01(1 - fit.rmse / ball_d)
    rim_q = _clip01(1 - rim.stability / CFG["rim_stability_bad"])
    n_near = sum(1 for p in fit_pts
                 if np.hypot(p.x - rim.cx, p.y - rim.cy) < 4 * rim.w)
    cover_q = 0.5 + 0.5 * _clip01(n_near / 3)
    quality = min(track_q, rim_q) * cover_q

    if tc is None:
        p_make, reason = 0.05, "SHORT_OF_RIM_HEIGHT"
        feats["margin"] = None
    else:
        x_cross = float(np.polyval(fit.x_coef, tc))
        dx = x_cross - rim.cx
        margin = float(np.clip(1.0 - abs(dx) / clearance, -1.5, 1.0))
        feats.update(x_cross_offset_px=round(dx, 1), margin=round(margin, 2))

        t_cross_abs = fit.t0 + tc
        in_col = [p for p in post
                  if p.y > rim.cy + 0.25 * rim.w and abs(p.x - rim.cx) <= rim_r]
        below = 1.0 if len(in_col) >= 1 else 0.0
        bounce = 1.0 if any(p.y < rim.cy - 0.5 * rim.w
                            and p.t > t_cross_abs - 0.05 for p in post) else 0.0
        sideways = 1.0 if any(p.y > rim.cy and abs(p.x - rim.cx) > 1.5 * rim.w
                              for p in post) else 0.0
        feats.update(below_in_column=below, bounce_back=bounce, exited_sideways=sideways)

        w = CFG["weights"]
        z = (w["bias"] + w["margin"] * margin + w["below"] * below
             + w["bounce"] * bounce + w["sideways"] * sideways)
        p_make = _sigmoid(z)
        reason = "TRAJECTORY_RIM_PLANE_CHECK"

    conf = 0.5 + (max(p_make, 1 - p_make) - 0.5) * quality
    conf = round(min(conf, CFG["conf_cap"]), 2)

    if quality < CFG["min_quality"]:
        label, reason = "unknown", "LOW_EVIDENCE_QUALITY"
    elif p_make >= CFG["make_thr"]:
        label = "make"
    elif p_make <= CFG["miss_thr"]:
        label = "miss"
    else:
        label, reason = "unknown", "AMBIGUOUS_NEAR_RIM"

    return Outcome(label, round(p_make, 3), conf, round(quality, 2), reason, feats)


# ----------------------------------------------------------------------------
# Calibration hook: use the human M/X/U labels from the Review screen
# ----------------------------------------------------------------------------
def calibrate_from_reviews(feature_rows, human_labels):
    """feature_rows: list of Outcome.features dicts. human_labels: 1 = make,
    0 = miss (skip U). Fit only when you have enough reviewed attempts from
    several sessions, then validate with session-grouped cross-validation and
    report Brier score / reliability. Returns a fitted sklearn model or None."""
    if len(human_labels) < 50 or len(set(human_labels)) < 2:
        return None
    from sklearn.linear_model import LogisticRegression
    keys = ["margin", "below_in_column", "bounce_back", "exited_sideways"]
    X = np.array([[row.get(k) or 0.0 for k in keys] for row in feature_rows])
    return LogisticRegression(C=1.0).fit(X, np.array(human_labels))
