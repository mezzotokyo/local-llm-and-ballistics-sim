"""Tests for the chart's pure scaling helpers.

Only the arithmetic (:func:`axis_ticks` / :func:`chart_domain`) is tested; the
drawing itself is exercised by running the app. Importing the module pulls in
Tkinter, which is a documented dependency of ``desktop``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1]
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

import gui_model  # noqa: E402
import trajectory_chart  # noqa: E402


def point(x: float, y: float) -> gui_model.TrajectoryPoint:
    return gui_model.TrajectoryPoint(t=0.0, x=x, y=y, vx=0.0, vy=0.0, speed=0.0)


class AxisTicksTests(unittest.TestCase):
    def test_non_negative_domain_starts_at_zero(self) -> None:
        values = trajectory_chart.axis_ticks(0.0, 100.0, 5)
        self.assertEqual(values[0], 0.0)
        self.assertGreaterEqual(values[-1], 100.0)

    def test_negative_domain_includes_zero_and_covers_range(self) -> None:
        values = trajectory_chart.axis_ticks(-95.0, 95.0, 5)
        self.assertIn(0.0, values)
        self.assertLessEqual(values[0], -95.0 + 1e-6)
        self.assertGreaterEqual(values[-1], 95.0 - 1e-6)
        self.assertEqual(values, sorted(values))

    def test_degenerate_domain(self) -> None:
        self.assertEqual(trajectory_chart.axis_ticks(0.0, 0.0, 5), [0.0])


class ChartDomainTests(unittest.TestCase):
    def test_flat_surface_reproduces_legacy_scaling(self) -> None:
        points = [point(0.0, 0.0), point(100.0, 10.0)]
        x_lo, x_hi, y_lo, y_hi = trajectory_chart.chart_domain(
            points, 213.60, 101.12, central_body=False
        )
        self.assertEqual(x_lo, 0.0)
        self.assertEqual(y_lo, 0.0)
        self.assertAlmostEqual(x_hi, 213.60 * 1.05, places=6)
        self.assertAlmostEqual(y_hi, 10.0 * 1.15, places=6)

    def test_flat_surface_ignores_a_missing_ideal_range(self) -> None:
        points = [point(0.0, 0.0), point(50.0, 5.0)]
        _x_lo, x_hi, _y_lo, _y_hi = trajectory_chart.chart_domain(
            points, None, None, central_body=False
        )
        self.assertAlmostEqual(x_hi, 50.0 * 1.05, places=6)

    def test_central_body_includes_origin_and_goes_negative(self) -> None:
        points = [point(7.0e6, 0.0), point(0.0, 7.0e6), point(-7.0e6, 0.0)]
        x_lo, x_hi, y_lo, y_hi = trajectory_chart.chart_domain(
            points, None, None, central_body=True
        )
        self.assertLess(x_lo, -7.0e6)
        self.assertGreater(x_hi, 7.0e6)
        self.assertLessEqual(y_lo, 0.0)
        self.assertGreater(y_hi, 7.0e6)

    def test_empty_trajectory_still_yields_a_positive_domain(self) -> None:
        for central_body in (False, True):
            with self.subTest(central_body=central_body):
                x_lo, x_hi, y_lo, y_hi = trajectory_chart.chart_domain(
                    [], None, None, central_body=central_body
                )
                self.assertGreater(x_hi, x_lo)
                self.assertGreater(y_hi, y_lo)

    def test_top_down_view_scales_the_lateral_offset(self) -> None:
        points = [
            gui_model.TrajectoryPoint(
                t=0.0, x=0.0, y=0.0, vx=0.0, vy=0.0, speed=0.0, z=0.0
            ),
            gui_model.TrajectoryPoint(
                t=1.0, x=100.0, y=30.0, vx=0.0, vy=0.0, speed=0.0, z=20.0
            ),
        ]
        side = trajectory_chart.chart_domain(
            points, None, None, central_body=False, view=trajectory_chart.VIEW_XY
        )
        top = trajectory_chart.chart_domain(
            points, None, None, central_body=False, view=trajectory_chart.VIEW_XZ
        )
        self.assertAlmostEqual(side[3], 30.0 * 1.15, places=6)
        self.assertAlmostEqual(top[3], 20.0 * 1.15, places=6)

    def test_unknown_view_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            trajectory_chart.chart_domain([], None, None, central_body=False, view="qq")


if __name__ == "__main__":
    unittest.main()
