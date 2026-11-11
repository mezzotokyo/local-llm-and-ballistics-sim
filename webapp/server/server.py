#!/usr/bin/env python3
"""JSON API for the projectile simulator, built on the standard library only.

The server reuses the tested physics in ``range_calculator`` (``ballistics`` and
``physics_config``) instead of re-implementing it. It exposes three endpoints on
top of that core (two read-only GET and one POST):

    GET  /api/health    liveness probe
    GET  /api/config    built-in defaults for the launch scenario
    POST /api/simulate  run one launch and return the summary plus trajectory

Run it with::

    python3 webapp/server/server.py --port 8000

The response is JSON; ``Access-Control-Allow-Origin`` is permissive so the Vite
dev server can talk to it directly (a dev proxy is also configured, so CORS is
not strictly required).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RANGE_CALCULATOR = REPO_ROOT / "range_calculator"
if str(RANGE_CALCULATOR) not in sys.path:
    sys.path.insert(0, str(RANGE_CALCULATOR))

from ballistics import (  # noqa: E402
    EARTH_ATMOSPHERE_LAYERS,
    ProjectileSimulator,
    SimulationDiverged,
    atmospheric_drag,
    exponential_density,
    flat_altitude,
    j2_gravity,
    magnus_lift,
    newtonian_gravity,
    orbital_altitude,
    tabulated_density,
)
from orbital import orbital_elements  # noqa: E402
from physics_config import DEFAULT_PARAMETERS, coerce_parameters  # noqa: E402

KMPH_TO_MPS = 1000 / 3600

DEFAULT_VELOCITY_KMPH = 170.0
DEFAULT_ANGLE_DEG = 35.0
DEFAULT_TIMESTEP = 0.01

PARAMETER_FIELDS = (
    "max_time",
    "gravity",
    "mu",
    "j2",
    "equatorial_radius",
    "scale_height",
    "sea_level_density",
    "air_density",
    "mass",
    "diameter",
    "drag_coefficient",
)

GRAVITY_MODELS = ("constant", "newtonian", "j2")
DRAG_MODELS = ("constant", "exponential", "tabulated")

# Closed orbits are integrated for one full period times this margin, so the
# trajectory visibly closes instead of stopping after the projectile max_time.
ORBITAL_PERIOD_MARGIN = 1.05

# Upper bound on the number of integration steps for one orbit. A full period at
# the projectile dt (0.01 s) would need ~600k steps (~30 s of wall time), so the
# orbital timestep is raised to ``period / this`` when the caller asks for finer.
MAX_ORBITAL_STEPS = 4000

MAX_TRAJECTORY_POINTS = 2000

_TOO_COARSE_RE = re.compile(
    r"timestep dt=(?P<dt>\S+) is too coarse: an upward launch reached the "
    r"ground within the first step\. Reduce dt below (?P<stable>\S+)\."
)


class BadRequest(ValueError):
    """Raised when the request payload cannot be turned into a scenario."""


def localize_error(message: str) -> str:
    """Translate the physics core's timestep errors into Japanese for the UI.

    The core (:mod:`ballistics`) keeps its messages in English because they are
    asserted by the unit tests. This adapter is the presentation boundary, so
    only user-facing timestep failures are rewritten here; anything that does not
    match a known pattern is returned unchanged.
    """
    match = _TOO_COARSE_RE.search(message)
    if match:
        return (
            f"刻み幅 dt={match['dt']} は粗すぎます。上方向への発射が最初のステップで"
            f"地面に到達しました。dt を {match['stable']} 未満にしてください。"
        )
    if "non-finite state" in message:
        return (
            "刻み幅 dt が大きすぎて計算が発散しました（非有限値）。"
            "dt を小さくしてください。"
        )
    if "more than" in message and "launch speed" in message:
        return (
            "刻み幅 dt が大きすぎて計算速度が発散しました。dt を小さくしてください。"
        )
    return message


def _number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequest(f"{key} must be a number")
    if not math.isfinite(value):
        raise BadRequest(f"{key} must be finite")
    return float(value)


def _boolean(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise BadRequest(f"{key} must be a boolean")
    return value


def _parameter_overrides(payload: dict[str, Any]) -> dict[str, float] | None:
    raw = payload.get("parameters")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BadRequest("parameters must be an object")
    unknown = set(raw) - set(PARAMETER_FIELDS)
    if unknown:
        raise BadRequest(f"unknown parameters: {sorted(unknown)}")
    return {key: _number(raw, key, 0.0) for key in raw}


def _gravity_model_name(payload: dict[str, Any]) -> str:
    value = payload.get("gravity_model", "constant")
    if not isinstance(value, str):
        raise BadRequest("gravity_model must be a string")
    if value not in GRAVITY_MODELS:
        raise BadRequest(f"unknown gravity_model: {value!r}")
    return value


def _drag_model_name(payload: dict[str, Any]) -> str:
    value = payload.get("drag_model", "constant")
    if not isinstance(value, str):
        raise BadRequest("drag_model must be a string")
    if value not in DRAG_MODELS:
        raise BadRequest(f"unknown drag_model: {value!r}")
    return value


def _initial_state(payload: dict[str, Any]) -> tuple[float, ...]:
    raw = payload.get("initial_state")
    if raw is None:
        raise BadRequest("initial_state is required for newtonian gravity")
    if not isinstance(raw, list) or len(raw) != 6:
        raise BadRequest("initial_state must be a list of 6 numbers")
    state: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BadRequest("initial_state must be a list of 6 numbers")
        if not math.isfinite(value):
            raise BadRequest("initial_state must be finite")
        state.append(float(value))
    return tuple(state)


def simulate(payload: dict[str, Any]) -> dict[str, Any]:
    velocity_kmph = _number(payload, "velocity_kmph", DEFAULT_VELOCITY_KMPH)
    angle_deg = _number(payload, "angle_deg", DEFAULT_ANGLE_DEG)
    dt = _number(payload, "dt", DEFAULT_TIMESTEP)
    adaptive = _boolean(payload, "adaptive", False)
    spin_rate_rpm = _number(payload, "spin_rate", 0.0)
    spin_axis_deg = _number(payload, "spin_axis_angle", 0.0)
    if dt <= 0.0:
        raise BadRequest("dt must be greater than 0")

    constants = _parameter_overrides(payload)
    profile = coerce_parameters(constants)
    gravity_model_name = _gravity_model_name(payload)
    drag_model_name = _drag_model_name(payload)
    orbital = gravity_model_name in ("newtonian", "j2")

    if gravity_model_name == "j2":
        gravity_model = j2_gravity(
            profile.mu, profile.j2, profile.equatorial_radius
        )
    elif gravity_model_name == "newtonian":
        gravity_model = newtonian_gravity(profile.mu)
    else:
        gravity_model = None

    drag_model = None
    if drag_model_name != "constant":
        if orbital:
            altitude = orbital_altitude(profile.equatorial_radius)
        else:
            altitude = flat_altitude()
        if drag_model_name == "exponential":
            density = exponential_density(
                profile.sea_level_density, profile.scale_height
            )
        else:
            density = tabulated_density(EARTH_ATMOSPHERE_LAYERS)
        drag_model = atmospheric_drag(profile, density, altitude)

    if orbital:
        state = _initial_state(payload)
        mu = profile.mu
        span = None
        elements = orbital_elements(state, mu)
        if elements.period is not None:
            span = elements.period * ORBITAL_PERIOD_MARGIN
            if "max_time" not in (constants or {}):
                constants = {**(constants or {}), "max_time": span}
                profile = coerce_parameters(constants)
        orbital_dt = dt
        if span is not None:
            orbital_dt = max(dt, span / MAX_ORBITAL_STEPS)
        simulator = ProjectileSimulator.from_state(
            state,
            constants,
            orbital_dt,
            adaptive=adaptive,
            gravity_model=gravity_model,
            drag_model=drag_model,
            ground_collision=False,
        )
    else:
        mu = None
        lift_model = None
        if spin_rate_rpm != 0.0:
            lift_model = magnus_lift(profile, spin_rate_rpm, spin_axis_deg)
        simulator = ProjectileSimulator(
            velocity_kmph * KMPH_TO_MPS,
            math.radians(angle_deg),
            constants,
            dt=dt,
            adaptive=adaptive,
            drag_model=drag_model,
            lift_model=lift_model,
        )

    trajectory: list[dict[str, float]] = []

    def record(t: float, state: tuple[float, float, float, float, float, float]) -> None:
        x, y, z, vx, vy, vz = state
        trajectory.append(
            {"t": t, "x": x, "y": y, "z": z, "vx": vx, "vy": vy,
             "speed": math.hypot(vx, vy, vz)}
        )

    ideal_range = None if orbital else simulator.calculate_ideal_range()
    ground_range, flight_time = simulator.run_simulation(on_step=record)
    result = simulator.result()

    elements = None
    if orbital:
        computed = orbital_elements(simulator.state, mu)
        elements = {
            "specific_energy": computed.specific_energy,
            "semi_major_axis": computed.semi_major_axis,
            "eccentricity": computed.eccentricity,
            "periapsis": computed.periapsis,
            "apoapsis": computed.apoapsis,
            "period": computed.period,
            "inclination_deg": math.degrees(computed.inclination_rad),
        }

    return {
        "input": {
            "velocity_kmph": velocity_kmph,
            "angle_deg": angle_deg,
            "dt": dt,
            "adaptive": adaptive,
            "gravity_model": gravity_model_name,
            "drag_model": drag_model_name,
            "spin_rate": spin_rate_rpm,
            "spin_axis_angle": spin_axis_deg,
        },
        "result": {
            "ideal_range": ideal_range,
            "ground_range": ground_range,
            "lateral_range": result.lateral_range,
            "flight_time": flight_time,
            "impact_speed": result.impact_speed,
            "landed": result.landed,
            "timed_out": result.timed_out,
            "steps": result.steps,
            "timestep_min": result.timestep_min,
            "timestep_max": result.timestep_max,
        },
        "orbital": elements,
        "trajectory": _downsample(trajectory, MAX_TRAJECTORY_POINTS),
    }


def _downsample(points: list[dict[str, float]], limit: int) -> list[dict[str, float]]:
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def default_config() -> dict[str, Any]:
    return {
        "defaults": {
            "velocity_kmph": DEFAULT_VELOCITY_KMPH,
            "angle_deg": DEFAULT_ANGLE_DEG,
            "dt": DEFAULT_TIMESTEP,
            "adaptive": False,
            "gravity_model": "constant",
            "drag_model": "constant",
            "spin_rate": 0.0,
            "spin_axis_angle": 0.0,
        },
        "parameters": {
            field: getattr(DEFAULT_PARAMETERS, field) for field in PARAMETER_FIELDS
        },
        "gravity_models": list(GRAVITY_MODELS),
        "drag_models": list(DRAG_MODELS),
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "RangeCalcAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"[api] {self.address_string()} {format % args}\n")

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/api/config":
            self._send_json(200, default_config())
        else:
            self._send_json(404, {"error": f"not found: {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/simulate":
            self._send_json(404, {"error": f"not found: {path}"})
            return
        try:
            payload = self._read_json()
            self._send_json(200, simulate(payload))
        except (TypeError, ValueError) as exc:
            # BadRequest is a ValueError subclass, so malformed input and
            # validation failures share the same 400 response.
            self._send_json(400, {"error": localize_error(str(exc))})
        except SimulationDiverged as exc:
            self._send_json(422, {"error": localize_error(str(exc))})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequest(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadRequest("request body must be a JSON object")
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Projectile simulator JSON API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    print(f"RangeCalc API listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
