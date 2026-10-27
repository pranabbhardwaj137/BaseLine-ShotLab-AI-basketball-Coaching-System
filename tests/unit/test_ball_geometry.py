import unittest
import numpy as np
from basketball.tracking.ball_geometry import (
    box_center,
    point_distance,
    box_to_point_distance,
    ball_under_rim,
    release_angle_deg,
    fit_parabola,
    sample_parabola,
    arc_peak,
    calculate_entry_angle,
    ParabolaFit,
)


class TestBallGeometry(unittest.TestCase):
    def test_box_center_and_distance(self):
        box = [100.0, 200.0, 140.0, 240.0]
        cx, cy = box_center(box)
        self.assertEqual(cx, 120.0)
        self.assertEqual(cy, 220.0)

        dist = point_distance((120.0, 220.0), (120.0, 250.0))
        self.assertEqual(dist, 30.0)

        b_dist = box_to_point_distance(box, (120.0, 260.0))
        self.assertEqual(b_dist, 40.0)

    def test_ball_under_rim(self):
        rim_box = [500.0, 300.0, 560.0, 320.0]  # center (530, 310)
        # Below rim center (y=350 > 310), horizontally aligned (x=535)
        ball_box = [520.0, 340.0, 550.0, 360.0]
        self.assertTrue(ball_under_rim(ball_box, rim_box, x_threshold=70))

        # Above rim (y=250 < 310)
        ball_above = [520.0, 240.0, 550.0, 260.0]
        self.assertFalse(ball_under_rim(ball_above, rim_box, x_threshold=70))

        # Far horizontally (x=700)
        ball_far = [690.0, 340.0, 710.0, 360.0]
        self.assertFalse(ball_under_rim(ball_far, rim_box, x_threshold=70))

    def test_release_angle_deg(self):
        # 45-degree angle in screen coords: dx = 10, dy = -10 (upward in image space)
        prev_box = [100.0, 200.0, 120.0, 220.0]  # center (110, 210)
        curr_box = [110.0, 190.0, 130.0, 210.0]  # center (120, 200)
        angle = release_angle_deg(curr_box, prev_box)
        self.assertEqual(angle, 45.0)

    def test_fit_parabola_and_sampling(self):
        # Generate known parabola y = 0.005 * x^2 - 2 * x + 500
        # in screen space: a > 0 is downward curve (apex is minimum y)
        xs = np.linspace(100, 300, 10)
        ys = 0.005 * (xs ** 2) - 2.0 * xs + 500.0
        pts = [(float(x), float(y)) for x, y in zip(xs, ys)]

        fit = fit_parabola(pts)
        self.assertIsNotNone(fit)
        self.assertIsInstance(fit, ParabolaFit)
        self.assertAlmostEqual(fit["a"], 0.005, places=4)
        self.assertAlmostEqual(fit["b"], -2.0, places=4)
        self.assertGreater(fit["r2"], 0.95)

        # Test dict and tuple backward compatibility
        self.assertAlmostEqual(fit[0], fit["a"])
        self.assertAlmostEqual(fit[3], fit["r2"])

        # Test apex
        apex = fit["apex"]
        self.assertAlmostEqual(apex[0], 200.0, delta=2.0)

        # Test sampling
        sampled = sample_parabola(fit, 100, 300, steps=20)
        self.assertEqual(len(sampled), 20)

    def test_insufficient_points_parabola(self):
        pts = [(10.0, 20.0), (20.0, 30.0), (30.0, 40.0)]
        self.assertIsNone(fit_parabola(pts))

    def test_calculate_entry_angle(self):
        # Parabola y = 0.005 * x^2 - 2.0 * x + 500
        # At rim x = 300: dy/dx = 2 * 0.005 * 300 - 2.0 = 3.0 - 2.0 = 1.0 => arctan(1.0) = 45 deg
        fit = {"a": 0.005, "b": -2.0, "c": 500.0, "r2": 0.99}
        rim_center = (300.0, 350.0)
        angle = calculate_entry_angle(fit, rim_center)
        self.assertAlmostEqual(angle, 45.0, places=1)


if __name__ == "__main__":
    unittest.main()
