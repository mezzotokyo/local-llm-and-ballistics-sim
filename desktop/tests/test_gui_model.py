"""Headless unit tests for the desktop app's pure logic."""

from __future__ import annotations

import math
import sys
import unittest
import warnings
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1]
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

import errors  # noqa: E402
import gui_model  # noqa: E402
from gui_model import LaunchConditions  # noqa: E402
from physics_config import DEFAULT_PARAMETERS  # noqa: E402


class PresetTests(unittest.TestCase):
    def test_presets_match_expected_values_and_labels(self) -> None:
        expected = ((0.47, "球体（既定値）"),)
        self.assertEqual(gui_model.DRAG_PRESETS, expected)

    def test_preset_label_known_and_unknown(self) -> None:
        self.assertEqual(gui_model.preset_label(0.47), "球体（既定値）（Cd=0.47）")
        self.assertEqual(gui_model.preset_label(0.5), "Cd=0.5")


class ValidateDtTests(unittest.TestCase):
    def test_accepts_default_and_bounds(self) -> None:
        self.assertIsNone(gui_model.validate_dt("0.01"))
        self.assertIsNone(gui_model.validate_dt("0.0001"))
        self.assertIsNone(gui_model.validate_dt("10"))

    def test_rejects_underflow(self) -> None:
        self.assertEqual(
            gui_model.validate_dt("0.00001"),
            "刻み幅 dt は 0.0001 以上で指定してください。",
        )

    def test_rejects_overflow(self) -> None:
        self.assertEqual(
            gui_model.validate_dt("11"),
            "刻み幅 dt は 10.0 以下で指定してください。",
        )

    def test_rejects_step_mismatch(self) -> None:
        self.assertEqual(
            gui_model.validate_dt("0.00015"),
            "刻み幅 dt は 0.0001 単位で指定してください。",
        )

    def test_rejects_non_numeric(self) -> None:
        message = "刻み幅 dt には数値を指定してください。"
        self.assertEqual(gui_model.validate_dt("abc"), message)
        self.assertEqual(gui_model.validate_dt(""), message)


class SimulateTests(unittest.TestCase):
    def test_reference_scenario_matches_spec(self) -> None:
        outcome = gui_model.simulate(LaunchConditions())
        result = outcome.result
        self.assertAlmostEqual(result.ideal_range, 213.60, delta=0.01)
        self.assertAlmostEqual(result.ground_range, 101.12, delta=0.01)
        self.assertAlmostEqual(result.flight_time, 4.37, delta=0.01)
        self.assertTrue(result.landed)
        self.assertFalse(result.timed_out)
        self.assertAlmostEqual(outcome.reduction_percent, 52.7, delta=0.1)

    def test_fixed_mode_timestep_is_constant(self) -> None:
        outcome = gui_model.simulate(LaunchConditions())
        self.assertAlmostEqual(outcome.result.timestep_min, 0.01)

    def test_adaptive_mode_shortens_timestep(self) -> None:
        outcome = gui_model.simulate(
            LaunchConditions(dt=5.0, adaptive=True)
        )
        self.assertTrue(outcome.result.landed)
        self.assertLess(outcome.result.timestep_min, 5.0)

    def test_drag_preset_changes_range(self) -> None:
        heavy = gui_model.simulate(LaunchConditions(drag_coefficient=0.47))
        light = gui_model.simulate(LaunchConditions(drag_coefficient=0.3))
        self.assertLess(heavy.result.ground_range, light.result.ground_range)

    def test_too_coarse_timestep_raises(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with self.assertRaises(gui_model.SimulationDiverged):
                gui_model.simulate(LaunchConditions(dt=100.0))


class SpinTests(unittest.TestCase):
    """The Magnus lift model bends the flat-surface trajectory."""

    def baseline(self):
        return gui_model.simulate(gui_model.make_conditions())

    def test_no_spin_leaves_the_range_unchanged(self) -> None:
        outcome = self.baseline()
        self.assertEqual(outcome.result.lateral_range, 0.0)
        self.assertTrue(all(point.z == 0.0 for point in outcome.trajectory))

    def test_backspin_lifts_the_projectile(self) -> None:
        without = self.baseline()
        with_spin = gui_model.simulate(gui_model.make_conditions(spin_rate=2500.0))
        self.assertGreater(with_spin.result.ground_range, without.result.ground_range)
        self.assertAlmostEqual(with_spin.result.lateral_range, 0.0, places=9)

    def test_spin_axis_angle_deflects_left_and_right(self) -> None:
        right = gui_model.simulate(
            gui_model.make_conditions(spin_rate=2500.0, spin_axis_deg=90.0)
        )
        left = gui_model.simulate(
            gui_model.make_conditions(spin_rate=2500.0, spin_axis_deg=-90.0)
        )
        self.assertGreater(right.result.lateral_range, 0.0)
        self.assertLess(left.result.lateral_range, 0.0)
        self.assertAlmostEqual(
            right.result.lateral_range, -left.result.lateral_range, places=6
        )

    def test_lateral_offset_matches_the_final_trajectory_point(self) -> None:
        outcome = gui_model.simulate(
            gui_model.make_conditions(spin_rate=2500.0, spin_axis_deg=90.0)
        )
        self.assertAlmostEqual(
            outcome.trajectory[-1].z, outcome.result.lateral_range, places=6
        )


class OrbitalTests(unittest.TestCase):
    """The newtonian gravity model integrates a central-gravity orbit."""

    RADIUS = 7.0e6

    def circular_conditions(self, **overrides) -> LaunchConditions:
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / self.RADIUS)
        defaults = dict(
            gravity_model="newtonian",
            dt=1.0,
            drag_coefficient=0.0,
            initial_state=(self.RADIUS, 0.0, 0.0, 0.0, speed, 0.0),
        )
        defaults.update(overrides)
        return LaunchConditions(**defaults)

    def test_circular_orbit_reports_elements(self) -> None:
        outcome = gui_model.simulate(self.circular_conditions())
        self.assertIsNotNone(outcome.orbital)
        self.assertIsNone(outcome.result.ideal_range)
        self.assertAlmostEqual(outcome.orbital.eccentricity, 0.0, places=6)
        self.assertAlmostEqual(outcome.orbital.periapsis, self.RADIUS, places=0)
        self.assertAlmostEqual(
            outcome.orbital.period,
            2.0 * math.pi * math.sqrt(self.RADIUS**3 / DEFAULT_PARAMETERS.mu),
            places=0,
        )
        self.assertEqual(outcome.reduction_percent, 0.0)

    def test_constant_model_reports_no_elements(self) -> None:
        outcome = gui_model.simulate(LaunchConditions())
        self.assertIsNone(outcome.orbital)
        self.assertNotEqual(outcome.result.ideal_range, None)

    def test_newtonian_requires_an_initial_state(self) -> None:
        with self.assertRaises(ValueError):
            gui_model.simulate(LaunchConditions(gravity_model="newtonian"))

    def test_unknown_gravity_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            gui_model.simulate(LaunchConditions(gravity_model="quantum"))

    def test_j2_perturbs_the_circular_orbit(self) -> None:
        outcome = gui_model.simulate(self.circular_conditions(gravity_model="j2"))
        self.assertIsNotNone(outcome.orbital)
        self.assertGreater(outcome.orbital.eccentricity, 1e-4)

    def test_zero_j2_matches_newtonian(self) -> None:
        baseline = gui_model.simulate(self.circular_conditions()).orbital
        flat = gui_model.simulate(
            self.circular_conditions(gravity_model="j2", j2=0.0)
        ).orbital
        self.assertIsNotNone(baseline)
        self.assertEqual(flat, baseline)

    def test_unknown_drag_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            gui_model.simulate(
                LaunchConditions(drag_model="magnus")
            )

    def test_constant_drag_model_matches_the_default(self) -> None:
        baseline = gui_model.simulate(LaunchConditions())
        explicit = gui_model.simulate(LaunchConditions(drag_model="constant"))
        self.assertEqual(baseline.result, explicit.result)

    def test_tabulated_drag_changes_a_low_orbit(self) -> None:
        radius = DEFAULT_PARAMETERS.equatorial_radius + 200000.0
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / radius)
        conditions = self.circular_conditions(
            dt=5.0,
            drag_coefficient=0.47,
            drag_model="tabulated",
            initial_state=(radius, 0.0, 0.0, 0.0, speed, 0.0),
        )
        outcome = gui_model.simulate(conditions)
        self.assertIsNotNone(outcome.orbital)

    def test_closed_orbit_integrates_a_full_period(self) -> None:
        outcome = gui_model.simulate(self.circular_conditions())
        period = 2.0 * math.pi * math.sqrt(self.RADIUS**3 / DEFAULT_PARAMETERS.mu)
        self.assertAlmostEqual(
            outcome.result.flight_time,
            period * gui_model.ORBITAL_PERIOD_MARGIN,
            delta=outcome.result.timestep_max or 1.0,
        )
        start = outcome.trajectory[0]
        closest = min(
            math.hypot(p.x - start.x, p.y - start.y) for p in outcome.trajectory
        )
        self.assertLess(closest, self.RADIUS * 1e-3)

    def test_orbital_timestep_is_bounded_by_max_steps(self) -> None:
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / self.RADIUS)
        state = (self.RADIUS, 0.0, 0.0, 0.0, speed, 0.0)
        span = gui_model.orbital_time_span(state)
        self.assertIsNotNone(span)
        fine = gui_model.orbital_timestep(state, 0.01)
        self.assertAlmostEqual(fine, span / gui_model.MAX_ORBITAL_STEPS, places=9)
        coarse = gui_model.orbital_timestep(state, 5.0)
        self.assertEqual(coarse, 5.0)

    def test_open_orbit_keeps_the_requested_timestep(self) -> None:
        escape = math.sqrt(2.0 * DEFAULT_PARAMETERS.mu / self.RADIUS)
        state = (self.RADIUS, 0.0, 0.0, 0.0, escape * 1.2, 0.0)
        self.assertIsNone(gui_model.orbital_time_span(state))
        self.assertEqual(gui_model.orbital_timestep(state, 0.5), 0.5)


class UiHelperTests(unittest.TestCase):
    """The label/format/toggle helpers the GUI widgets call directly."""

    def test_gravity_and_density_labels(self) -> None:
        self.assertEqual(gui_model.gravity_label("j2"), "ニュートン+J2（軌道）")
        self.assertEqual(gui_model.density_label("none"), "なし")
        self.assertEqual(gui_model.gravity_label("mystery"), "mystery")
        self.assertEqual(gui_model.density_label("mystery"), "mystery")

    def test_orbital_speed_is_the_circular_speed(self) -> None:
        radius = 7.0e6
        self.assertAlmostEqual(
            gui_model.orbital_speed(radius),
            math.sqrt(DEFAULT_PARAMETERS.mu / radius),
            places=9,
        )
        with self.assertRaises(ValueError):
            gui_model.orbital_speed(0.0)

    def test_format_optional_renders_none_as_dash(self) -> None:
        self.assertEqual(gui_model.format_optional(None), "-")
        self.assertEqual(gui_model.format_optional(1234.567), "1234.57")

    def test_make_conditions_ballistic_defaults(self) -> None:
        conditions = gui_model.make_conditions()
        self.assertEqual(conditions.gravity_model, "constant")
        self.assertEqual(conditions.drag_model, "constant")
        self.assertEqual(conditions.drag_coefficient, gui_model.DRAG_COEFFICIENT_DEFAULT)
        self.assertIsNone(conditions.initial_state)

    def test_make_conditions_none_density_disables_drag(self) -> None:
        conditions = gui_model.make_conditions(density_model="none")
        self.assertEqual(conditions.drag_model, "constant")
        self.assertEqual(conditions.drag_coefficient, 0.0)

    def test_make_conditions_exponential_density_keeps_the_coefficient(self) -> None:
        conditions = gui_model.make_conditions(
            density_model="exponential", drag_coefficient=0.3
        )
        self.assertEqual(conditions.drag_model, "exponential")
        self.assertEqual(conditions.drag_coefficient, 0.3)

    def test_make_conditions_orbital_builds_a_circular_state(self) -> None:
        conditions = gui_model.make_conditions(gravity_model="j2", radius=7.0e6)
        self.assertEqual(conditions.gravity_model, "j2")
        self.assertIsNotNone(conditions.initial_state)
        state = conditions.initial_state
        self.assertEqual(state[0], 7.0e6)
        self.assertAlmostEqual(state[4], gui_model.orbital_speed(7.0e6), places=9)

    def test_make_conditions_rejects_unknown_selectors(self) -> None:
        with self.assertRaises(ValueError):
            gui_model.make_conditions(gravity_model="quantum")
        with self.assertRaises(ValueError):
            gui_model.make_conditions(density_model="magnus")

    def test_default_metric_rows_match_ballistic_columns(self) -> None:
        outcome = gui_model.simulate(gui_model.make_conditions())
        rows = gui_model.result_metrics(outcome)
        defaults = gui_model.DEFAULT_METRIC_ROWS
        self.assertEqual([key for key, _l, _v in rows], [key for key, _l, _v in defaults])
        self.assertEqual([label for _k, label, _v in rows], [label for _k, label, _v in defaults])

    def test_default_orbital_metric_rows_match_columns(self) -> None:
        outcome = gui_model.simulate(
            gui_model.make_conditions(
                gravity_model="newtonian",
                radius=7.0e6,
                dt=1.0,
                density_model="none",
            )
        )
        rows = gui_model.result_metrics(outcome)
        defaults = gui_model.DEFAULT_ORBITAL_METRIC_ROWS
        self.assertEqual([key for key, _l, _v in rows], [key for key, _l, _v in defaults])
        self.assertEqual([label for _k, label, _v in rows], [label for _k, label, _v in defaults])

    def test_result_metrics_ballistic_columns(self) -> None:
        outcome = gui_model.simulate(gui_model.make_conditions())
        keys = [key for key, _label, _value in gui_model.result_metrics(outcome)]
        self.assertEqual(
            keys,
            [
                "ideal_range",
                "ground_range",
                "reduction",
                "lateral_range",
                "flight_time",
                "impact_speed",
                "steps",
                "timestep",
                "landed",
            ],
        )

    def test_result_metrics_orbital_columns(self) -> None:
        outcome = gui_model.simulate(
            gui_model.make_conditions(
                gravity_model="newtonian",
                radius=7.0e6,
                dt=1.0,
                density_model="none",
            )
        )
        rows = gui_model.result_metrics(outcome)
        keys = [key for key, _label, _value in rows]
        self.assertEqual(
            keys,
            [
                "semi_major_axis",
                "eccentricity",
                "periapsis",
                "apoapsis",
                "period",
                "inclination",
                "flight_time",
                "steps",
                "timestep",
            ],
        )
        self.assertNotIn("ideal_range", keys)


class FormattingTests(unittest.TestCase):
    def test_format_number(self) -> None:
        self.assertEqual(gui_model.format_number(101.1234), "101.12")
        self.assertEqual(gui_model.format_number(4.371, 1), "4.4")

    def test_format_decimal_trims_trailing_zeros(self) -> None:
        self.assertEqual(gui_model.format_decimal(0.01), "0.01")
        self.assertEqual(gui_model.format_decimal(0.0001), "0.0001")


class DownsampleTests(unittest.TestCase):
    def test_short_trajectory_is_unchanged(self) -> None:
        points = [gui_model.TrajectoryPoint(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
        self.assertEqual(gui_model._downsample(points, 2000), points)

    def test_long_trajectory_keeps_last_point(self) -> None:
        points = [
            gui_model.TrajectoryPoint(float(i), float(i), 0.0, 0.0, 0.0, 0.0)
            for i in range(5000)
        ]
        sampled = gui_model._downsample(points, 2000)
        self.assertLessEqual(len(sampled), 2000 + 1)
        self.assertIs(sampled[-1], points[-1])


class ErrorLocalizationTests(unittest.TestCase):
    def test_too_coarse_message_is_translated(self) -> None:
        raw = (
            "timestep dt=100 is too coarse: an upward launch reached the ground "
            "within the first step. Reduce dt below 1.24049."
        )
        translated = errors.localize_error(raw)
        self.assertIn("dt=100", translated)
        self.assertIn("1.24049", translated)
        self.assertIn("粗すぎます", translated)

    def test_unknown_message_passes_through(self) -> None:
        self.assertEqual(errors.localize_error("boom"), "boom")


if __name__ == "__main__":
    unittest.main()
