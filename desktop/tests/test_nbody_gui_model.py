"""Headless unit tests for the desktop N-body window's pure logic.

The Tk widgets (:mod:`nbody_app`, :class:`trajectory_chart.NBodyChart`) are
exercised by launching the app; everything they depend on lives in
``gui_model`` / ``trajectory_chart`` and is tested here without a display.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1]
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

import errors  # noqa: E402
import gui_model  # noqa: E402
import trajectory_chart  # noqa: E402
from gui_model import NBodyConditions, NBodySpec  # noqa: E402

CIRCULAR_STATE = (1.0e6, 0.0, 0.0, 0.0, 1.0e3, 0.0)


def spec(
    name: str = "天体1",
    density: float = 1000.0,
    radius: float = 1.0,
    state=CIRCULAR_STATE,
) -> NBodySpec:
    return NBodySpec(name=name, density=density, radius=radius, state=state)


def sun_earth_conditions(
    dt: float = 3600.0, max_time: float | None = None
) -> NBodyConditions:
    """A Sun-centred system with Earth on a circular orbit, for the run tests."""
    sun = gui_model.nbody_preset_bodies("sun_centered")[0]
    earth = gui_model.nbody_catalog_spec("地球", sun.state, sun.mu, sun.radius)
    if max_time is None:
        max_time = 365.25 * 86400.0
    return NBodyConditions(bodies=(sun, earth), dt=dt, max_time=max_time)


class PresetTests(unittest.TestCase):
    def test_preset_values_and_labels(self) -> None:
        self.assertEqual(
            gui_model.NBODY_PRESETS,
            (
                ("sun_centered", "太陽を中心とした多体問題"),
                ("earth_centered", "地球を中心とした多体問題"),
                ("sun_earth_moon", "太陽・地球・月（3体）"),
            ),
        )

    def test_three_body_preset_places_the_moon_about_the_earth(self) -> None:
        conditions = gui_model.nbody_preset_conditions("sun_earth_moon")
        sun, earth, moon = conditions.bodies
        self.assertEqual([body.name for body in conditions.bodies], ["太陽", "地球", "月"])
        expected = gui_model.nbody_orbit_separation("月", earth.radius)
        self.assertAlmostEqual(
            math.dist(moon.state[:3], earth.state[:3]), expected
        )
        self.assertLess(math.dist(earth.state[:3], sun.state[:3]), 1.6e11)

    def test_three_body_preset_cancels_the_total_momentum(self) -> None:
        bodies = gui_model.nbody_preset_conditions("sun_earth_moon").bodies
        total_mu = sum(body.mu for body in bodies)
        for index in (3, 4, 5):
            momentum = sum(body.mu * body.state[index] for body in bodies) / total_mu
            self.assertAlmostEqual(momentum, 0.0, places=6)

    def test_three_body_preset_runs_and_conserves_energy(self) -> None:
        conditions = gui_model.nbody_preset_conditions("sun_earth_moon")
        self.assertIsNone(gui_model.validate_nbody_conditions(conditions))
        self.assertIsNone(gui_model.nbody_timestep_warning(conditions))
        outcome = gui_model.run_nbody(conditions)
        self.assertEqual(len(outcome.frames[0].positions), 3)
        self.assertLess(abs(outcome.energy_drift_percent), 1e-6)

    def test_presets_start_from_the_central_body_only(self) -> None:
        sun = gui_model.nbody_preset_bodies("sun_centered")
        earth = gui_model.nbody_preset_bodies("earth_centered")
        self.assertEqual([body.name for body in sun], ["太陽"])
        self.assertEqual([body.name for body in earth], ["地球"])
        for bodies in (sun, earth):
            body = bodies[0]
            with self.subTest(body=body.name):
                self.assertGreater(body.mu, 0.0)
                self.assertEqual(body.state, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def test_preset_conditions_validate_and_stay_within_the_step_budget(self) -> None:
        for value, _label in gui_model.NBODY_PRESETS:
            with self.subTest(preset=value):
                conditions = gui_model.nbody_preset_conditions(value)
                self.assertIsNone(gui_model.validate_nbody_conditions(conditions))
                self.assertLessEqual(
                    conditions.estimated_steps, gui_model.MAX_NBODY_STEPS
                )

    def test_sun_centered_preset_spans_one_earth_year(self) -> None:
        conditions = gui_model.nbody_preset_conditions("sun_centered")
        self.assertEqual(conditions.dt, gui_model.SUN_CENTERED_DT)
        self.assertEqual(conditions.max_time, gui_model.SUN_CENTERED_MAX_TIME)
        self.assertAlmostEqual(conditions.max_time / 86400.0, 365.25, delta=0.01)

    def test_earth_centered_preset_spans_one_lunar_period(self) -> None:
        conditions = gui_model.nbody_preset_conditions("earth_centered")
        self.assertEqual(conditions.dt, gui_model.EARTH_CENTERED_DT)
        self.assertAlmostEqual(conditions.max_time / 86400.0, 27.32, delta=0.1)

    def test_unknown_preset_raises(self) -> None:
        with self.assertRaises(ValueError):
            gui_model.nbody_preset_bodies("unknown")
        with self.assertRaises(ValueError):
            gui_model.nbody_preset_conditions("unknown")


class CircularOrbitTests(unittest.TestCase):
    def test_circular_state_uses_the_central_mu(self) -> None:
        central_mu = 3.986_004_418e14
        state = gui_model.nbody_circular_state(7.0e6, central_mu)
        self.assertEqual(state[:3], (7.0e6, 0.0, 0.0))
        self.assertEqual(state[3], 0.0)
        self.assertAlmostEqual(state[4], math.sqrt(central_mu / 7.0e6))
        self.assertGreater(state[4], 0.0)
        self.assertEqual(state[5], 0.0)

    def test_circular_state_rejects_a_non_positive_radius(self) -> None:
        for radius in (0.0, -1.0):
            with self.subTest(radius=radius):
                with self.assertRaises(ValueError):
                    gui_model.nbody_circular_state(radius, 1.0)

    def test_catalog_spec_seeds_density_radius_and_circular_speed(self) -> None:
        central_mu = gui_model.nbody_mu(1408.0, 695_700_000.0)
        _name, _primary, density, radius, orbit = next(
            entry for entry in gui_model.NBODY_CATALOG if entry[0] == "地球"
        )
        body = gui_model.nbody_catalog_spec(
            "地球", (0.0,) * 6, central_mu, 695_700_000.0
        )
        self.assertEqual(body.name, "地球")
        self.assertEqual(body.density, density)
        self.assertEqual(body.radius, radius)
        self.assertAlmostEqual(body.state[0], orbit)
        self.assertAlmostEqual(body.state[4], math.sqrt(central_mu / orbit))

    def test_catalog_spec_keeps_the_body_clear_of_the_centre(self) -> None:
        central_mu = gui_model.nbody_mu(1408.0, 695_700_000.0)
        # The Moon's default is its geocentric distance, inside the Sun's radius.
        min_separation = 7.0e8
        body = gui_model.nbody_catalog_spec(
            "月", (0.0,) * 6, central_mu, min_separation
        )
        self.assertGreaterEqual(body.state[0], min_separation)

    def test_catalog_spec_offsets_from_the_host_state(self) -> None:
        host = gui_model.nbody_preset_bodies("earth_centered")[0]
        host_state = (1.0e11, 2.0e10, 0.0, 0.0, 2.9e4, 0.0)
        satellite = gui_model.nbody_catalog_spec(
            gui_model.NBODY_SATELLITE, host_state, host.mu, host.radius, 400_000.0
        )
        # The satellite sits 400 km above the host, keeping its x velocity but
        # gaining the circular speed sqrt(mu / r) in +y.
        separation = host.radius + 400_000.0
        self.assertAlmostEqual(satellite.state[3], host_state[3])
        self.assertAlmostEqual(
            satellite.state[4],
            host_state[4] + math.sqrt(host.mu / separation),
        )
        self.assertAlmostEqual(satellite.state[0], host_state[0] + separation)

    def test_satellite_separation_uses_the_altitude_field(self) -> None:
        altitude = 550_000.0
        self.assertEqual(
            gui_model.nbody_orbit_separation(
                gui_model.NBODY_SATELLITE, 6_371_000.0, altitude
            ),
            6_371_000.0 + altitude,
        )
        # Without an altitude the catalogue default is used.
        self.assertEqual(
            gui_model.nbody_orbit_separation(gui_model.NBODY_SATELLITE, 6_371_000.0),
            6_371_000.0 + gui_model.NBODY_SATELLITE_ALTITUDE_DEFAULT,
        )

    def test_altitude_applies_to_any_body(self) -> None:
        # The Moon can be placed around Mars at a chosen height above its
        # surface, overriding the catalogue's geocentric distance.
        mars_radius = 3_389_500.0
        self.assertEqual(
            gui_model.nbody_orbit_separation("月", mars_radius, 1.0e8),
            mars_radius + 1.0e8,
        )

    def test_moon_about_mars_uses_the_altitude(self) -> None:
        mars_radius = 3_389_500.0
        mars_mu = gui_model.nbody_mu(3933.0, mars_radius)
        moon = gui_model.nbody_catalog_spec(
            "月", (0.0,) * 6, mars_mu, mars_radius, 1.0e8
        )
        separation = mars_radius + 1.0e8
        self.assertAlmostEqual(moon.state[0], separation)
        self.assertAlmostEqual(moon.state[4], math.sqrt(mars_mu / separation))


class CataloguePrimaryTests(unittest.TestCase):
    def test_natural_primaries(self) -> None:
        self.assertEqual(gui_model.nbody_catalog_primary("太陽"), "")
        self.assertEqual(gui_model.nbody_catalog_primary("地球"), "太陽")
        self.assertEqual(gui_model.nbody_catalog_primary("月"), "地球")
        self.assertEqual(
            gui_model.nbody_catalog_primary(gui_model.NBODY_SATELLITE), "地球"
        )

    def test_unknown_name_has_no_primary(self) -> None:
        self.assertEqual(gui_model.nbody_catalog_primary("未知"), "")
        self.assertEqual(gui_model.nbody_catalog_primary("天体3"), "")

    def test_orbit_separation_rejects_an_unknown_name(self) -> None:
        with self.assertRaises(KeyError):
            gui_model.nbody_orbit_separation("未知", 1.0)


class BodyCatalogTests(unittest.TestCase):
    # Measured GM values (m^3/s^2) used only to check the derived mu stays
    # close; the catalogue itself stores density and radius.
    MEASURED_MU = {
        "太陽": 1.327_124_400_18e20,
        "水星": 2.203_2e13,
        "金星": 3.248_585_92e14,
        "地球": 3.986_004_418e14,
        "月": 4.904_869_5e12,
        "火星": 4.282_837e13,
        "木星": 1.266_865_34e17,
        "土星": 3.793_118_7e16,
        "天王星": 5.793_939e15,
        "海王星": 6.836_529e15,
    }

    def test_catalog_is_the_sun_planets_moon_and_satellite(self) -> None:
        names = [entry[0] for entry in gui_model.NBODY_CATALOG]
        self.assertEqual(
            names,
            [
                "太陽", "水星", "金星", "地球", "月", "火星", "木星", "土星",
                "天王星", "海王星", gui_model.NBODY_SATELLITE,
            ],
        )
        self.assertEqual(len(names), len(set(names)))

    def test_catalog_entries_are_positive(self) -> None:
        for name, _primary, density, radius, value in gui_model.NBODY_CATALOG:
            with self.subTest(body=name):
                self.assertGreater(density, 0.0)
                self.assertGreater(radius, 0.0)
                self.assertGreater(value, 0.0)

    def test_derived_mu_matches_measured_values_closely(self) -> None:
        # Volume-mean density is an approximation; the GUI accepts a small
        # error against measured GM (see the module docstring in gui_model).
        for name, _primary, density, radius, _value in gui_model.NBODY_CATALOG:
            if name == gui_model.NBODY_SATELLITE:
                continue  # A point satellite has no measured GM.
            with self.subTest(body=name):
                mu = gui_model.nbody_mu(density, radius)
                expected = self.MEASURED_MU[name]
                self.assertLess(abs(mu - expected) / expected, 0.005)

    def test_default_orbital_radii_increase_outward(self) -> None:
        orbits = {entry[0]: entry[4] for entry in gui_model.NBODY_CATALOG}
        order = ["水星", "金星", "地球", "火星", "木星", "土星", "天王星", "海王星"]
        radii = [orbits[name] for name in order]
        self.assertEqual(radii, sorted(radii))
        # The Moon's default is its geocentric distance, inside the planets.
        self.assertLess(orbits["月"], orbits["水星"])

    def test_mu_formula(self) -> None:
        expected = gui_model.NBODY_G * 5514.0 * (4.0 / 3.0) * math.pi * 6_371_000.0**3
        self.assertEqual(gui_model.nbody_mu(5514.0, 6_371_000.0), expected)


class NumberParsingTests(unittest.TestCase):
    def test_accepts_plain_and_scientific_notation(self) -> None:
        self.assertEqual(gui_model.nbody_number("60", "刻み幅 dt"), 60.0)
        self.assertEqual(gui_model.nbody_number("3.986004418e14", "μ"), 3.986004418e14)

    def test_rejects_non_numeric_with_the_field_name(self) -> None:
        for bad in ("", "abc", "nan", "inf"):
            with self.subTest(text=bad):
                with self.assertRaises(ValueError) as caught:
                    gui_model.nbody_number(bad, "天体2 の vx")
                self.assertEqual(
                    str(caught.exception),
                    "天体2 の vx には数値を指定してください。",
                )


class ConditionsFromRowsTests(unittest.TestCase):
    def row(self, **overrides: str) -> tuple[str, ...]:
        values: dict[str, str] = {
            "name": "月",
            "density": "3344.0",
            "radius": "1737400.0",
            "x": "1.0",
            "y": "2.0",
            "z": "0.0",
            "vx": "0.0",
            "vy": "3.0",
            "vz": "0.0",
        }
        values.update(overrides)
        return (
            values["name"], values["density"], values["radius"],
            values["x"], values["y"], values["z"],
            values["vx"], values["vy"], values["vz"],
        )

    def test_parses_rows_into_conditions(self) -> None:
        conditions = gui_model.nbody_conditions_from_rows(
            [self.row()], "60", "1000"  # type: ignore[list-item]
        )
        self.assertEqual(conditions.dt, 60.0)
        self.assertEqual(conditions.max_time, 1000.0)
        body = conditions.bodies[0]
        self.assertEqual(body.name, "月")
        self.assertEqual(body.density, 3344.0)
        self.assertEqual(body.radius, 1737400.0)
        self.assertAlmostEqual(body.mu, gui_model.nbody_mu(3344.0, 1737400.0))
        self.assertEqual(body.state, (1.0, 2.0, 0.0, 0.0, 3.0, 0.0))

    def test_empty_name_falls_back_to_a_numbered_label(self) -> None:
        conditions = gui_model.nbody_conditions_from_rows(
            [self.row(name="   ")], "60", "1000"  # type: ignore[list-item]
        )
        self.assertEqual(conditions.bodies[0].name, "天体1")

    def test_parses_the_adaptive_flag(self) -> None:
        fixed = gui_model.nbody_conditions_from_rows(
            [self.row()], "60", "1000"  # type: ignore[list-item]
        )
        adaptive = gui_model.nbody_conditions_from_rows(
            [self.row()], "60", "1000", adaptive=True  # type: ignore[list-item]
        )
        self.assertFalse(fixed.adaptive)
        self.assertTrue(adaptive.adaptive)

    def test_rejects_an_empty_body_list(self) -> None:
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows([], "60", "1000")
        self.assertEqual(str(caught.exception), "天体を 1 つ以上指定してください。")

    def test_rejects_a_short_row(self) -> None:
        short = ("地球", "5514.0", "6371000.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows(
                [short], "60", "1000"  # type: ignore[list-item]
            )
        self.assertEqual(str(caught.exception), "天体1 の入力欄が不足しています。")

    def test_rejects_a_bad_state_field_naming_the_body_and_field(self) -> None:
        row = self.row(vx="fast")
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows(
                [row], "60", "1000"  # type: ignore[list-item]
            )
        self.assertEqual(
            str(caught.exception), "天体1 の vx には数値を指定してください。"
        )

    def test_rejects_a_bad_density_naming_the_field(self) -> None:
        row = self.row(density="dense")
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows(
                [row], "60", "1000"  # type: ignore[list-item]
            )
        self.assertEqual(
            str(caught.exception), "天体1 の体積密度 には数値を指定してください。"
        )

    def test_rejects_bad_timestep_and_time(self) -> None:
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows(
                [self.row()], "abc", "1000"  # type: ignore[list-item]
            )
        self.assertEqual(str(caught.exception), "刻み幅 dt には数値を指定してください。")
        with self.assertRaises(ValueError) as caught:
            gui_model.nbody_conditions_from_rows(
                [self.row()], "60", ""  # type: ignore[list-item]
            )
        self.assertEqual(str(caught.exception), "最大時間 には数値を指定してください。")


class ValidateConditionsTests(unittest.TestCase):
    def conditions(self, **overrides: object) -> NBodyConditions:
        values: dict = {"bodies": (spec(),), "dt": 60.0, "max_time": 100.0}
        values.update(overrides)
        return NBodyConditions(**values)  # type: ignore[arg-type]

    def test_accepts_a_reasonable_run(self) -> None:
        self.assertIsNone(gui_model.validate_nbody_conditions(self.conditions()))

    def test_rejects_non_positive_timestep(self) -> None:
        self.assertEqual(
            gui_model.validate_nbody_conditions(self.conditions(dt=0.0)),
            "刻み幅 dt は正の数で指定してください。",
        )
        self.assertEqual(
            gui_model.validate_nbody_conditions(self.conditions(dt=-1.0)),
            "刻み幅 dt は正の数で指定してください。",
        )

    def test_rejects_non_positive_max_time(self) -> None:
        self.assertEqual(
            gui_model.validate_nbody_conditions(self.conditions(max_time=0.0)),
            "最大時間は正の数で指定してください。",
        )

    def test_rejects_non_positive_density(self) -> None:
        message = gui_model.validate_nbody_conditions(
            self.conditions(bodies=(spec(density=0.0),))
        )
        self.assertEqual(message, "天体1 の体積密度は正の数で指定してください。")

    def test_rejects_non_positive_radius(self) -> None:
        message = gui_model.validate_nbody_conditions(
            self.conditions(bodies=(spec(radius=-1.0),))
        )
        self.assertEqual(message, "天体1 の半径は正の数で指定してください。")

    def test_rejects_a_run_over_the_step_budget(self) -> None:
        message = gui_model.validate_nbody_conditions(
            self.conditions(dt=1.0, max_time=float(gui_model.MAX_NBODY_STEPS + 1))
        )
        assert message is not None
        self.assertIn("推定ステップ数", message)
        self.assertIn("上限", message)
        self.assertIn(f"{gui_model.MAX_NBODY_STEPS:,}", message)

    def test_rejects_bodies_starting_at_the_same_position(self) -> None:
        twin = spec(name="天体2")
        message = gui_model.validate_nbody_conditions(
            self.conditions(bodies=(spec(), twin))
        )
        self.assertEqual(
            message,
            "天体1 と天体2 が同じ位置で開始します。"
            "重力が特異になるため開始できません。",
        )

    def test_rejects_an_adaptive_run_over_the_step_budget(self) -> None:
        # The adaptive limit tightens the step well below dt, so the estimate
        # still catches a run whose ceiling alone would have looked affordable.
        bodies = sun_earth_conditions().bodies
        message = gui_model.validate_nbody_conditions(
            NBodyConditions(
                bodies=bodies,
                dt=1.0e7,
                max_time=1.0e15,
                adaptive=True,
            )
        )
        assert message is not None
        self.assertIn("推定ステップ数", message)
        self.assertIn(f"{gui_model.MAX_NBODY_STEPS:,}", message)


class EstimatedStepsTests(unittest.TestCase):
    def test_single_body_uses_the_fixed_dt(self) -> None:
        conditions = NBodyConditions(bodies=(spec(),), dt=2.0, max_time=10.0)
        self.assertEqual(gui_model.nbody_estimated_steps(conditions), 5)

    def test_adaptive_uses_the_tightest_pair_limit(self) -> None:
        base = sun_earth_conditions()
        period = gui_model.nbody_shortest_pair_period(base)
        assert period is not None
        fixed = gui_model.NBodyConditions(
            bodies=base.bodies, dt=1.0e7, max_time=base.max_time
        )
        adaptive = gui_model.NBodyConditions(
            bodies=base.bodies,
            dt=1.0e7,
            max_time=base.max_time,
            adaptive=True,
        )
        # The coarse dt would need a handful of steps, but the adaptive limit
        # forces ADAPTIVE_STEPS_PER_PERIOD steps per Earth year.
        self.assertLess(gui_model.nbody_estimated_steps(fixed), 10)
        self.assertAlmostEqual(
            gui_model.nbody_estimated_steps(adaptive),
            gui_model.ADAPTIVE_STEPS_PER_PERIOD,
            delta=2,
        )


class TimestepWarningTests(unittest.TestCase):
    def test_single_body_has_no_pair_period_or_warning(self) -> None:
        conditions = NBodyConditions(bodies=(spec(),), dt=3600.0, max_time=1000.0)
        self.assertIsNone(gui_model.nbody_shortest_pair_period(conditions))
        self.assertIsNone(gui_model.nbody_timestep_warning(conditions))

    def test_sun_earth_pair_period_is_the_earth_year(self) -> None:
        period = gui_model.nbody_shortest_pair_period(sun_earth_conditions())
        assert period is not None
        self.assertAlmostEqual(period / 31_557_600.0, 1.0, delta=0.02)

    def test_adaptive_mode_never_warns(self) -> None:
        coarse = sun_earth_conditions()
        fixed = NBodyConditions(
            bodies=coarse.bodies, dt=1.0e7, max_time=coarse.max_time
        )
        adaptive = NBodyConditions(
            bodies=coarse.bodies,
            dt=1.0e7,
            max_time=coarse.max_time,
            adaptive=True,
        )
        self.assertIsNotNone(gui_model.nbody_timestep_warning(fixed))
        self.assertIsNone(gui_model.nbody_timestep_warning(adaptive))

    def test_adequate_timestep_does_not_warn(self) -> None:
        for preset in ("sun_centered", "earth_centered", "sun_earth_moon"):
            with self.subTest(preset=preset):
                conditions = gui_model.nbody_preset_conditions(preset)
                self.assertIsNone(gui_model.nbody_timestep_warning(conditions))

    def test_coarse_timestep_warns_about_the_tightest_pair(self) -> None:
        earth = gui_model.nbody_preset_bodies("earth_centered")[0]
        satellite = gui_model.nbody_catalog_spec(
            gui_model.NBODY_SATELLITE, earth.state, earth.mu, earth.radius, 400_000.0
        )
        # dt = 3600 s is far above a low Earth orbit's ~92 min period.
        conditions = NBodyConditions(
            bodies=(earth, satellite), dt=3600.0, max_time=86_400.0
        )
        warning = gui_model.nbody_timestep_warning(conditions)
        assert warning is not None
        self.assertIn("dt", warning)
        self.assertIn("周期", warning)


class RunNBodyTests(unittest.TestCase):
    """A Sun-centred two-body run, shared by the assertions below."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conditions = sun_earth_conditions()
        cls.outcome = gui_model.run_nbody(cls.conditions)

    def test_run_reaches_the_time_limit(self) -> None:
        outcome = self.outcome
        self.assertTrue(outcome.timed_out)
        self.assertAlmostEqual(
            outcome.elapsed_time, self.conditions.max_time, delta=self.conditions.dt
        )
        self.assertLessEqual(
            abs(outcome.steps - self.conditions.estimated_steps), 1
        )

    def test_frames_are_recorded_thinned_and_monotonic(self) -> None:
        frames = self.outcome.frames
        self.assertLessEqual(len(frames), gui_model.MAX_NBODY_FRAMES)
        self.assertGreater(len(frames), 1)
        self.assertEqual(frames[0].t, 0.0)
        self.assertTrue(
            all(a.t < b.t for a, b in zip(frames, frames[1:])),
            "frame times must strictly increase",
        )
        for frame in frames:
            self.assertEqual(len(frame.positions), 2)
            for position in frame.positions:
                self.assertEqual(len(position), 3)
                self.assertTrue(all(map(math.isfinite, position)))

    def test_energy_is_conserved_over_the_run(self) -> None:
        self.assertLess(abs(self.outcome.energy_drift_percent), 1e-9)

    def test_moon_around_earth_records_two_bodies(self) -> None:
        earth = gui_model.nbody_preset_bodies("earth_centered")[0]
        moon = gui_model.nbody_catalog_spec("月", earth.state, earth.mu, earth.radius)
        conditions = NBodyConditions(
            bodies=(earth, moon),
            dt=gui_model.EARTH_CENTERED_DT,
            max_time=gui_model.EARTH_CENTERED_MAX_TIME,
        )
        outcome = gui_model.run_nbody(conditions)
        self.assertTrue(outcome.timed_out)
        self.assertEqual(len(outcome.frames[0].positions), 2)
        self.assertLess(abs(outcome.energy_drift_percent), 1e-9)

    def test_invalid_conditions_are_rejected_before_integrating(self) -> None:
        bad = NBodyConditions(bodies=(spec(),), dt=0.0, max_time=10.0)
        with self.assertRaises(ValueError) as caught:
            gui_model.run_nbody(bad)
        self.assertEqual(str(caught.exception), "刻み幅 dt は正の数で指定してください。")


class AdaptiveRunTests(unittest.TestCase):
    @staticmethod
    def coarse_adaptive() -> NBodyConditions:
        base = sun_earth_conditions()
        return NBodyConditions(
            bodies=base.bodies,
            dt=1.0e7,
            max_time=base.max_time,
            adaptive=True,
        )

    def test_shortens_a_coarse_ceiling_and_finishes(self) -> None:
        conditions = self.coarse_adaptive()
        outcome = gui_model.run_nbody(conditions)
        self.assertTrue(outcome.timed_out)
        self.assertLessEqual(outcome.timestep_max, 1.0e7)
        self.assertLess(outcome.timestep_min, 1.0e7)
        self.assertLessEqual(
            abs(outcome.steps - gui_model.nbody_estimated_steps(conditions)), 2
        )
        self.assertLess(abs(outcome.energy_drift_percent), 1e-3)

    def test_metrics_report_the_shortest_step(self) -> None:
        outcome = gui_model.run_nbody(self.coarse_adaptive())
        rows = {
            key: (label, value)
            for key, label, value in gui_model.nbody_result_metrics(outcome)
        }
        label, value = rows["timestep"]
        self.assertEqual(label, "最短刻み")
        self.assertTrue(value.endswith(" s"))


class NBodyMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = gui_model.run_nbody(sun_earth_conditions())

    def test_metric_rows_match_the_placeholder_keys(self) -> None:
        default_keys = [row[0] for row in gui_model.DEFAULT_NBODY_METRIC_ROWS]
        metric_keys = [
            row[0] for row in gui_model.nbody_result_metrics(self.outcome)
        ]
        self.assertEqual(default_keys, metric_keys)

    def test_placeholder_rows_are_dashes(self) -> None:
        for _key, _label, value in gui_model.DEFAULT_NBODY_METRIC_ROWS:
            self.assertEqual(value, "-")

    def test_values_after_a_run(self) -> None:
        values = dict(
            (key, value)
            for key, _label, value in gui_model.nbody_result_metrics(self.outcome)
        )
        self.assertEqual(values["bodies"], "2")
        self.assertEqual(values["timed_out"], "yes")
        self.assertEqual(values["steps"], "8,766")
        self.assertTrue(values["timestep"].endswith(" s"))
        self.assertEqual(values["frames"], f"{len(self.outcome.frames):,}")
        # Elapsed shows comma-grouped seconds plus a days/hours/minutes form.
        self.assertIn("31,557,600.00 s", values["elapsed"])
        self.assertIn("365日6時間0分0秒", values["elapsed"])
        self.assertTrue(values["energy_drift"].endswith(" %"))


class NBodyErrorLocalisationTests(unittest.TestCase):
    """nbody.py messages that errors.py rewrites (desktop-only patterns)."""

    def test_minimum_separation_is_translated(self) -> None:
        message = (
            "bodies 0 and 1 are within the 1000000 m minimum separation "
            "(distance 5 m); a close encounter cannot be modelled as point masses"
        )
        localised = errors.localize_error(message)
        self.assertNotEqual(localised, message)
        self.assertIn("最小間隔", localised)

    def test_coincident_bodies_are_translated(self) -> None:
        message = (
            "bodies 0 and 1 occupy the same position; the mutual "
            "gravitational force is singular"
        )
        localised = errors.localize_error(message)
        self.assertNotEqual(localised, message)
        self.assertIn("同じ位置", localised)

    def test_initial_speed_divergence_is_translated(self) -> None:
        message = (
            "body 0 reached a speed of 2.072e+22 m/s, more than 1000x its "
            "initial speed; the timestep is too coarse for this scenario"
        )
        localised = errors.localize_error(message)
        self.assertNotEqual(localised, message)
        self.assertIn("刻み幅 dt が大きすぎて計算速度が発散", localised)

    def test_non_finite_state_uses_the_shared_pattern(self) -> None:
        message = (
            "body 0 reached a non-finite state (0, 0, nan, 0); the timestep "
            "is too coarse for this scenario"
        )
        localised = errors.localize_error(message)
        self.assertIn("非有限値", localised)


class EqualAspectDomainTests(unittest.TestCase):
    def test_empty_input_returns_a_unit_box(self) -> None:
        self.assertEqual(
            trajectory_chart.equal_aspect_domain([], [], 600, 400),
            (-1.0, 1.0, -1.0, 1.0),
        )

    def test_domain_contains_every_point(self) -> None:
        xs = [-3.0e8, 0.0, 4.0e8]
        ys = [-1.0e8, 2.0e8]
        x_lo, x_hi, y_lo, y_hi = trajectory_chart.equal_aspect_domain(
            xs, ys, 640, 480
        )
        self.assertLessEqual(x_lo, min(xs))
        self.assertGreaterEqual(x_hi, max(xs))
        self.assertLessEqual(y_lo, min(ys))
        self.assertGreaterEqual(y_hi, max(ys))

    def test_units_per_pixel_match_on_both_axes(self) -> None:
        x_lo, x_hi, y_lo, y_hi = trajectory_chart.equal_aspect_domain(
            [0.0, 1.0e6], [0.0, 5.0e5], 800, 300
        )
        self.assertAlmostEqual(
            (x_hi - x_lo) / 800, (y_hi - y_lo) / 300, places=9
        )

    def test_degenerate_points_still_produce_a_usable_domain(self) -> None:
        x_lo, x_hi, y_lo, y_hi = trajectory_chart.equal_aspect_domain(
            [5.0], [5.0], 640, 480
        )
        self.assertLess(x_lo, 5.0)
        self.assertGreater(x_hi, 5.0)
        self.assertLess(y_lo, 5.0)
        self.assertGreater(y_hi, 5.0)
        self.assertAlmostEqual(
            (x_hi - x_lo) / 640, (y_hi - y_lo) / 480, places=9
        )

    def test_padding_widens_the_domain_beyond_the_data(self) -> None:
        x_lo, x_hi, _y_lo, _y_hi = trajectory_chart.equal_aspect_domain(
            [0.0, 100.0], [0.0, 100.0], 640, 480, pad_fraction=0.10
        )
        self.assertLess(x_lo, 0.0)
        self.assertGreater(x_hi, 100.0)


if __name__ == "__main__":
    unittest.main()
