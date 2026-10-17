"""Tests for the JSON API's orbital wiring.

These exercise the pure ``simulate`` function directly (no HTTP socket), which
is where the gravity-model selection and element reporting live.
"""

from __future__ import annotations

import math
import unittest

import server
from physics_config import DEFAULT_PARAMETERS


class ConstantGravityTests(unittest.TestCase):
    """The default payload must keep the projectile behaviour untouched."""

    def test_default_request_has_no_orbital_block(self):
        response = server.simulate({})
        self.assertIsNone(response["orbital"])
        self.assertEqual(response["input"]["gravity_model"], "constant")
        self.assertIsNotNone(response["result"]["ideal_range"])
        self.assertGreater(len(response["trajectory"]), 0)

    def test_explicit_constant_model_matches_the_default(self):
        self.assertEqual(
            server.simulate({"gravity_model": "constant"})["result"],
            server.simulate({})["result"],
        )


class NewtonianGravityTests(unittest.TestCase):
    """Newtonian mode integrates a central-gravity orbit and reports elements."""

    def circular_payload(self, **overrides):
        radius = 7.0e6
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / radius)
        payload = {
            "gravity_model": "newtonian",
            "dt": 1.0,
            "parameters": {"drag_coefficient": 0.0},
            "initial_state": [radius, 0.0, 0.0, 0.0, speed, 0.0],
        }
        payload.update(overrides)
        return payload

    def test_circular_orbit_reports_closed_elements(self):
        response = server.simulate(self.circular_payload())
        elements = response["orbital"]
        self.assertIsNotNone(elements)
        self.assertEqual(response["input"]["gravity_model"], "newtonian")
        self.assertIsNone(response["result"]["ideal_range"])
        self.assertAlmostEqual(elements["eccentricity"], 0.0, places=6)
        self.assertAlmostEqual(elements["periapsis"], 7.0e6, places=0)
        self.assertAlmostEqual(elements["inclination_deg"], 0.0, places=9)
        self.assertAlmostEqual(
            elements["period"],
            2.0 * math.pi * math.sqrt(7.0e6**3 / DEFAULT_PARAMETERS.mu),
            places=0,
        )

    def test_newtonian_requires_an_initial_state(self):
        with self.assertRaises(server.BadRequest):
            server.simulate({"gravity_model": "newtonian"})

    def test_initial_state_must_be_six_numbers(self):
        for bad in ([1, 2, 3], [0, 0, 0, 0, 0, "x"]):
            with self.subTest(bad=bad):
                with self.assertRaises(server.BadRequest):
                    server.simulate(
                        {"gravity_model": "newtonian", "initial_state": bad}
                    )

    def test_unknown_gravity_model_is_rejected(self):
        with self.assertRaises(server.BadRequest):
            server.simulate({"gravity_model": "quantum"})


class J2GravityTests(unittest.TestCase):
    """The J2 model reduces to Newtonian at zero and perturbs a circular orbit."""

    def payload(self, **overrides):
        radius = 7.0e6
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / radius)
        payload = {
            "gravity_model": "j2",
            "dt": 1.0,
            "parameters": {"drag_coefficient": 0.0},
            "initial_state": [radius, 0.0, 0.0, 0.0, speed, 0.0],
        }
        payload.update(overrides)
        return payload

    def test_zero_j2_matches_newtonian(self):
        baseline = self.payload(
            gravity_model="newtonian", parameters={"drag_coefficient": 0.0}
        )
        flat = self.payload(parameters={"drag_coefficient": 0.0, "j2": 0.0})
        self.assertEqual(
            server.simulate(flat)["orbital"],
            server.simulate(baseline)["orbital"],
        )

    def test_oblateness_perturbs_the_circular_orbit(self):
        response = server.simulate(self.payload())
        self.assertEqual(response["input"]["gravity_model"], "j2")
        self.assertIsNone(response["result"]["ideal_range"])
        self.assertGreater(response["orbital"]["eccentricity"], 1e-4)


class DragModelTests(unittest.TestCase):
    """The atmosphere drag model is selectable and echoed back to the client."""

    def low_orbit_payload(self, **overrides):
        radius = DEFAULT_PARAMETERS.equatorial_radius + 200000.0
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / radius)
        payload = {
            "gravity_model": "newtonian",
            "drag_model": "tabulated",
            "dt": 5.0,
            "parameters": {"max_time": 60.0},
            "initial_state": [radius, 0.0, 0.0, 0.0, speed, 0.0],
        }
        payload.update(overrides)
        return payload

    def test_default_drag_model_is_constant(self):
        response = server.simulate(
            {
                "gravity_model": "newtonian",
                "parameters": {"drag_coefficient": 0.0},
                "initial_state": [7.0e6, 0, 0, 0, 7546.0, 0],
            }
        )
        self.assertEqual(response["input"]["drag_model"], "constant")

    def test_tabulated_drag_runs_and_is_reported(self):
        response = server.simulate(self.low_orbit_payload())
        self.assertEqual(response["input"]["drag_model"], "tabulated")
        self.assertIsNotNone(response["orbital"])

    def test_unknown_drag_model_is_rejected(self):
        with self.assertRaises(server.BadRequest):
            server.simulate({"drag_model": "magnus"})


class SpinTests(unittest.TestCase):
    """The Magnus force curves the flight when the spin axis is tilted."""

    def test_no_spin_has_no_lateral_deflection(self):
        response = server.simulate({})
        self.assertEqual(response["result"]["lateral_range"], 0.0)
        self.assertEqual(response["input"]["spin_rate"], 0.0)

    def test_sidespin_deflects_the_flight_sideways(self):
        response = server.simulate({"spin_rate": 2500.0, "spin_axis_angle": 90.0})
        self.assertGreater(response["result"]["lateral_range"], 0.0)
        self.assertEqual(response["input"]["spin_axis_angle"], 90.0)

    def test_trajectory_carries_the_lateral_coordinate(self):
        response = server.simulate({"spin_rate": 2500.0, "spin_axis_angle": 90.0})
        self.assertIn("z", response["trajectory"][0])
        self.assertGreater(response["trajectory"][-1]["z"], 0.0)


class OrbitalSpanTests(unittest.TestCase):
    """Closed orbits integrate one period; an explicit max_time still wins."""

    def circular_payload(self, **overrides):
        radius = 7.0e6
        speed = math.sqrt(DEFAULT_PARAMETERS.mu / radius)
        payload = {
            "gravity_model": "newtonian",
            "dt": 1.0,
            "parameters": {"drag_coefficient": 0.0},
            "initial_state": [radius, 0.0, 0.0, 0.0, speed, 0.0],
        }
        payload.update(overrides)
        return payload

    def test_closed_orbit_uses_one_period(self):
        response = server.simulate(self.circular_payload())
        period = 2.0 * math.pi * math.sqrt(7.0e6**3 / DEFAULT_PARAMETERS.mu)
        self.assertAlmostEqual(
            response["result"]["flight_time"],
            period * server.ORBITAL_PERIOD_MARGIN,
            delta=2.0,
        )
        self.assertTrue(response["result"]["timed_out"])

    def test_explicit_max_time_is_respected(self):
        response = server.simulate(
            self.circular_payload(
                parameters={"drag_coefficient": 0.0, "max_time": 60.0}
            )
        )
        self.assertLessEqual(response["result"]["flight_time"], 65.0)
        self.assertTrue(response["result"]["timed_out"])


class ConfigTests(unittest.TestCase):
    def test_config_exposes_mu_and_the_gravity_models(self):
        config = server.default_config()
        self.assertIn("mu", config["parameters"])
        self.assertIn("j2", config["parameters"])
        self.assertEqual(config["defaults"]["gravity_model"], "constant")
        self.assertEqual(config["defaults"]["drag_model"], "constant")


if __name__ == "__main__":
    unittest.main()
