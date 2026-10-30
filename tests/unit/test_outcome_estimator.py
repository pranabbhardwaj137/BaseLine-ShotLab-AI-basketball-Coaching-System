"""Unit tests for outcome_estimator.py.

Tests synthetic ballistic trajectories (geometry only), consensus_rim filters,
confidence bounds, and non-interference with human labels.
"""

import unittest
import numpy as np

from basketball.tracking.outcome_estimator import (
    BallPt,
    RimAnchor,
    Outcome,
    consensus_rim,
    estimate_outcome,
    get_cfg_hash,
    CFG,
    ESTIMATOR_VERSION,
)


class TestOutcomeEstimator(unittest.TestCase):
    def setUp(self):
        # Canonical court geometry for tests:
        # Rim center at (320, 200), width 60 px (diameter)
        self.rim = RimAnchor(cx=320.0, cy=200.0, w=60.0, stability=0.02)
        self.fps = 30.0

    def _generate_synthetic_trajectory(
        self,
        start_x=320.0,
        start_y=550.0,
        apex_x=320.0,
        apex_y=120.0,
        target_x=320.0,
        target_y=200.0,
        n_points=25,
        ball_w=24.0,
        post_rim_points=None,
    ):
        """Generate an exact parabolic arc in time passing through (0, start_y), (t_apex, apex_y), and (t_target, target_y)."""
        t_apex = 0.5
        a = (start_y - apex_y) / (t_apex ** 2)
        if target_y >= apex_y:
            t_target = t_apex + float(np.sqrt((target_y - apex_y) / a))
        else:
            t_target = 0.8
        vx = (target_x - start_x) / t_target

        ts = np.linspace(0.0, t_target, n_points)
        pts = []
        for t in ts:
            px = float(vx * t + start_x)
            py = float(a * ((t - t_apex) ** 2) + apex_y)
            pts.append(BallPt(t=float(t), x=px, y=py, w=ball_w, conf=0.90))

        if post_rim_points:
            for pt in post_rim_points:
                pts.append(pt)

        return pts

    def test_missing_rim_returns_rim_not_anchored(self):
        """Missing rim must immediately return unknown with RIM_NOT_ANCHORED reason."""
        pts = self._generate_synthetic_trajectory()
        res = estimate_outcome(pts, release_t=0.0, rim=None)
        self.assertEqual(res.label, "unknown")
        self.assertEqual(res.reason, "RIM_NOT_ANCHORED")
        self.assertIsNone(res.p_make)
        self.assertIsNone(res.confidence)
        self.assertEqual(res.evidence_quality, 0.0)

    def test_sparse_track_returns_track_too_sparse(self):
        """Track with fewer than 5 points returns unknown with TRACK_TOO_SPARSE."""
        pts = [
            BallPt(t=0.0, x=320.0, y=500.0, w=24.0, conf=0.9),
            BallPt(t=0.1, x=320.0, y=400.0, w=24.0, conf=0.9),
            BallPt(t=0.2, x=320.0, y=300.0, w=24.0, conf=0.9),
        ]
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "unknown")
        self.assertEqual(res.reason, "TRACK_TOO_SPARSE")

    def test_centered_shot_gives_make(self):
        """A shot dead center through the rim plane with below-rim descent produces make."""
        post = [
            BallPt(t=0.80, x=320.0, y=225.0, w=24.0, conf=0.88),
            BallPt(t=0.85, x=320.0, y=250.0, w=24.0, conf=0.85),
            BallPt(t=0.90, x=320.0, y=280.0, w=24.0, conf=0.82),
        ]
        pts = self._generate_synthetic_trajectory(
            start_x=320.0, start_y=550.0, apex_x=320.0, apex_y=120.0, target_x=320.0, target_y=200.0, post_rim_points=post
        )
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "make")
        self.assertIsNotNone(res.p_make)
        self.assertGreaterEqual(res.p_make, CFG["make_thr"])
        self.assertGreaterEqual(res.confidence, 0.50)
        self.assertLessEqual(res.confidence, CFG["conf_cap"])

    def test_shot_one_point_five_rim_widths_off_gives_miss(self):
        """A shot crossing the rim plane 1.5 rim widths wide (e.g. 90px off) produces miss."""
        post = [
            BallPt(t=0.80, x=415.0, y=225.0, w=24.0, conf=0.85),
            BallPt(t=0.85, x=425.0, y=260.0, w=24.0, conf=0.80),
        ]
        pts = self._generate_synthetic_trajectory(
            start_x=320.0, start_y=550.0, apex_x=370.0, apex_y=120.0, target_x=410.0, target_y=200.0, post_rim_points=post
        )
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "miss")
        self.assertIsNotNone(res.p_make)
        self.assertLessEqual(res.p_make, CFG["miss_thr"])

    def test_shot_near_rim_edge_gives_unknown(self):
        """A shot touching the edge of the rim aperture without net descent gives AMBIGUOUS_NEAR_RIM."""
        pts = self._generate_synthetic_trajectory(
            start_x=320.0, start_y=550.0, apex_x=330.0, apex_y=120.0, target_x=340.0, target_y=200.0
        )
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "unknown")
        self.assertEqual(res.reason, "AMBIGUOUS_NEAR_RIM")
        self.assertIsNotNone(res.p_make)
        self.assertGreater(res.p_make, CFG["miss_thr"])
        self.assertLess(res.p_make, CFG["make_thr"])

    def test_short_ball_never_reaching_rim_height_gives_miss(self):
        """Ball that peaks below rim height produces SHORT_OF_RIM_HEIGHT."""
        pts = self._generate_synthetic_trajectory(
            start_x=320.0, start_y=550.0, apex_x=320.0, apex_y=250.0, target_x=320.0, target_y=300.0
        )
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "miss")
        self.assertEqual(res.reason, "SHORT_OF_RIM_HEIGHT")
        self.assertIsNotNone(res.p_make)
        self.assertLessEqual(res.p_make, CFG["miss_thr"])

    def test_occlusion_gap_near_rim_still_fits(self):
        """Occlusion gap (missing 5 frames near apex/rim) still fits properly via RANSAC."""
        post = [
            BallPt(t=0.80, x=320.0, y=230.0, w=24.0, conf=0.88),
            BallPt(t=0.85, x=320.0, y=260.0, w=24.0, conf=0.85),
        ]
        all_pts = self._generate_synthetic_trajectory(
            start_x=320.0, start_y=550.0, apex_x=320.0, apex_y=120.0, target_x=320.0, target_y=200.0, n_points=30, post_rim_points=post
        )
        gapped_pts = [p for i, p in enumerate(all_pts) if i not in (12, 13, 14, 15, 16)]
        res = estimate_outcome(gapped_pts, release_t=0.0, rim=self.rim)
        self.assertEqual(res.label, "make")
        self.assertIsNotNone(res.p_make)

    def test_consensus_rim_filters_fake_sky_and_wide_boxes(self):
        """consensus_rim must ignore top-edge glued boxes and excessively wide sky boxes."""
        frame_w = 640
        frame_h = 480

        dets = [
            # 10 fake detections glued to top edge (cy - h/2 < 0.01 * frame_h)
            (320.0, 10.0, 200.0, 18.0, 0.85),
            (321.0, 9.0, 202.0, 17.0, 0.82),
            (319.0, 10.0, 198.0, 19.0, 0.80),
            (320.0, 10.0, 200.0, 18.0, 0.85),
            (321.0, 9.0, 202.0, 17.0, 0.82),
            (319.0, 10.0, 198.0, 19.0, 0.80),
            (320.0, 10.0, 200.0, 18.0, 0.85),
            (321.0, 9.0, 202.0, 17.0, 0.82),
            (319.0, 10.0, 198.0, 19.0, 0.80),
            (320.0, 10.0, 200.0, 18.0, 0.85),
            # 5 fake detections that are way too wide (> 0.25 * frame_w = 160px)
            (300.0, 150.0, 220.0, 90.0, 0.90),
            (302.0, 151.0, 218.0, 88.0, 0.92),
            (299.0, 149.0, 222.0, 91.0, 0.89),
            (300.0, 150.0, 220.0, 90.0, 0.90),
            (302.0, 151.0, 218.0, 88.0, 0.92),
            # 8 genuine, stable rim detections (w=50px, h=25px, ratio=2.0)
            (320.0, 180.0, 50.0, 25.0, 0.78),
            (320.5, 180.2, 50.2, 24.8, 0.80),
            (319.8, 179.9, 49.8, 25.1, 0.81),
            (320.2, 180.1, 50.0, 25.0, 0.79),
            (320.0, 180.0, 50.1, 24.9, 0.82),
            (320.3, 180.2, 49.9, 25.0, 0.77),
            (319.9, 179.8, 50.3, 25.2, 0.83),
            (320.1, 180.1, 50.0, 25.0, 0.80),
        ]

        anchor = consensus_rim(dets, frame_w, frame_h, min_conf=0.5, min_votes=5)
        self.assertIsNotNone(anchor)
        self.assertAlmostEqual(anchor.cx, 320.0, delta=2.0)
        self.assertAlmostEqual(anchor.cy, 180.0, delta=2.0)
        self.assertAlmostEqual(anchor.w, 50.0, delta=2.0)
        self.assertLess(anchor.stability, 0.15)

    def test_confidence_caps_and_evidence_quality_shrinking(self):
        """Confidence never exceeds conf_cap (0.90) and is close to 0.5 when quality is low."""
        post = [
            BallPt(t=0.80, x=320.0, y=225.0, w=24.0, conf=0.9),
            BallPt(t=0.85, x=320.0, y=250.0, w=24.0, conf=0.9),
        ]
        pts = self._generate_synthetic_trajectory(post_rim_points=post)
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)
        self.assertLessEqual(res.confidence, CFG["conf_cap"])

        wobbly_rim = RimAnchor(cx=320.0, cy=200.0, w=60.0, stability=0.14)
        res_wobbly = estimate_outcome(pts, release_t=0.0, rim=wobbly_rim)
        self.assertLessEqual(res_wobbly.evidence_quality, res.evidence_quality)
        self.assertLess(res_wobbly.confidence, res.confidence)

    def test_human_labels_never_modified_by_estimator(self):
        """Processing with estimate_outcome must never modify human ground truth label or review status."""
        shot_record = {
            "shot_id": "shot_test_123",
            "outcome": "miss",
            "outcome_source": "manual_review",
            "review_status": "approved",
            "automated_outcome": "unknown",
        }
        pts = self._generate_synthetic_trajectory()
        res = estimate_outcome(pts, release_t=0.0, rim=self.rim)

        # Apply machine outcome to a machine proposal payload
        machine_update = {
            "automated_outcome": res.label,
            "automated_outcome_conf": res.confidence,
            "p_make": res.p_make,
            "evidence_quality": res.evidence_quality,
            "outcome_reason": res.reason,
            "estimator_version": ESTIMATOR_VERSION,
            "estimator_cfg_hash": get_cfg_hash(),
        }

        # Check human label and source remain strictly unaffected
        self.assertEqual(shot_record["outcome"], "miss")
        self.assertEqual(shot_record["outcome_source"], "manual_review")
        self.assertEqual(shot_record["review_status"], "approved")
        self.assertEqual(machine_update["automated_outcome"], "make")
        self.assertNotEqual(shot_record["outcome"], machine_update["automated_outcome"])


if __name__ == "__main__":
    unittest.main()