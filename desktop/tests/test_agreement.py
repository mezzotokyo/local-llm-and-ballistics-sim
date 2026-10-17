"""Guard against drift between the desktop app and the web app.

The desktop app deliberately duplicates three things from ``webapp`` so that
each entry point stays self-contained:

* the Japanese error localisation (``webapp/server/server.py`` ``localize_error``)
* the drag-coefficient presets (``webapp/src/lib/sim.ts`` ``DRAG_PRESETS``)
* the simulate glue (``webapp/server/server.py`` ``simulate``)

These tests fail when one side changes without the other, which turns the
intentional duplication into a checked contract.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
import unittest
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DESKTOP_DIR.parent
SERVER_PATH = REPO_ROOT / "webapp" / "server" / "server.py"
APP_TSX_PATH = REPO_ROOT / "webapp" / "src" / "lib" / "sim.ts"

if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

import errors  # noqa: E402
import gui_model  # noqa: E402


def _load_web_server() -> object:
    """Import ``webapp/server/server.py`` under a private module name."""
    spec = importlib.util.spec_from_file_location("webapp_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SERVER = _load_web_server()

CANONICAL_ERRORS = (
    (
        "timestep dt=5 is too coarse: an upward launch reached the ground "
        "within the first step. Reduce dt below 1.24049."
    ),
    (
        "integration produced a non-finite state (0, 0, nan, 0); the timestep "
        "is too coarse for this scenario"
    ),
    (
        "integration produced a speed of 2.072e+22 m/s, more than 1000x the "
        "launch speed; the timestep is too coarse for this scenario"
    ),
    "some unrelated core failure",
)


class ErrorLocalizationAgreementTests(unittest.TestCase):
    def test_desktop_and_server_produce_identical_messages(self) -> None:
        for message in CANONICAL_ERRORS:
            with self.subTest(message=message):
                self.assertEqual(
                    errors.localize_error(message),
                    SERVER.localize_error(message),
                )

    def test_known_patterns_are_actually_translated(self) -> None:
        for message in CANONICAL_ERRORS[:-1]:
            with self.subTest(message=message):
                self.assertNotEqual(errors.localize_error(message), message)


class DragPresetAgreementTests(unittest.TestCase):
    def _parse_app_presets(self) -> tuple[tuple[float, str], ...]:
        text = APP_TSX_PATH.read_text(encoding="utf-8")
        default_match = re.search(
            r"DRAG_COEFFICIENT_DEFAULT\s*=\s*([0-9.]+)", text
        )
        self.assertIsNotNone(default_match, "DRAG_COEFFICIENT_DEFAULT not found")
        named = {"DRAG_COEFFICIENT_DEFAULT": default_match.group(1)}

        block_match = re.search(r"DRAG_PRESETS\s*=\s*\[(.*?)\]\s*as const", text, re.S)
        self.assertIsNotNone(block_match, "DRAG_PRESETS block not found")
        entry = re.compile(
            r"\{\s*value:\s*([A-Za-z0-9_.]+)\s*,\s*label:\s*'([^']*)'\s*\}"
        )
        presets = []
        for token, label in entry.findall(block_match.group(1)):
            value = float(named.get(token, token))
            presets.append((value, label))
        return tuple(presets)

    def test_desktop_presets_match_tsx(self) -> None:
        self.assertEqual(gui_model.DRAG_PRESETS, self._parse_app_presets())


class ConstantAgreementTests(unittest.TestCase):
    def test_scalar_constants_match(self) -> None:
        for name in (
            "KMPH_TO_MPS",
            "DEFAULT_VELOCITY_KMPH",
            "DEFAULT_ANGLE_DEG",
            "DEFAULT_TIMESTEP",
            "MAX_TRAJECTORY_POINTS",
        ):
            with self.subTest(name=name):
                self.assertEqual(getattr(gui_model, name), getattr(SERVER, name))

    def test_downsample_behaviour_matches(self) -> None:
        web_points = [{"i": i} for i in range(5000)]
        app_points = [
            gui_model.TrajectoryPoint(float(i), 0.0, 0.0, 0.0, 0.0, 0.0)
            for i in range(5000)
        ]
        web_sampled = SERVER._downsample(web_points, SERVER.MAX_TRAJECTORY_POINTS)
        app_sampled = gui_model._downsample(
            app_points, gui_model.MAX_TRAJECTORY_POINTS
        )
        self.assertEqual(len(web_sampled), len(app_sampled))
        self.assertIs(web_sampled[-1], web_points[-1])
        self.assertIs(app_sampled[-1], app_points[-1])

    def test_downsample_keeps_short_lists(self) -> None:
        web_points = [{"i": i} for i in range(10)]
        app_points = [
            gui_model.TrajectoryPoint(float(i), 0.0, 0.0, 0.0, 0.0, 0.0)
            for i in range(10)
        ]
        self.assertEqual(
            SERVER._downsample(web_points, SERVER.MAX_TRAJECTORY_POINTS),
            web_points,
        )
        self.assertEqual(
            gui_model._downsample(app_points, gui_model.MAX_TRAJECTORY_POINTS),
            app_points,
        )


class SimulateAgreementTests(unittest.TestCase):
    def test_reference_scenario_metrics_match(self) -> None:
        conditions = gui_model.LaunchConditions()
        desktop = gui_model.simulate(conditions).result
        web = SERVER.simulate(
            {
                "velocity_kmph": conditions.velocity_kmph,
                "angle_deg": conditions.angle_deg,
                "dt": conditions.dt,
                "adaptive": conditions.adaptive,
                "parameters": {
                    "drag_coefficient": conditions.drag_coefficient,
                },
            }
        )["result"]

        self.assertAlmostEqual(desktop.ideal_range, web["ideal_range"], places=9)
        self.assertAlmostEqual(desktop.ground_range, web["ground_range"], places=9)
        self.assertAlmostEqual(desktop.flight_time, web["flight_time"], places=9)
        self.assertAlmostEqual(desktop.impact_speed, web["impact_speed"], places=9)
        self.assertEqual(desktop.landed, web["landed"])
        self.assertEqual(desktop.timed_out, web["timed_out"])
        self.assertEqual(desktop.steps, web["steps"])
        self.assertTrue(
            math.isclose(desktop.timestep_min, web["timestep_min"], rel_tol=1e-12)
        )
        self.assertTrue(
            math.isclose(desktop.timestep_max, web["timestep_max"], rel_tol=1e-12)
        )


if __name__ == "__main__":
    unittest.main()
