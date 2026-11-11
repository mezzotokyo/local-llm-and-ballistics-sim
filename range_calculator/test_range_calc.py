import contextlib
import io
import json
import math
import tempfile
import unittest
import warnings
from pathlib import Path

import ballistics
import range_calc as range_calc
from ballistics import ProjectileSimulator, SimulationDiverged
from physics_config import (
    DEFAULT_PARAMETERS,
    PhysicalParameters,
    coerce_parameters,
    load_parameters,
)
from range_calc import ProjectileConstants

GRAVITY = ProjectileConstants.GRAVITY
DRAG_K = ProjectileConstants.drag_scaling_factor()

V0_KMPH = 170.0
V0_MPS = V0_KMPH * (1000 / 3600)
ANGLE_DEG = 35.0


def simulate(v0_mps=V0_MPS, angle_deg=ANGLE_DEG, k=DRAG_K, dt=0.01):
    """Runs the drag simulation and returns the simulator so state can be inspected."""
    simulator = ProjectileSimulator(
        v0_mps, math.radians(angle_deg), {'drag_scaling_factor': k}
    )
    simulator.run_simulation(dt)
    return simulator


class AnalyticAgreementTests(unittest.TestCase):
    """With drag disabled the integration must reproduce the closed-form solution."""

    def test_range_matches_closed_form(self):
        angle_rad = math.radians(ANGLE_DEG)
        expected = (V0_MPS**2 * math.sin(2 * angle_rad)) / GRAVITY
        simulator = simulate(k=0.0, dt=0.001)
        self.assertAlmostEqual(simulator.state[0], expected, delta=1e-4)

    def test_flight_time_matches_closed_form(self):
        angle_rad = math.radians(ANGLE_DEG)
        expected = (2 * V0_MPS * math.sin(angle_rad)) / GRAVITY
        simulator = simulate(k=0.0, dt=0.001)
        self.assertAlmostEqual(simulator.t, expected, delta=1e-4)

    def test_vertical_launch_matches_closed_form_time(self):
        expected = (2 * V0_MPS) / GRAVITY
        simulator = simulate(angle_deg=90.0, k=0.0, dt=0.001)
        self.assertAlmostEqual(simulator.t, expected, delta=1e-4)


class ConvergenceTests(unittest.TestCase):
    """The landing interpolation must make the result independent of the timestep."""

    def test_result_converges_with_smaller_timestep(self):
        coarse = simulate(dt=0.01)
        fine = simulate(dt=0.002)
        self.assertAlmostEqual(coarse.state[0], fine.state[0], delta=1e-3)
        self.assertAlmostEqual(coarse.t, fine.t, delta=1e-4)

    def test_result_matches_fine_reference(self):
        reference = simulate(dt=0.0001)
        actual = simulate(dt=0.01)
        self.assertAlmostEqual(actual.state[0], reference.state[0], delta=1e-3)
        self.assertAlmostEqual(actual.t, reference.t, delta=1e-4)


class LandingStateTests(unittest.TestCase):
    """The state after landing must be physically consistent."""

    def test_lands_at_ground_level(self):
        simulator = simulate()
        self.assertEqual(simulator.state[1], 0.0)

    def test_is_still_descending_at_landing(self):
        simulator = simulate()
        self.assertLess(simulator.state[ballistics.VY], 0.0)

    def test_horizontal_launch_lands_at_origin(self):
        simulator = simulate(angle_deg=0.0)
        self.assertEqual(simulator.state[0], 0.0)
        self.assertEqual(simulator.t, 0.0)

    def test_zero_velocity_lands_at_origin(self):
        simulator = simulate(v0_mps=0.0)
        self.assertEqual(simulator.state[0], 0.0)
        self.assertEqual(simulator.t, 0.0)

    def test_vertical_launch_has_no_horizontal_range(self):
        simulator = simulate(angle_deg=90.0)
        self.assertLess(abs(simulator.state[0]), 1e-9)


class PhysicsTests(unittest.TestCase):
    """Qualitative expectations that must hold regardless of the integrator."""

    def test_drag_shortens_range(self):
        simulator = simulate()
        self.assertLess(simulator.state[0], simulator.calculate_ideal_range())

    def test_optimal_angle_is_below_45_degrees(self):
        best_angle = max(
            range(1, 90),
            key=lambda deg: simulate(angle_deg=deg, dt=0.001).state[0],
        )
        self.assertLess(best_angle, 45)
        self.assertGreater(best_angle, 30)


class RegressionTests(unittest.TestCase):
    """Golden values for the reference scenario stored in data.csv (170 km/h, 35 deg)."""

    def test_reference_range(self):
        simulator = simulate()
        self.assertAlmostEqual(simulator.state[0], 101.1214, delta=1e-3)

    def test_reference_flight_time(self):
        simulator = simulate()
        self.assertAlmostEqual(simulator.t, 4.37386, delta=1e-4)


class SimulatorContractTests(unittest.TestCase):
    """The refactored simulator must stay predictable and self-contained."""

    def test_run_simulation_is_idempotent(self):
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG))
        first = simulator.run_simulation()
        second = simulator.run_simulation()
        self.assertEqual(first, second)

    def test_reset_restores_launch_state(self):
        simulator = simulate()
        simulator.reset()
        self.assertEqual(simulator.state, simulator.initial_state)
        self.assertEqual(simulator.t, 0.0)
        self.assertFalse(simulator.landed)

    def test_resume_after_landing_is_a_no_op(self):
        simulator = simulate()
        landed = simulator.result()
        self.assertEqual(simulator.run_simulation(resume=True), (landed.ground_range, landed.flight_time))

    def test_result_exposes_richer_details(self):
        simulator = simulate()
        ground_range, flight_time = simulator.run_simulation()
        result = simulator.result()
        self.assertEqual(ground_range, result.ground_range)
        self.assertEqual(flight_time, result.flight_time)
        self.assertTrue(result.landed)
        self.assertFalse(result.timed_out)
        self.assertGreater(result.impact_speed, 0.0)

    def test_time_limit_is_reported(self):
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG), {'max_time': 0.02})
        simulator.run_simulation()
        self.assertTrue(simulator.timed_out)
        self.assertFalse(simulator.landed)

    def test_rejects_invalid_constants_type(self):
        with self.assertRaises(TypeError):
            ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG), constants=object())

    def test_rejects_non_positive_timestep(self):
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG))
        with self.assertRaises(ValueError):
            simulator.run_simulation(dt=0.0)

    def test_rejects_unknown_constants_key(self):
        with self.assertRaises(ValueError):
            ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG), {'nope': 1.0})

    def test_rejects_non_finite_velocity(self):
        with self.assertRaises(ValueError):
            ProjectileSimulator(math.inf, math.radians(ANGLE_DEG))

    def test_core_module_performs_no_file_io(self):
        source = Path(ballistics.__file__).read_text(encoding='utf-8')
        for forbidden in ('open(', 'read_text', 'json', 'csv'):
            self.assertNotIn(forbidden, source)


class ConfigurationTests(unittest.TestCase):
    """Constants live in config/physics_constants.json and are validated."""

    def test_shipped_config_matches_built_in_defaults(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            self.assertEqual(load_parameters(), PhysicalParameters())

    def test_defaults_class_attributes_track_the_profile(self):
        self.assertEqual(ProjectileConstants.GRAVITY, DEFAULT_PARAMETERS.gravity)
        self.assertEqual(
            ProjectileConstants.DRAG_COEFFICIENT, DEFAULT_PARAMETERS.drag_coefficient
        )

    def test_drag_scaling_factor_inverts_round_trip(self):
        parameters = DEFAULT_PARAMETERS
        inverted = parameters.with_drag_scaling_factor(parameters.drag_scaling_factor())
        self.assertAlmostEqual(
            inverted.drag_scaling_factor(), parameters.drag_scaling_factor()
        )

    def test_legacy_drag_mapping_matches_config_profile(self):
        legacy = coerce_parameters({'drag_scaling_factor': DRAG_K})
        self.assertAlmostEqual(legacy.drag_scaling_factor(), DRAG_K)
        self.assertAlmostEqual(legacy.gravity, GRAVITY)

    def test_config_override_reaches_the_simulation(self):
        low_gravity = coerce_parameters({'gravity': GRAVITY / 2})
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG), low_gravity)
        self.assertAlmostEqual(
            simulator.calculate_ideal_range(),
            2 * (V0_MPS**2 * math.sin(2 * math.radians(ANGLE_DEG))) / GRAVITY,
        )

    def test_missing_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertWarns(UserWarning):
                parameters = load_parameters(Path(tmp) / 'absent.json')
        self.assertEqual(parameters, PhysicalParameters())

    def test_config_partial_override_keeps_other_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'constants.json'
            config.write_text(json.dumps({'mass': 0.5}), encoding='utf-8')
            parameters = load_parameters(config)
        self.assertEqual(parameters.mass, 0.5)
        self.assertEqual(parameters.gravity, PhysicalParameters().gravity)

    def test_unknown_config_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'constants.json'
            config.write_text(json.dumps({'massa': 0.5}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_parameters(config)

    def test_invalid_config_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'constants.json'
            config.write_text('{not json', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_parameters(config)

    def test_non_positive_mass_is_rejected(self):
        with self.assertRaises(ValueError):
            PhysicalParameters(mass=0.0)

    def test_negative_air_density_is_rejected(self):
        with self.assertRaises(ValueError):
            PhysicalParameters(air_density=-1.0)

    def test_non_numeric_constant_is_rejected(self):
        with self.assertRaises(TypeError):
            PhysicalParameters(mass='149g')


class ScenarioLoadingTests(unittest.TestCase):
    """The CLI layer owns CSV parsing and must degrade gracefully."""

    def test_load_scenario_reads_shipped_data(self):
        velocity_kmph, angle_deg = range_calc.load_scenario()
        self.assertEqual(velocity_kmph, 170.0)
        self.assertEqual(angle_deg, 35.0)

    def test_load_scenario_falls_back_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertWarns(UserWarning):
                velocity_kmph, angle_deg = range_calc.load_scenario(
                    Path(tmp) / 'missing.csv'
                )
        self.assertEqual(velocity_kmph, range_calc.DEFAULT_VELOCITY_KMPH)
        self.assertEqual(angle_deg, range_calc.DEFAULT_ANGLE_DEG)

    def test_load_scenario_falls_back_when_malformed(self):
        for content in ('', '170\n', 'abc,def', '170,\n'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'data.csv'
                path.write_text(content, encoding='utf-8')
                with self.assertWarns(UserWarning):
                    velocity_kmph, angle_deg = range_calc.load_scenario(path)
            self.assertEqual(velocity_kmph, range_calc.DEFAULT_VELOCITY_KMPH)
            self.assertEqual(angle_deg, range_calc.DEFAULT_ANGLE_DEG)

    def test_load_scenario_ignores_extra_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.csv'
            path.write_text('170,35,notes\n', encoding='utf-8')
            with warnings.catch_warnings():
                warnings.simplefilter('error')
                self.assertEqual(range_calc.load_scenario(path), (170.0, 35.0))

    def test_main_runs_and_reports_results(self):
        buffer = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(range_calc.main(), 0)
        output = buffer.getvalue()
        self.assertIn('Ideal Range (No Drag)', output)
        self.assertIn('101.12 m', output)


class NumericalGuardTests(unittest.TestCase):
    """Coarse timesteps must fail loudly instead of returning meaningless numbers."""

    def setUp(self):
        self._ignore_warnings = warnings.catch_warnings()
        self._ignore_warnings.__enter__()
        warnings.simplefilter('ignore', RuntimeWarning)
        self.addCleanup(self._ignore_warnings.__exit__, None, None, None)

    def simulate_or_raise(self, v0_mps=V0_MPS, angle_deg=ANGLE_DEG, **kwargs):
        return ProjectileSimulator(
            v0_mps, math.radians(angle_deg), **kwargs
        ).run_simulation()

    def test_coarse_timestep_warns_about_accuracy(self):
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG), dt=5.0)
        with self.assertWarns(RuntimeWarning) as caught:
            with self.assertRaises(ValueError):
                simulator.run_simulation()
        message = str(caught.warning)
        self.assertIn('dt*k*v', message)
        self.assertIn('Use dt <=', message)

    def test_recommended_timestep_is_stable(self):
        """The advertised dt restores stability, but is not an accuracy promise."""
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG))
        with self.assertWarns(RuntimeWarning) as caught:
            with self.assertRaises(ValueError):
                simulator.run_simulation(dt=5.0)
        recommended = float(
            str(caught.warning)
            .rsplit('Use dt <= ', 1)[1]
            .split(' ')[0]
        )
        self.assertGreater(recommended, 0.0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            ground_range, flight_time = simulator.run_simulation(dt=recommended)
        self.assertGreater(ground_range, 0.0)
        self.assertTrue(simulator.landed)
        self.assertGreater(flight_time, 0.0)

    def test_stability_bound_does_not_imply_accuracy(self):
        """Documents the known limit: stability guards divergence, not error size."""
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG))
        with self.assertWarns(RuntimeWarning):
            with self.assertRaises(ValueError):
                simulator.run_simulation(dt=5.0)
        stable_dt = ProjectileSimulator._stable_timestep(simulator.k, V0_MPS)
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            at_limit = simulator.run_simulation(dt=stable_dt)[0]
            accurate = simulator.run_simulation(dt=0.01)[0]
        self.assertGreater(
            abs(at_limit - accurate) / accurate,
            1e-3,
            'expected the stability boundary to still show >0.1% error',
        )

    def test_upward_launch_landing_in_first_step_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.simulate_or_raise(dt=5.0)
        self.assertIn('too coarse', str(caught.exception))

    def test_speed_explosion_is_detected(self):
        with self.assertRaises(SimulationDiverged) as caught:
            self.simulate_or_raise(dt=50.0)
        self.assertIn('too coarse', str(caught.exception))

    def test_absurd_drag_is_detected(self):
        with self.assertRaises(SimulationDiverged):
            self.simulate_or_raise(constants={'mass': 1e-12})
        with self.assertRaises(SimulationDiverged):
            self.simulate_or_raise(constants={'drag_coefficient': 1e6})

    def test_high_velocity_launch_warns_about_accuracy(self):
        simulator = ProjectileSimulator(100000 * 1000 / 3600, math.radians(35))
        with self.assertWarns(RuntimeWarning):
            simulator.run_simulation()

    def test_divergence_speed_factor_is_configurable(self):
        simulator = ProjectileSimulator(
            V0_MPS, math.radians(ANGLE_DEG), divergence_speed_factor=1e6
        )
        with self.assertRaises(SimulationDiverged):
            simulator.run_simulation(dt=50.0)

    def test_divergence_speed_factor_must_be_positive(self):
        with self.assertRaises(ValueError):
            ProjectileSimulator(
                V0_MPS, math.radians(ANGLE_DEG), divergence_speed_factor=0.0
            )

    def test_normal_scenarios_are_not_rejected(self):
        for angle in (0.0, 35.0, 45.0, 90.0, -45.0, 180.0):
            with self.subTest(angle=angle):
                with warnings.catch_warnings():
                    warnings.simplefilter('error', RuntimeWarning)
                    self.simulate_or_raise(angle_deg=angle)
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            self.simulate_or_raise(v0_mps=0.0)

    def test_horizontal_launch_still_lands_at_origin(self):
        self.assertEqual(self.simulate_or_raise(angle_deg=0.0), (0.0, 0.0))

    def test_no_warning_when_drag_is_disabled(self):
        simulator = ProjectileSimulator(
            V0_MPS, math.radians(ANGLE_DEG), {'drag_scaling_factor': 0.0}, dt=1.0
        )
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            ground_range, flight_time = simulator.run_simulation()
        self.assertGreater(ground_range, 0.0)
        self.assertGreater(flight_time, 0.0)

    def test_divergence_leaves_the_simulator_reusable(self):
        simulator = ProjectileSimulator(V0_MPS, math.radians(ANGLE_DEG))
        with self.assertRaises(SimulationDiverged):
            simulator.run_simulation(dt=50.0)
        simulator.reset()
        self.assertEqual(simulator.state, simulator.initial_state)
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            self.assertAlmostEqual(simulator.run_simulation()[0], 101.1214, delta=1e-3)


def spin_simulate(spin_rpm, axis_deg, dt=0.005, k=DRAG_K):
    simulator = ProjectileSimulator(
        V0_MPS,
        math.radians(ANGLE_DEG),
        {'drag_scaling_factor': k},
        dt=dt,
        lift_model=ballistics.magnus_lift(
            DEFAULT_PARAMETERS, spin_rpm, axis_deg
        ),
    )
    simulator.run_simulation()
    return simulator.result()


class MagnusLiftTests(unittest.TestCase):
    """The spin force is vertical for backspin and lateral for sidespin."""

    def test_zero_spin_reproduces_the_drag_only_flight(self):
        spun = spin_simulate(0.0, 0.0)
        baseline = simulate(dt=0.005).result()
        self.assertEqual(spun, baseline)

    def test_backspin_extends_and_topspin_shortens_the_range(self):
        baseline = spin_simulate(0.0, 0.0).ground_range
        backspin = spin_simulate(2500.0, 0.0)
        topspin = spin_simulate(-2500.0, 0.0)
        self.assertGreater(backspin.ground_range, baseline)
        self.assertLess(topspin.ground_range, baseline)
        self.assertEqual(backspin.lateral_range, 0.0)
        self.assertEqual(topspin.lateral_range, 0.0)

    def test_sidespin_curves_symmetrically_without_changing_the_range(self):
        positive = spin_simulate(2500.0, 90.0)
        negative = spin_simulate(2500.0, -90.0)
        self.assertGreater(positive.lateral_range, 0.0)
        self.assertLess(negative.lateral_range, 0.0)
        self.assertAlmostEqual(
            positive.lateral_range, -negative.lateral_range, delta=1e-6
        )
        self.assertAlmostEqual(
            positive.ground_range, negative.ground_range, delta=1e-6
        )

    def test_spin_axis_vector_convention(self):
        self.assertEqual(ballistics.spin_axis_vector(0.0), (0.0, 0.0, 1.0))
        x, y, z = ballistics.spin_axis_vector(90.0)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, -1.0)
        self.assertAlmostEqual(z, 0.0)


if __name__ == '__main__':
    unittest.main()