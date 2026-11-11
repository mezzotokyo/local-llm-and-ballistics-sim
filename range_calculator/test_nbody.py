"""Tests for the mutual-gravity N-body module (:mod:`nbody`).

The suite mirrors the layout of the ballistics tests: analytic agreement where
a closed form exists (single-body drift, two-body circular orbits, Kepler
periods), conservation diagnostics, configuration validation, divergence and
singularity guards, and the module contract of performing no file I/O.

Flattened imports (``import nbody``) match the rest of the package; run the
suite from the repository root or from ``range_calculator/``.
"""

import math
import unittest
from pathlib import Path

import nbody
from ballistics import SimulationDiverged, X
from nbody import (
    Body,
    NBodySimulator,
    angular_momentum,
    center_of_mass,
    linear_momentum,
    mutual_gravity,
    system_derivatives,
    total_energy,
)


def circular_pair(mu1, mu2, separation):
    """Barycentre-frame circular pair ``(body1, body2)`` of the given separation.

    Body 1 sits on the -x side and body 2 on the +x side; both revolve
    counterclockwise so the total linear momentum vanishes and the centre of
    mass stays at the origin.
    """
    total = mu1 + mu2
    radius1 = separation * mu2 / total
    radius2 = separation * mu1 / total
    omega = math.sqrt(total / separation**3)
    body1 = Body(
        mu1, (-radius1, 0.0, 0.0, 0.0, -omega * radius1, 0.0)
    )
    body2 = Body(
        mu2, (radius2, 0.0, 0.0, 0.0, omega * radius2, 0.0)
    )
    return body1, body2


def pair_period(separation, mu1, mu2):
    """Kepler period of the relative two-body orbit (G = 1)."""
    return 2.0 * math.pi * math.sqrt(separation**3 / (mu1 + mu2))


def lagrange_triangle(mu=1.0, side=1.0):
    """Equilateral Lagrange configuration revolving counterclockwise.

    Three equal masses at the vertices of a regular triangle of the given
    side, with exactly the circular velocities of the L4/L5 relative
    equilibrium, so the shape rotates rigidly.
    """
    radius = side / math.sqrt(3.0)
    omega = math.sqrt(3.0 * mu / side**3)
    bodies = []
    for angle in (0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0):
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        bodies.append(
            Body(mu, (x, y, 0.0, -omega * y, omega * x, 0.0))
        )
    return tuple(bodies)


def lagrange_period(side=1.0, mu=1.0):
    """Rigid-rotation period of :func:`lagrange_triangle` (G = 1)."""
    return 2.0 * math.pi * math.sqrt(side**3 / (3.0 * mu))


def pair_separation(system, first=0, second=1):
    return math.dist(system[first][:3], system[second][:3])


class SingleBodyTests(unittest.TestCase):
    """With one body there is no force, so the motion is exactly inertial."""

    def test_moves_in_a_straight_line(self):
        state = (0.0, 0.0, 0.0, 1.0, 2.0, 3.0)
        simulator = NBodySimulator(
            [Body(1.0, state)], dt=0.01, max_time=10.0
        )
        elapsed = simulator.run_simulation()
        self.assertAlmostEqual(elapsed, 10.0, places=9)
        self.assertTrue(simulator.timed_out)
        # 1000 full steps plus one trimmed step that lands exactly on the
        # limit: the accumulation of 0.01 falls a few ulp short of 10.0, and
        # the trimming rule then covers the remainder instead of overshooting.
        self.assertEqual(simulator.steps, 1001)
        final = simulator.system[0]
        for index, component in enumerate((10.0, 20.0, 30.0)):
            self.assertAlmostEqual(final[index], component, places=9)
        self.assertEqual(final[3:], (1.0, 2.0, 3.0))

    def test_the_lone_bodys_mu_is_never_used(self):
        slow = NBodySimulator(
            [Body(1.0, (0.0, 0.0, 0.0, 1.0, 0.0, 0.0))],
            dt=0.01,
            max_time=1.0,
        )
        heavy = NBodySimulator(
            [Body(1e12, (0.0, 0.0, 0.0, 1.0, 0.0, 0.0))],
            dt=0.01,
            max_time=1.0,
        )
        slow.run_simulation()
        heavy.run_simulation()
        self.assertEqual(slow.system, heavy.system)


class MutualGravityFieldTests(unittest.TestCase):
    """The field itself, isolated from the integrator."""

    def test_acceleration_points_toward_the_other_body(self):
        field = mutual_gravity([1.0, 1.0])
        accelerations = field(
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             (3.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        )
        self.assertGreater(accelerations[0][0], 0.0)
        self.assertEqual(accelerations[0][1:], (0.0, 0.0))
        self.assertLess(accelerations[1][0], 0.0)

    def test_magnitude_is_mu_over_r_squared(self):
        field = mutual_gravity([1.0, 2.0])
        accelerations = field(
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             (3.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        )
        # body 0 feels body 1's mu over the squared distance
        self.assertAlmostEqual(accelerations[0][0], 2.0 / 9.0, places=12)
        # body 1 feels body 0's mu over the squared distance
        self.assertAlmostEqual(accelerations[1][0], -1.0 / 9.0, places=12)

    def test_acceleration_falls_off_as_the_inverse_square(self):
        field = mutual_gravity([1.0, 1.0])
        near = field(
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             (1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        )[0][0]
        far = field(
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             (2.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        )[0][0]
        self.assertAlmostEqual(near / far, 4.0, places=12)

    def test_three_body_acceleration_sums_the_pairs(self):
        field = mutual_gravity([1.0, 2.0, 3.0])
        system = (
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            (0.0, 2.0, 0.0, 0.0, 0.0, 0.0),
        )
        accelerations = field(system)
        self.assertAlmostEqual(accelerations[0][0], 2.0, places=12)
        self.assertAlmostEqual(accelerations[0][1], 3.0 / 4.0, places=12)
        self.assertAlmostEqual(accelerations[0][2], 0.0, places=12)

    def test_a_single_body_feels_nothing(self):
        field = mutual_gravity([5.0])
        accelerations = field(((1.0, 2.0, 3.0, 0.0, 0.0, 0.0),))
        self.assertEqual(accelerations, ((0.0, 0.0, 0.0),))

    def test_coincident_bodies_are_singular(self):
        field = mutual_gravity([1.0, 1.0])
        same = (1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
        with self.assertRaises(SimulationDiverged) as caught:
            field((same, same))
        self.assertIn("singular", str(caught.exception))

    def test_min_separation_stops_a_close_encounter(self):
        field = mutual_gravity([1.0, 1.0], min_separation=0.5)
        with self.assertRaises(SimulationDiverged) as caught:
            field(
                ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                 (0.4, 0.0, 0.0, 0.0, 0.0, 0.0))
            )
        self.assertIn("minimum separation", str(caught.exception))

    def test_min_separation_allows_distant_pairs(self):
        field = mutual_gravity([1.0, 1.0], min_separation=0.5)
        accelerations = field(
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             (1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        )
        self.assertAlmostEqual(accelerations[0][0], 1.0, places=12)

    def test_field_rejects_a_system_of_the_wrong_length(self):
        field = mutual_gravity([1.0, 1.0])
        with self.assertRaises(ValueError) as caught:
            field(
                ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0),) * 3
            )
        self.assertIn("built for 2", str(caught.exception))

    def test_mus_must_be_positive_and_finite(self):
        for bad in (0.0, -1.0, math.inf, math.nan):
            with self.assertRaises(ValueError):
                mutual_gravity([1.0, bad])
        with self.assertRaises(TypeError):
            mutual_gravity([1.0, "x"])
        with self.assertRaises(TypeError):
            mutual_gravity(3)
        mutual_gravity([1.0])

    def test_min_separation_must_be_non_negative(self):
        with self.assertRaises(ValueError):
            mutual_gravity([1.0, 1.0], min_separation=-0.1)


class SystemDerivativesTests(unittest.TestCase):
    """The equation of motion assembles velocities and field accelerations."""

    def test_velocities_lead_and_accelerations_follow(self):
        field = lambda system: ((1.0, 2.0, 3.0),)
        derivative = system_derivatives(
            ((10.0, 20.0, 30.0, 4.0, 5.0, 6.0),), field
        )
        self.assertEqual(derivative, ((4.0, 5.0, 6.0, 1.0, 2.0, 3.0),))

    def test_bodies_keep_their_order(self):
        field = lambda system: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        derivative = system_derivatives(
            (
                (0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            ),
            field,
        )
        self.assertEqual(
            derivative,
            (
                (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0, 1.0, 0.0),
            ),
        )


class TwoBodyTests(unittest.TestCase):
    """The circular two-body problem against its Kepler solution."""

    def setUp(self):
        self.mu1 = self.mu2 = 1.0
        self.separation = 1.0
        self.pair = circular_pair(self.mu1, self.mu2, self.separation)
        self.period = pair_period(self.separation, self.mu1, self.mu2)

    def test_returns_to_the_start_after_one_period(self):
        simulator = NBodySimulator(self.pair, dt=1e-3, max_time=self.period)
        simulator.run_simulation()
        for initial, final in zip(self.pair, simulator.system):
            for a, b in zip(initial.state, final):
                self.assertAlmostEqual(a, b, delta=1e-6)

    def test_separation_is_constant_throughout(self):
        observed = []
        simulator = NBodySimulator(self.pair, dt=1e-3, max_time=self.period)
        simulator.run_simulation(
            on_step=lambda t, system: observed.append(pair_separation(system))
        )
        self.assertGreater(len(observed), 100)
        for separation in observed:
            self.assertAlmostEqual(
                separation, self.separation, delta=1e-6
            )

    def test_the_barycentre_stays_at_the_origin(self):
        simulator = NBodySimulator(self.pair, dt=1e-3, max_time=self.period)
        simulator.run_simulation()
        for component in center_of_mass(simulator.bodies):
            self.assertAlmostEqual(component, 0.0, delta=1e-9)

    def test_unequal_masses_orbit_the_barycentre(self):
        pair = circular_pair(3.0, 1.0, 1.0)
        period = pair_period(1.0, 3.0, 1.0)
        simulator = NBodySimulator(pair, dt=1e-3, max_time=period)
        simulator.run_simulation()
        for initial, final in zip(pair, simulator.system):
            for a, b in zip(initial.state, final):
                self.assertAlmostEqual(a, b, delta=1e-6)
        # the heavier body hugs the barycentre
        self.assertLess(
            math.dist(pair[0].state[:3], simulator.system[0][:3]),
            math.dist(pair[1].state[:3], simulator.system[1][:3]),
        )

    def test_energy_matches_the_closed_form(self):
        energy = total_energy(self.pair)
        closed_form = -self.mu1 * self.mu2 / (2.0 * self.separation)
        self.assertAlmostEqual(energy, closed_form, places=10)


class KeplerLimitTests(unittest.TestCase):
    """A light body around a heavy one recovers the central-field orbit."""

    def setUp(self):
        self.heavy_mu = 1e6
        self.light_mu = 1.0
        self.separation = 1.0
        self.pair = circular_pair(
            self.heavy_mu, self.light_mu, self.separation
        )
        self.period = pair_period(
            self.separation, self.heavy_mu, self.light_mu
        )

    def test_the_separation_survives_one_period(self):
        simulator = NBodySimulator(self.pair, dt=1e-5, max_time=self.period)
        simulator.run_simulation()
        self.assertAlmostEqual(
            pair_separation(simulator.system), self.separation, delta=1e-6
        )

    def test_the_light_body_returns_to_its_start(self):
        simulator = NBodySimulator(self.pair, dt=1e-5, max_time=self.period)
        simulator.run_simulation()
        displacement = math.dist(
            self.pair[1].state[:3], simulator.system[1][:3]
        )
        self.assertLess(displacement, 1e-6)

    def test_the_heavy_body_hardly_moves(self):
        simulator = NBodySimulator(self.pair, dt=1e-5, max_time=self.period)
        simulator.run_simulation()
        wobble = math.dist(
            self.pair[0].state[:3], simulator.system[0][:3]
        )
        light_travel = math.dist(
            self.pair[1].state[:3], simulator.system[1][:3]
        )
        self.assertLess(wobble, 1e-10)
        self.assertLess(wobble, light_travel * 1e-3)


class ConservationTests(unittest.TestCase):
    """The exact invariants of mutual gravity, on the Lagrange triangle."""

    def setUp(self):
        self.bodies = lagrange_triangle()
        self.initial_energy = total_energy(self.bodies)
        self.initial_momentum = linear_momentum(self.bodies)
        self.initial_angular = angular_momentum(self.bodies)
        self.simulator = NBodySimulator(
            self.bodies, dt=1e-3, max_time=lagrange_period() / 4.0
        )
        self.simulator.run_simulation()

    def test_linear_momentum_is_conserved(self):
        momentum = linear_momentum(self.simulator.bodies)
        for initial, final in zip(self.initial_momentum, momentum):
            self.assertAlmostEqual(final - initial, 0.0, delta=1e-12)

    def test_angular_momentum_is_conserved(self):
        angular = angular_momentum(self.simulator.bodies)
        for initial, final in zip(self.initial_angular, angular):
            self.assertAlmostEqual(final - initial, 0.0, delta=1e-12)

    def test_energy_is_conserved(self):
        drift = abs(total_energy(self.simulator.bodies) - self.initial_energy)
        self.assertLess(drift, 1e-9)

    def test_energy_starts_at_the_lagrange_closed_form(self):
        # three unit masses at mutual distance 1: KE = 3/2, PE = -3
        self.assertAlmostEqual(self.initial_energy, -1.5, places=12)

    def test_angular_momentum_starts_at_the_closed_form(self):
        # L = 3 * mu * R with R = 1/sqrt(3), so L = sqrt(3)
        self.assertAlmostEqual(self.initial_angular[2], math.sqrt(3.0), places=12)
        self.assertEqual(self.initial_angular[:2], (0.0, 0.0))

    def test_energy_drift_shrinks_as_the_timestep_refines(self):
        """RK4 is not symplectic, but its energy error is still O(dt^4)."""
        pair = circular_pair(1.0, 1.0, 1.0)
        half_period = pair_period(1.0, 1.0, 1.0) / 2.0
        reference = total_energy(pair)
        coarse = NBodySimulator(pair, dt=1e-1, max_time=half_period)
        fine = NBodySimulator(pair, dt=1e-2, max_time=half_period)
        coarse.run_simulation()
        fine.run_simulation()
        coarse_drift = abs(total_energy(coarse.bodies) - reference)
        fine_drift = abs(total_energy(fine.bodies) - reference)
        self.assertGreater(coarse_drift, 1e-7)
        self.assertLess(fine_drift, coarse_drift / 1e3)


class LagrangeTests(unittest.TestCase):
    """The equilateral configuration rotates rigidly."""

    def test_the_shape_survives_one_period(self):
        bodies = lagrange_triangle()
        side = 1.0
        period = lagrange_period(side)
        simulator = NBodySimulator(bodies, dt=1e-3, max_time=period)
        simulator.run_simulation()
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertAlmostEqual(
                    pair_separation(simulator.system, i, j),
                    side,
                    delta=1e-6,
                )

    def test_every_body_returns_to_its_start(self):
        bodies = lagrange_triangle()
        simulator = NBodySimulator(
            bodies, dt=1e-3, max_time=lagrange_period()
        )
        simulator.run_simulation()
        for initial, final in zip(bodies, simulator.system):
            self.assertAlmostEqual(
                math.dist(initial.state[:3], final[:3]), 0.0, delta=1e-6
            )

    def test_the_period_follows_the_closed_form(self):
        # a longer triangle must revolve more slowly
        slow = lagrange_period(side=4.0)
        fast = lagrange_period(side=1.0)
        self.assertAlmostEqual(slow / fast, 8.0, places=12)


class DiagnosticTests(unittest.TestCase):
    """The helper functions reject undefined inputs and weight correctly."""

    def test_energy_rejects_overlapping_bodies(self):
        overlapping = (
            Body(1.0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Body(1.0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        )
        with self.assertRaises(ValueError):
            total_energy(overlapping)

    def test_center_of_mass_weights_by_mu(self):
        com = center_of_mass(
            [
                Body(3.0, (-1.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                Body(1.0, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            ]
        )
        self.assertAlmostEqual(com[0], -0.5, places=12)
        self.assertEqual(com[1:], (0.0, 0.0))

    def test_center_of_mass_rejects_an_empty_system(self):
        with self.assertRaises(ValueError):
            center_of_mass([])

    def test_momenta_of_a_body_at_rest_vanish(self):
        at_rest = [Body(2.0, (1.0, 2.0, 3.0, 0.0, 0.0, 0.0))]
        self.assertEqual(linear_momentum(at_rest), (0.0, 0.0, 0.0))
        self.assertEqual(angular_momentum(at_rest), (0.0, 0.0, 0.0))

    def test_bodies_property_reports_the_current_state(self):
        pair = circular_pair(1.0, 1.0, 1.0)
        simulator = NBodySimulator(pair, dt=1e-3, max_time=0.1)
        self.assertEqual(simulator.bodies, pair)
        simulator.run_simulation()
        self.assertEqual(
            tuple(body.state for body in simulator.bodies), simulator.system
        )
        self.assertEqual(
            tuple(body.mu for body in simulator.bodies), simulator.mus
        )


class ValidationTests(unittest.TestCase):
    """Constructor inputs are validated before any integration starts."""

    def test_rejects_an_empty_system(self):
        with self.assertRaises(ValueError):
            NBodySimulator([])

    def test_rejects_a_non_sequence(self):
        with self.assertRaises(TypeError):
            NBodySimulator(3)

    def test_rejects_a_non_body_entry(self):
        with self.assertRaises(TypeError):
            NBodySimulator([(1.0, (0, 0, 0, 0, 0, 0))])

    def test_rejects_bad_mu(self):
        state = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for bad in (0.0, -1.0, math.inf, math.nan):
            with self.assertRaises(ValueError):
                NBodySimulator(
                    [Body(1.0, state), Body(bad, state)]
                )
        with self.assertRaises(TypeError):
            NBodySimulator([Body(1.0, state), Body("x", state)])
        with self.assertRaises(TypeError):
            NBodySimulator([Body(1.0, state), Body(True, state)])

    def test_rejects_a_malformed_state(self):
        with self.assertRaises(ValueError):
            NBodySimulator(
                [Body(1.0, (0.0, 0.0, 0.0)), Body(1.0, (1.0, 0, 0, 0, 0, 0))]
            )
        with self.assertRaises(TypeError):
            NBodySimulator(
                [Body(1.0, "xxxxxx"), Body(1.0, (1.0, 0, 0, 0, 0, 0))]
            )
        with self.assertRaises(ValueError):
            NBodySimulator(
                [Body(1.0, (0.0,) * 5 + (math.inf,)),
                 Body(1.0, (1.0, 0, 0, 0, 0, 0))]
            )

    def test_rejects_coincident_starting_positions(self):
        same = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        with self.assertRaises(ValueError) as caught:
            NBodySimulator([Body(1.0, same), Body(1.0, same)])
        self.assertIn("same position", str(caught.exception))

    def test_rejects_a_start_closer_than_min_separation(self):
        with self.assertRaises(ValueError) as caught:
            NBodySimulator(
                [Body(1.0, (0, 0, 0, 0, 0, 0)),
                 Body(1.0, (0.1, 0, 0, 0, 0, 0))],
                min_separation=0.2,
            )
        self.assertIn("min_separation", str(caught.exception))

    def test_rejects_bad_timestep_and_limits(self):
        pair = circular_pair(1.0, 1.0, 1.0)
        for bad in (0.0, -1.0, math.inf):
            with self.assertRaises(ValueError):
                NBodySimulator(pair, dt=bad)
            with self.assertRaises(ValueError):
                NBodySimulator(pair, max_time=bad)
            with self.assertRaises(ValueError):
                NBodySimulator(pair, divergence_speed_factor=bad)
        for bad in (-0.1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                NBodySimulator(pair, min_separation=bad)

    def test_accepts_list_states_and_converts_them(self):
        simulator = NBodySimulator(
            [Body(1.0, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]),
             Body(1.0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0])],
            dt=0.01,
            max_time=0.01,
        )
        self.assertIsInstance(simulator.system[0], tuple)
        self.assertEqual(len(simulator.system[0]), 6)


class SingularityTests(unittest.TestCase):
    """Collisions are unmodelable; they must fail loudly when guarded."""

    def falling_pair(self):
        return [
            Body(1.0, (-0.5, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Body(1.0, (0.5, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ]

    def test_min_separation_stops_a_head_on_collision(self):
        simulator = NBodySimulator(
            self.falling_pair(), dt=1e-3, max_time=5.0, min_separation=0.05
        )
        with self.assertRaises(SimulationDiverged) as caught:
            simulator.run_simulation()
        self.assertIn("minimum separation", str(caught.exception))
        self.assertLess(simulator.t, 1.0)

    def test_without_a_guard_the_bodies_pass_through(self):
        """Documents the known limit: unguarded collisions become artifacts.

        The pair falls from rest, steps over the singular region, and emerges
        on the other side with finite numbers. Nothing diverges, so only
        ``min_separation`` turns the encounter into a loud failure.
        """
        simulator = NBodySimulator(
            self.falling_pair(), dt=1e-3, max_time=5.0
        )
        simulator.run_simulation()
        self.assertTrue(simulator.timed_out)
        self.assertGreater(simulator.system[0][X], 0.0)
        self.assertLess(simulator.system[1][X], 0.0)
        self.assertTrue(
            all(math.isfinite(component) for body in simulator.system
                for component in body)
        )


class DivergenceGuardTests(unittest.TestCase):
    """Injected fields exercise the guards without physical fine-tuning."""

    def bodies_at_rest(self):
        return [
            Body(1.0, (-0.5, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Body(1.0, (0.5, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ]

    def bodies_with_speed(self):
        return [
            Body(1.0, (-0.5, 0.0, 0.0, 0.0, 1.0, 0.0)),
            Body(1.0, (0.5, 0.0, 0.0, 0.0, -1.0, 0.0)),
        ]

    def test_non_finite_forces_are_detected(self):
        def poison(system):
            return tuple((math.inf, math.inf, math.inf) for _ in system)

        simulator = NBodySimulator(
            self.bodies_at_rest(),
            dt=1e-3,
            max_time=1.0,
            gravity_model=poison,
        )
        with self.assertRaises(SimulationDiverged) as caught:
            simulator.run_simulation()
        self.assertIn("non-finite", str(caught.exception))

    def test_speed_explosion_is_detected(self):
        def huge(system):
            return tuple((1e10, 0.0, 0.0) for _ in system)

        simulator = NBodySimulator(
            self.bodies_with_speed(),
            dt=1e-3,
            max_time=1.0,
            gravity_model=huge,
        )
        with self.assertRaises(SimulationDiverged) as caught:
            simulator.run_simulation()
        self.assertIn("too coarse", str(caught.exception))

    def test_a_resting_system_has_no_speed_baseline(self):
        """The speed guard needs an initial speed; rests rely on finiteness."""

        def huge(system):
            return tuple((1e10, 0.0, 0.0) for _ in system)

        simulator = NBodySimulator(
            self.bodies_at_rest(),
            dt=1e-3,
            max_time=1e-2,
            gravity_model=huge,
        )
        elapsed = simulator.run_simulation()
        self.assertAlmostEqual(elapsed, 1e-2, places=12)
        self.assertTrue(simulator.timed_out)

    def test_divergence_speed_factor_widens_the_limit(self):
        def huge(system):
            return tuple((1e10, 0.0, 0.0) for _ in system)

        simulator = NBodySimulator(
            self.bodies_with_speed(),
            dt=1e-3,
            max_time=1e-2,
            divergence_speed_factor=1e12,
            gravity_model=huge,
        )
        simulator.run_simulation()
        self.assertTrue(simulator.timed_out)


class LifecycleTests(unittest.TestCase):
    """reset / resume / idempotence mirror the ProjectileSimulator contract."""

    def setUp(self):
        self.pair = circular_pair(1.0, 1.0, 1.0)

    def test_repeated_runs_are_idempotent(self):
        simulator = NBodySimulator(self.pair, dt=1e-2, max_time=0.5)
        first = simulator.run_simulation()
        steps = simulator.steps
        second = simulator.run_simulation()
        self.assertEqual(first, second)
        self.assertEqual(steps, simulator.steps)

    def test_reset_restores_the_initial_system(self):
        simulator = NBodySimulator(self.pair, dt=1e-2, max_time=0.5)
        simulator.run_simulation(dt=1e-3)
        simulator.reset()
        self.assertEqual(simulator.system, simulator.initial_system)
        self.assertEqual(simulator.t, 0.0)
        self.assertEqual(simulator.steps, 0)
        self.assertFalse(simulator.timed_out)
        self.assertEqual(simulator.dt, simulator.default_dt)

    def test_resume_after_timeout_is_a_no_op(self):
        simulator = NBodySimulator(self.pair, dt=1e-2, max_time=0.2)
        simulator.run_simulation()
        steps = simulator.steps
        elapsed = simulator.run_simulation(resume=True)
        self.assertAlmostEqual(elapsed, 0.2, places=12)
        self.assertEqual(simulator.steps, steps)

    def test_on_step_observes_the_start_and_every_accepted_step(self):
        seen = []
        simulator = NBodySimulator(self.pair, dt=0.01, max_time=0.05)
        simulator.run_simulation(on_step=lambda t, system: seen.append(t))
        self.assertEqual(len(seen), simulator.steps + 1)
        self.assertEqual(seen[0], 0.0)
        self.assertAlmostEqual(seen[-1], 0.05, places=12)

    def test_timestep_override_is_validated(self):
        simulator = NBodySimulator(self.pair)
        with self.assertRaises(ValueError):
            simulator.run_simulation(dt=0.0)

    def test_result_reports_the_run_counters(self):
        simulator = NBodySimulator(self.pair, dt=0.01, max_time=0.05)
        simulator.run_simulation()
        result = simulator.result()
        self.assertAlmostEqual(result.elapsed_time, 0.05, places=12)
        self.assertEqual(result.steps, 5)
        self.assertTrue(result.timed_out)


class AdaptiveTimestepTests(unittest.TestCase):
    """Adaptive mode: dt is a ceiling, the step only ever shrinks."""

    def setUp(self):
        # A barycentre circular pair of unit separation: the two-body period is
        # constant, so the adaptive step is constant too.
        self.pair = circular_pair(1.0, 1.0, 1.0)
        self.period = pair_period(1.0, 1.0, 1.0)
        self.adaptive_step = self.period / nbody.ADAPTIVE_STEPS_PER_PERIOD

    def test_step_never_exceeds_the_ceiling(self):
        simulator = NBodySimulator(
            self.pair, dt=0.5, max_time=self.period, adaptive=True
        )
        simulator.run_simulation()
        result = simulator.result()
        self.assertLessEqual(result.timestep_max, 0.5)
        self.assertAlmostEqual(
            result.timestep_max, self.adaptive_step, places=9
        )
        self.assertLessEqual(result.timestep_min, result.timestep_max)

    def test_shortens_a_ceiling_that_is_too_coarse(self):
        coarse = NBodySimulator(
            self.pair, dt=0.5, max_time=self.period, adaptive=False
        )
        adaptive = NBodySimulator(
            self.pair, dt=0.5, max_time=self.period, adaptive=True
        )
        coarse.run_simulation()
        adaptive.run_simulation()
        self.assertLess(adaptive.result().timestep_max, 0.5)
        self.assertGreater(adaptive.steps, coarse.steps)

    def test_matches_fixed_mode_below_the_adaptive_limit(self):
        fixed = NBodySimulator(self.pair, dt=0.01, max_time=self.period)
        adaptive = NBodySimulator(
            self.pair, dt=0.01, max_time=self.period, adaptive=True
        )
        fixed.run_simulation()
        adaptive.run_simulation()
        self.assertEqual(fixed.steps, adaptive.steps)
        self.assertEqual(fixed.system, adaptive.system)

    def test_a_single_body_has_no_orbit_to_resolve(self):
        bodies = (Body(1.0, (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)),)
        fixed = NBodySimulator(bodies, dt=0.1, max_time=1.0)
        adaptive = NBodySimulator(bodies, dt=0.1, max_time=1.0, adaptive=True)
        fixed.run_simulation()
        adaptive.run_simulation()
        self.assertEqual(fixed.steps, adaptive.steps)
        self.assertEqual(fixed.system, adaptive.system)

    def test_keeps_steps_per_orbit(self):
        simulator = NBodySimulator(
            self.pair, dt=self.period, max_time=self.period, adaptive=True
        )
        simulator.run_simulation()
        # ADAPTIVE_STEPS_PER_PERIOD steps for one period, plus at most one
        # trimmed step from the floating-point remainder.
        self.assertGreaterEqual(simulator.steps, nbody.ADAPTIVE_STEPS_PER_PERIOD)
        self.assertLessEqual(
            simulator.steps, nbody.ADAPTIVE_STEPS_PER_PERIOD + 2
        )

    def test_conserves_energy_over_a_coarse_ceiling(self):
        simulator = NBodySimulator(
            self.pair, dt=0.5, max_time=self.period, adaptive=True
        )
        before = total_energy(simulator.bodies)
        simulator.run_simulation()
        after = total_energy(simulator.bodies)
        self.assertLess(abs(after - before) / abs(before), 1e-5)


class ResultTimestepTests(unittest.TestCase):
    """SystemResult exposes the step bounds in both modes."""

    def setUp(self):
        self.pair = circular_pair(1.0, 1.0, 1.0)

    def test_before_a_run_the_bounds_are_none(self):
        simulator = NBodySimulator(self.pair)
        self.assertIsNone(simulator.result().timestep_min)
        self.assertIsNone(simulator.result().timestep_max)

    def test_fixed_mode_reports_the_ceiling(self):
        simulator = NBodySimulator(self.pair, dt=0.01, max_time=0.05)
        simulator.run_simulation()
        result = simulator.result()
        self.assertAlmostEqual(result.timestep_max, 0.01, places=12)
        self.assertAlmostEqual(result.timestep_min, 0.01, places=12)


class ContractTests(unittest.TestCase):
    """The core module keeps the same boundaries as ballistics."""

    def test_module_performs_no_file_io(self):
        source = Path(nbody.__file__).read_text(encoding='utf-8')
        for forbidden in ('open(', 'read_text', 'json', 'csv'):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
