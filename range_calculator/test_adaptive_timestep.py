"""Tests for the adaptive timestep mode added in V5.

The mode keeps ``dt`` as an upper bound and shortens each step to stay inside
the explicit-RK4 stability band. These tests pin three things: the step never
exceeds the ceiling, scenarios that used to raise now complete, and the mode
makes no accuracy promise it cannot keep.
"""

import contextlib
import io
import math
import unittest
import warnings

import range_calc as range_calc
from ballistics import ProjectileSimulator, SimulationDiverged

GRAVITY = 9.81

V0_KMPH = 170.0
V0_MPS = V0_KMPH * (1000 / 3600)
ANGLE_DEG = 35.0
ANGLE_RAD = math.radians(ANGLE_DEG)

# Measured range at the baseline scenario, i.e. the dt -> 0 limit for the drag
# model in config/physics_constants.json.
REFERENCE_RANGE = 101.1215
REFERENCE_FLIGHT_TIME = 4.3739


def simulate(adaptive=True, v0_mps=V0_MPS, angle_rad=ANGLE_RAD, dt=0.01, **kwargs):
    simulator = ProjectileSimulator(
        v0_mps, angle_rad, dt=dt, adaptive=adaptive, **kwargs
    )
    simulator.run_simulation()
    return simulator


@contextlib.contextmanager
def allow_runtime_warnings():
    """Lets the fixed-timestep mode emit its accuracy warning.

    Adaptive runs are asserted to be warning-free, but the fixed-mode baselines
    they are compared against warn by design.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        yield


class TimestepCeilingTests(unittest.TestCase):
    """The adaptive step may shrink the timestep but must never lengthen it."""

    def test_step_never_exceeds_the_ceiling(self):
        for dt_max in (0.01, 0.5, 5.0, 1000.0):
            with self.subTest(dt_max=dt_max):
                result = simulate(dt=dt_max).result()
                self.assertLessEqual(result.timestep_max, dt_max)

    def test_stable_scenarios_leave_the_timestep_untouched(self):
        """Below the stability band nothing shrinks, so the run matches fixed dt."""
        result = simulate(dt=0.01).result()
        self.assertAlmostEqual(result.timestep_min, 0.01, delta=1e-12)
        self.assertAlmostEqual(result.timestep_max, 0.01, delta=1e-12)

    def test_coarse_ceiling_forces_a_shorter_step(self):
        baseline = simulate()
        stable_dt = ProjectileSimulator._stable_timestep(baseline.k, V0_MPS)
        dt_max = stable_dt * 10
        result = simulate(dt=dt_max).result()
        self.assertLess(result.timestep_max, dt_max)
        self.assertLessEqual(result.timestep_min, stable_dt)

    def test_step_is_deterministic(self):
        self.assertEqual(simulate(dt=5.0).run_simulation(), simulate(dt=5.0).run_simulation())


class AgreementWithFixedTimestepTests(unittest.TestCase):
    """Where the fixed mode is already stable, the two modes must agree exactly."""

    def test_matches_fixed_mode_below_the_stability_band(self):
        for dt in (0.01, 0.05, 0.2):
            with self.subTest(dt=dt):
                fixed = simulate(adaptive=False, dt=dt).run_simulation()
                adaptive = simulate(adaptive=True, dt=dt).run_simulation()
                self.assertEqual(fixed, adaptive)

    def test_baseline_scenario_regression(self):
        simulator = simulate(dt=0.01)
        self.assertAlmostEqual(simulator.state[0], REFERENCE_RANGE, delta=1e-3)
        self.assertAlmostEqual(simulator.t, REFERENCE_FLIGHT_TIME, delta=1e-3)
        self.assertTrue(simulator.landed)


class StabilityAbsorptionTests(unittest.TestCase):
    """Inputs that used to fail loudly now complete with a shorter step."""

    def setUp(self):
        self._warnings = warnings.catch_warnings()
        self._warnings.__enter__()
        warnings.simplefilter('error', RuntimeWarning)
        self.addCleanup(self._warnings.__exit__, None, None, None)

    def test_coarse_timestep_completes_instead_of_raising(self):
        """The fixed mode warns then raises here; adaptive mode just shortens."""
        fixed = ProjectileSimulator(V0_MPS, ANGLE_RAD, dt=5.0)
        with allow_runtime_warnings():
            with self.assertRaises(ValueError):
                fixed.run_simulation()

        adaptive = simulate(dt=5.0)
        self.assertTrue(adaptive.landed)
        self.assertGreater(adaptive.state[0], 0.0)
        self.assertLess(adaptive.result().timestep_min, 5.0)

    def test_absurd_drag_no_longer_diverges(self):
        with allow_runtime_warnings():
            with self.assertRaises(SimulationDiverged):
                simulate(adaptive=False, constants={'mass': 1e-12})
        adaptive = simulate(constants={'mass': 1e-12})
        self.assertTrue(adaptive.landed)
        self.assertLess(adaptive.state[0], 1.0)

    def test_high_velocity_launch_completes(self):
        simulator = simulate(v0_mps=100000 * 1000 / 3600)
        self.assertTrue(simulator.landed)
        self.assertLess(simulator.result().timestep_min, 0.01)

    def test_adaptive_mode_never_warns(self):
        """Warnings are the fixed mode's contract; adaptive mode absorbs the cause."""
        for dt in (5.0, 50.0):
            with self.subTest(dt=dt):
                simulate(dt=dt)

    def test_time_limit_is_not_overshot(self):
        simulator = simulate(dt=1000.0, constants={'max_time': 0.02})
        self.assertTrue(simulator.timed_out)
        self.assertFalse(simulator.landed)
        self.assertLessEqual(simulator.t, 0.02)


class NoAccuracyClaimTests(unittest.TestCase):
    """Pins the known limit: the mode bounds divergence, it does not add accuracy."""

    def test_coarse_ceiling_still_loses_accuracy(self):
        simulator = simulate(dt=1.0)
        relative_error = abs(simulator.state[0] - REFERENCE_RANGE) / REFERENCE_RANGE
        self.assertGreater(
            relative_error,
            1e-3,
            'expected a 1.0 s ceiling to still show >0.1% error',
        )

    def test_refining_the_ceiling_still_improves_accuracy(self):
        coarse = abs(simulate(dt=0.2).state[0] - REFERENCE_RANGE)
        fine = abs(simulate(dt=0.002).state[0] - REFERENCE_RANGE)
        self.assertGreater(coarse, fine)

    def test_drag_disabled_matches_the_closed_form(self):
        simulator = simulate(dt=0.001, constants={'drag_coefficient': 0.0})
        expected = (V0_MPS**2 * math.sin(2 * ANGLE_RAD)) / GRAVITY
        self.assertAlmostEqual(simulator.state[0], expected, delta=1e-4)


class LifecycleTests(unittest.TestCase):
    """reset, resume and the step counters must keep working in adaptive mode."""

    def test_reset_clears_the_step_counters(self):
        simulator = simulate()
        self.assertGreater(simulator.result().steps, 0)
        simulator.reset()
        self.assertEqual(simulator.result().steps, 0)
        self.assertIsNone(simulator.result().timestep_min)

    def test_repeated_runs_are_idempotent(self):
        simulator = simulate(dt=5.0)
        first = simulator.run_simulation()
        second = simulator.run_simulation()
        self.assertEqual(first, second)

    def test_resume_after_landing_is_a_no_op(self):
        simulator = simulate()
        landed = simulator.result()
        self.assertEqual(
            simulator.run_simulation(resume=True),
            (landed.ground_range, landed.flight_time),
        )

    def test_resume_continues_accumulating_steps(self):
        simulator = simulate(dt=0.05, constants={'max_time': 2.0})
        self.assertTrue(simulator.timed_out)
        partial = simulator.result().steps
        simulator.run_simulation(resume=True)
        self.assertGreater(simulator.result().steps, partial)

    def test_ceiling_override_still_validates(self):
        simulator = ProjectileSimulator(V0_MPS, ANGLE_RAD, adaptive=True)
        with self.assertRaises(ValueError):
            simulator.run_simulation(dt=0.0)


class EdgeCaseTests(unittest.TestCase):
    """Launch conditions that collapse a trajectory to a single step."""

    def test_degenerate_angles_land_at_the_origin(self):
        for angle_deg in (0.0, 180.0, -45.0):
            with self.subTest(angle_deg=angle_deg):
                simulator = simulate(angle_rad=math.radians(angle_deg))
                self.assertEqual(simulator.state[0], 0.0)
                self.assertTrue(simulator.landed)

    def test_vertical_launch_has_no_range(self):
        simulator = simulate(angle_rad=math.radians(90.0))
        self.assertAlmostEqual(simulator.state[0], 0.0, delta=1e-9)
        self.assertGreater(simulator.t, 0.0)

    def test_zero_velocity_lands_immediately(self):
        simulator = simulate(v0_mps=0.0)
        self.assertEqual(simulator.run_simulation(), (0.0, 0.0))

    def test_first_step_guard_still_applies_without_drag(self):
        """With no drag there is no stability band, so a coarse ceiling must fail."""
        with self.assertRaises(ValueError) as caught:
            simulate(dt=1000.0, constants={'drag_coefficient': 0.0})
        self.assertIn('too coarse', str(caught.exception))


class CommandLineTests(unittest.TestCase):
    """The CLI must expose the ceiling and the mode flag without losing defaults."""

    def run_main(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = range_calc.main(argv)
        return exit_code, buffer.getvalue()

    def test_default_invocation_matches_the_v4_report(self):
        exit_code, output = self.run_main([])
        self.assertEqual(exit_code, 0)
        self.assertIn('101.12 m', output)
        self.assertIn('Timestep Ceiling: 0.01 s', output)
        self.assertIn('Integration Steps:', output)

    def test_adaptive_flag_is_reported(self):
        _, output = self.run_main(['--adaptive'])
        self.assertIn('adaptive timestep', output)
        self.assertIn('101.12 m', output)

    def test_coarse_ceiling_reports_the_shortened_step(self):
        _, output = self.run_main(['', '5', '--adaptive'])
        self.assertIn('Timestep Ceiling: 5 s', output)
        self.assertIn('Shortest Step Taken:', output)

    def test_empty_path_falls_back_to_the_shipped_scenario(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            self.assertEqual(
                range_calc.parse_args(['']),
                range_calc.CliArgs(None, 0.01, False, None, None, False, 7.0e6),
            )

    def test_parse_args_defaults(self):
        self.assertEqual(
            range_calc.parse_args(None),
            range_calc.CliArgs(None, 0.01, False, None, None, False, 7.0e6),
        )
        self.assertEqual(
            range_calc.parse_args(['data.csv', '0.05', '--adaptive']),
            range_calc.CliArgs('data.csv', 0.05, True, None, None, False, 7.0e6),
        )

    def test_parse_args_returns_launch_overrides(self):
        self.assertEqual(
            range_calc.parse_args(['--v0=160', '--angle=40']),
            range_calc.CliArgs(None, 0.01, False, 160.0, 40.0, False, 7.0e6),
        )
        self.assertEqual(
            range_calc.parse_args(['data.csv', '--angle=40']),
            range_calc.CliArgs('data.csv', 0.01, False, None, 40.0, False, 7.0e6),
        )

    def test_parse_args_returns_orbital_inputs(self):
        self.assertEqual(
            range_calc.parse_args(['--orbital', '--radius=8.0e6']),
            range_calc.CliArgs(None, 0.01, False, None, None, True, 8.0e6),
        )
        self.assertEqual(
            range_calc.parse_args(['--orbital', '--v0=27000']),
            range_calc.CliArgs(None, 0.01, False, 27000.0, None, True, 7.0e6),
        )

    def test_both_overrides_are_reported_without_touching_the_file(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            _, output = self.run_main(['missing.csv', '--v0=160', '--angle=40'])
        self.assertIn('Input Velocity: 160.0 km/h', output)
        self.assertIn('Launch Angle: 40.0 deg', output)

    def test_single_override_falls_back_per_field(self):
        _, output = self.run_main(['--v0=160'])
        self.assertIn('Input Velocity: 160.0 km/h', output)
        self.assertIn('Launch Angle: 35.0 deg', output)

    def test_single_override_with_missing_file_uses_the_default_angle(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            _, output = self.run_main(['missing.csv', '--v0=160'])
        self.assertIn('Input Velocity: 160.0 km/h', output)
        self.assertIn('Launch Angle: 35.0 deg', output)

    def test_bare_override_flags_are_rejected(self):
        for flag in ('--v0', '--angle', '--radius'):
            with self.subTest(flag=flag):
                with self.assertRaises(SystemExit):
                    range_calc.parse_args([flag])

    def test_non_numeric_override_is_rejected(self):
        with self.assertRaises(SystemExit):
            range_calc.parse_args(['--v0=fast'])

    def test_duplicate_override_is_rejected(self):
        with self.assertRaises(SystemExit):
            range_calc.parse_args(['--v0=160', '--v0=170'])

    def test_orbital_mode_reports_elements(self):
        exit_code, output = self.run_main(['--orbital', '--v0=27166'])
        self.assertEqual(exit_code, 0)
        self.assertIn('--- Orbital Simulation ---', output)
        self.assertIn('Gravity Model: Newtonian point mass', output)
        self.assertIn('Atmosphere: off', output)
        self.assertIn('--- Orbital Elements ---', output)
        self.assertIn('Eccentricity: 1.5', output)
        self.assertIn('Inclination: 0.0000 deg', output)
        self.assertIn('Period: 5828', output)

    def test_orbital_perturbation_flags_are_reported(self):
        _, output = self.run_main(['--orbital', '--v0=27166', '--j2', '--atmosphere'])
        self.assertIn('Gravity Model: J2 oblateness', output)
        self.assertIn('Atmosphere: on', output)

    def test_orbital_mode_rejects_a_non_positive_radius(self):
        with self.assertRaises(SystemExit):
            range_calc.main(['--orbital', '--radius=0'])


if __name__ == '__main__':
    unittest.main()
