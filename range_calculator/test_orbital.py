"""Tests for the Newtonian spherical gravity model added for orbital mechanics.

The gravity model is exposed as a field ``state -> (ax, ay, az)`` so the same
RK4 integrator can run either the flat-earth ballistics model or an inverse-square
field about the origin. These tests pin the field's shape and the behaviour of a
circular orbit integrated through :class:`ProjectileSimulator`.
"""

import math
import unittest

from ballistics import (
    EARTH_ATMOSPHERE_LAYERS,
    EQUATORIAL_RADIUS_EARTH,
    J2_EARTH,
    X,
    Y,
    Z,
    VX,
    VY,
    VZ,
    ProjectileSimulator,
    atmospheric_drag,
    constant_density,
    constant_drag,
    constant_gravity,
    derivatives,
    derivatives_with_gravity,
    derivatives_with_models,
    exponential_density,
    flat_altitude,
    j2_gravity,
    newtonian_gravity,
    orbital_altitude,
    sum_fields,
    tabulated_density,
)
from orbital import orbital_elements
from physics_config import coerce_parameters

MU = 3.986004418e14
ORBIT_RADIUS = 7.0e6


class NewtonianGravityFieldTests(unittest.TestCase):
    """The field must be an inverse-square acceleration toward the origin."""

    def test_points_toward_the_origin(self):
        ax, ay, az = newtonian_gravity(MU)(
            (ORBIT_RADIUS, 0.0, 0.0, 0.0, 0.0, 0.0)
        )
        self.assertLess(ax, 0.0)
        self.assertEqual(ay, 0.0)
        self.assertEqual(az, 0.0)

    def test_magnitude_is_mu_over_r_squared(self):
        scale = 7.0e6
        ax, _, _ = newtonian_gravity(MU)((scale, 0.0, 0.0, 0.0, 0.0, 0.0))
        expected = MU / scale**2
        self.assertAlmostEqual(abs(ax), expected, delta=expected * 1e-12)

    def test_falls_off_with_the_inverse_square(self):
        near, _, _ = newtonian_gravity(MU)((7.0e6, 0.0, 0.0, 0.0, 0.0, 0.0))
        far, _, _ = newtonian_gravity(MU)((14.0e6, 0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(near / far, 4.0, places=9)

    def test_acceleration_follows_the_position_vector(self):
        field = newtonian_gravity(MU)
        ax, ay, az = field((0.0, ORBIT_RADIUS, 0.0, 0.0, 0.0, 0.0))
        self.assertLess(ay, 0.0)
        self.assertEqual(ax, 0.0)
        self.assertEqual(az, 0.0)


class GravityFieldAgreementTests(unittest.TestCase):
    """The constant field must reproduce the legacy scalar-gravity derivatives."""

    def test_constant_field_matches_scalar_derivatives(self):
        state = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
        self.assertEqual(
            derivatives(state, 0.01, gravity=9.81),
            derivatives_with_gravity(state, 0.01, constant_gravity(9.81)),
        )

    def test_constant_field_defaults_to_the_profile_gravity(self):
        self.assertEqual(
            constant_gravity()((0, 0, 0, 0, 0, 0)),
            (0.0, -9.81, 0.0),
        )


class CircularOrbitTests(unittest.TestCase):
    """A circular orbit must stay circular under RK4 with the Newtonian field."""

    def _orbit(self, dt, periods=1.0):
        speed = math.sqrt(MU / ORBIT_RADIUS)
        period = 2 * math.pi * ORBIT_RADIUS / speed
        state = (ORBIT_RADIUS, 0.0, 0.0, 0.0, speed, 0.0)
        simulator = ProjectileSimulator.from_state(
            state,
            {'max_time': period * periods, 'drag_coefficient': 0.0},
            dt,
            adaptive=True,
            gravity_model=newtonian_gravity(MU),
            ground_collision=False,
        )
        radii = []
        simulator.run_simulation(
            on_step=lambda t, s: radii.append(math.hypot(s[X], s[Y], s[Z]))
        )
        return simulator, radii, period

    def test_radius_stays_near_constant(self):
        _, radii, _ = self._orbit(dt=0.5)
        reference = radii[0]
        for radius in radii:
            self.assertLess(abs(radius - reference) / reference, 1e-4)

    def test_returns_near_the_start_after_one_period(self):
        simulator, _, _ = self._orbit(dt=0.5)
        x, y = simulator.state[X], simulator.state[Y]
        self.assertLess(abs(y), 1e3)
        self.assertAlmostEqual(math.hypot(x, y), ORBIT_RADIUS, delta=1e3)

    def test_runs_until_the_time_limit_without_landing(self):
        simulator, _, _ = self._orbit(dt=1.0)
        self.assertTrue(simulator.timed_out)
        self.assertFalse(simulator.landed)


class EllipticalOrbitTests(unittest.TestCase):
    """An eccentric orbit must close on itself and keep its elements."""

    PERIAPSIS = 7.0e6
    APOAPSIS = 42.0e6

    def _elements(self):
        semi_major = (self.PERIAPSIS + self.APOAPSIS) / 2.0
        eccentricity = (self.APOAPSIS - self.PERIAPSIS) / (
            self.APOAPSIS + self.PERIAPSIS
        )
        speed = math.sqrt(MU * (2.0 / self.PERIAPSIS - 1.0 / semi_major))
        state = (self.PERIAPSIS, 0.0, 0.0, 0.0, speed, 0.0)
        return state, semi_major, eccentricity

    def test_apsides_match_the_elements(self):
        state, semi_major, _ = self._elements()
        period = 2.0 * math.pi * math.sqrt(semi_major**3 / MU)
        simulator = ProjectileSimulator.from_state(
            state,
            {'max_time': period * 1.05, 'drag_coefficient': 0.0},
            dt=0.5,
            gravity_model=newtonian_gravity(MU),
            ground_collision=False,
        )
        radii = []
        simulator.run_simulation(
            on_step=lambda t, s: radii.append(math.hypot(s[X], s[Y], s[Z]))
        )

        self.assertAlmostEqual(min(radii), self.PERIAPSIS, delta=1e3)
        self.assertAlmostEqual(max(radii), self.APOAPSIS, delta=1e3)

    def test_elements_are_conserved_along_the_arc(self):
        state, _, _ = self._elements()
        initial = orbital_elements(state, MU)
        quarter_period = 0.25 * 2.0 * math.pi * math.sqrt(
            initial.semi_major_axis**3 / MU
        )
        simulator = ProjectileSimulator.from_state(
            state,
            {'max_time': quarter_period, 'drag_coefficient': 0.0},
            dt=0.5,
            gravity_model=newtonian_gravity(MU),
            ground_collision=False,
        )
        simulator.run_simulation()
        current = orbital_elements(simulator.state, MU)

        self.assertAlmostEqual(
            current.semi_major_axis, initial.semi_major_axis, delta=1e3
        )
        self.assertAlmostEqual(current.eccentricity, initial.eccentricity, places=6)


class FromStateTests(unittest.TestCase):
    """``from_state`` must let a run start from an arbitrary state vector."""

    def test_sets_both_initial_and_current_state(self):
        state = (ORBIT_RADIUS, 0.0, 0.0, 0.0, 7546.0, 0.0)
        simulator = ProjectileSimulator.from_state(state)
        self.assertEqual(simulator.initial_state, state)
        self.assertEqual(simulator.state, state)

    def test_defaults_to_the_flat_earth_field(self):
        simulator = ProjectileSimulator.from_state((0.0, 10.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(simulator.gravity_model((0, 0, 0, 0, 0, 0)), (0.0, -9.81, 0.0))


class OrbitalElementTests(unittest.TestCase):
    """The element solver must reproduce closed-form values."""

    def test_circular_orbit_elements(self):
        speed = math.sqrt(MU / ORBIT_RADIUS)
        state = (ORBIT_RADIUS, 0.0, 0.0, 0.0, speed, 0.0)
        elements = orbital_elements(state, MU)

        self.assertAlmostEqual(elements.eccentricity, 0.0, places=12)
        self.assertAlmostEqual(elements.semi_major_axis, ORBIT_RADIUS, places=6)
        self.assertAlmostEqual(elements.periapsis, ORBIT_RADIUS, places=6)
        self.assertAlmostEqual(elements.apoapsis, ORBIT_RADIUS, places=6)
        self.assertAlmostEqual(
            elements.period,
            2.0 * math.pi * math.sqrt(ORBIT_RADIUS**3 / MU),
            places=6,
        )
        self.assertAlmostEqual(elements.specific_energy, -MU / (2 * ORBIT_RADIUS))
        self.assertAlmostEqual(elements.inclination_rad, 0.0, places=12)

    def test_elliptical_orbit_elements(self):
        periapsis = 7.0e6
        apoapsis = 42.0e6
        semi_major_axis = (periapsis + apoapsis) / 2.0
        eccentricity = (apoapsis - periapsis) / (apoapsis + periapsis)
        speed = math.sqrt(MU * (2.0 / periapsis - 1.0 / semi_major_axis))
        state = (periapsis, 0.0, 0.0, 0.0, speed, 0.0)
        elements = orbital_elements(state, MU)

        self.assertAlmostEqual(elements.eccentricity, eccentricity, places=12)
        self.assertAlmostEqual(elements.semi_major_axis, semi_major_axis, places=3)
        self.assertAlmostEqual(elements.periapsis, periapsis, places=3)
        self.assertAlmostEqual(elements.apoapsis, apoapsis, places=3)
        self.assertAlmostEqual(
            elements.period,
            2.0 * math.pi * math.sqrt(semi_major_axis**3 / MU),
            places=3,
        )

    def test_inclination_follows_the_orbit_plane(self):
        for inclination_deg in (0.0, 30.0, 63.4, 90.0):
            with self.subTest(inclination_deg=inclination_deg):
                inclination_rad = math.radians(inclination_deg)
                speed = math.sqrt(MU / ORBIT_RADIUS)
                state = (
                    ORBIT_RADIUS,
                    0.0,
                    0.0,
                    0.0,
                    speed * math.cos(inclination_rad),
                    speed * math.sin(inclination_rad),
                )
                elements = orbital_elements(state, MU)
                self.assertAlmostEqual(
                    elements.inclination_rad, inclination_rad, places=9
                )

    def test_hyperbolic_orbit_has_no_apoapsis_or_period(self):
        speed = 1.5 * math.sqrt(2.0 * MU / ORBIT_RADIUS)
        state = (ORBIT_RADIUS, 0.0, 0.0, 0.0, speed, 0.0)
        elements = orbital_elements(state, MU)
        self.assertGreater(elements.eccentricity, 1.0)
        self.assertIsNone(elements.apoapsis)
        self.assertIsNone(elements.period)
        self.assertGreater(elements.specific_energy, 0.0)

    def test_rejects_the_central_body_and_non_positive_mu(self):
        with self.assertRaises(ValueError):
            orbital_elements((0.0, 0.0, 0.0, 0.0, 0.0, 0.0), MU)
        with self.assertRaises(ValueError):
            orbital_elements((ORBIT_RADIUS, 0.0, 0.0, 0.0, 1.0, 0.0), 0.0)


class J2GravityFieldTests(unittest.TestCase):
    """j2_gravity adds an oblateness term that vanishes at j2 = 0."""

    def test_zero_j2_reproduces_the_newtonian_field(self):
        base = newtonian_gravity(MU)
        flat = j2_gravity(MU, 0.0)
        state = (ORBIT_RADIUS, 1.0e6, 2.0e6, 100.0, -50.0, 10.0)
        for got, expected in zip(flat(state), base(state)):
            self.assertAlmostEqual(got, expected, places=12)

    def test_equatorial_gravity_weakens_relative_to_point_mass(self):
        base = newtonian_gravity(MU)((ORBIT_RADIUS, 0.0, 0.0, 0.0, 0.0, 0.0))
        perturbed = j2_gravity(MU)((ORBIT_RADIUS, 0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertLess(perturbed[X], base[X])

    def test_polar_gravity_strengthens_relative_to_point_mass(self):
        base = newtonian_gravity(MU)((0.0, 0.0, ORBIT_RADIUS, 0.0, 0.0, 0.0))
        perturbed = j2_gravity(MU)((0.0, 0.0, ORBIT_RADIUS, 0.0, 0.0, 0.0))
        self.assertGreater(perturbed[Z], base[Z])

    def test_defaults_use_the_earth_constants(self):
        state = (EQUATORIAL_RADIUS_EARTH, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(j2_gravity(MU)(state), j2_gravity(MU, J2_EARTH)(state))


class SumFieldsTests(unittest.TestCase):
    """sum_fields composes acceleration fields componentwise."""

    def test_empty_sum_is_zero(self):
        self.assertEqual(sum_fields()((1.0, 2.0, 3.0, 0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))

    def test_single_field_is_unchanged(self):
        field = newtonian_gravity(MU)
        state = (ORBIT_RADIUS, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(sum_fields(field)(state), field(state))

    def test_two_fields_add_componentwise(self):
        a = newtonian_gravity(MU)
        b = newtonian_gravity(MU / 4)
        combined = sum_fields(a, b)
        state = (ORBIT_RADIUS, 1.0e6, 0.0, 0.0, 0.0, 0.0)
        got = combined(state)
        expected = tuple(
            component_a + component_b
            for component_a, component_b in zip(a(state), b(state))
        )
        for actual, wanted in zip(got, expected):
            self.assertAlmostEqual(actual, wanted, places=9)


class DensityModelTests(unittest.TestCase):
    """The atmosphere densities are positive, monotonic, and floor at altitude."""

    def test_constant_density_ignores_altitude(self):
        model = constant_density(1.2)
        self.assertEqual(model(0.0), 1.2)
        self.assertEqual(model(50000.0), 1.2)

    def test_exponential_density_matches_the_closed_form(self):
        model = exponential_density(1.225, 8500.0)
        self.assertAlmostEqual(model(0.0), 1.225, places=12)
        self.assertAlmostEqual(model(8500.0), 1.225 / math.e, places=9)
        self.assertGreater(model(0.0), model(10000.0))
        self.assertGreater(model(10000.0), model(50000.0))

    def test_exponential_density_needs_a_positive_scale_height(self):
        with self.assertRaises(ValueError):
            exponential_density(1.225, 0.0)

    def test_tabulated_density_decreases_with_altitude(self):
        model = tabulated_density(EARTH_ATMOSPHERE_LAYERS)
        self.assertGreater(model(0.0), model(50000.0))
        self.assertGreater(model(50000.0), model(200000.0))
        self.assertGreater(model(200000.0), model(1000000.0))

    def test_tabulated_density_selects_the_layer_below(self):
        model = tabulated_density(EARTH_ATMOSPHERE_LAYERS)
        base, rho, scale = EARTH_ATMOSPHERE_LAYERS[3]
        self.assertEqual(model(base), rho)
        self.assertAlmostEqual(
            model(base + scale), rho / math.e, places=15
        )

    def test_tabulated_density_rejects_bad_tables(self):
        with self.assertRaises(ValueError):
            tabulated_density(())
        with self.assertRaises(ValueError):
            tabulated_density(((0.0, 1.225, 0.0),))
        with self.assertRaises(ValueError):
            tabulated_density(((0.0, -1.0, 100.0),))


class DragModelTests(unittest.TestCase):
    """The drag fields match the legacy scalar term and oppose the velocity."""

    def setUp(self):
        self.state = (10.0, 20.0, 30.0, 40.0, -25.0, 5.0)
        self.gravity = constant_gravity(9.81)

    def test_constant_drag_matches_the_scalar_term(self):
        k = 0.0037
        modelled = derivatives_with_models(
            self.state, self.gravity, constant_drag(k)
        )
        legacy = derivatives(self.state, k, 9.81)
        for got, expected in zip(modelled, legacy):
            self.assertAlmostEqual(got, expected, places=12)

    def test_absent_drag_matches_the_drag_free_field(self):
        modelled = derivatives_with_models(self.state, self.gravity)
        legacy = derivatives_with_gravity(self.state, 0.0, self.gravity)
        self.assertEqual(modelled, legacy)

    def test_constant_drag_opposes_the_velocity(self):
        ax, ay, az = constant_drag(0.01)(self.state)
        self.assertLess(ax, 0.0)
        self.assertGreater(ay, 0.0)
        self.assertLess(az, 0.0)

    def test_atmospheric_drag_scales_with_density(self):
        parameters = coerce_parameters({})
        dry = atmospheric_drag(parameters, constant_density(0.0), flat_altitude())
        thick = atmospheric_drag(parameters, constant_density(1.0), flat_altitude())
        self.assertEqual(dry(self.state), (0.0, 0.0, 0.0))
        self.assertLess(thick(self.state)[0], 0.0)

    def test_orbital_altitude_uses_radius(self):
        altitude = orbital_altitude(EQUATORIAL_RADIUS_EARTH)
        state = (EQUATORIAL_RADIUS_EARTH + 200000.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(altitude(state), 200000.0, places=6)
        self.assertAlmostEqual(flat_altitude()(state), 0.0, places=12)


if __name__ == '__main__':
    unittest.main()
