"""Command line entry point: reads a launch scenario and prints the range.

Usage::

    python range_calc.py [scenario_path] [dt_max] [--adaptive] [--v0=<km/h>] [--angle=<deg>]
    python range_calc.py --spin=<rpm> [--spin-axis=<deg>] [--v0=<km/h>] [--angle=<deg>]
    python range_calc.py --orbital [--radius=<m>] [--v0=<km/h>] [--adaptive] [--j2] [--atmosphere]

``dt_max`` is a ceiling: with ``--adaptive`` each step is shortened to stay
inside the RK4 stability band, so a coarse value trades accuracy for stability
rather than diverging. ``--v0`` and ``--angle`` override the launch conditions
per field, falling back to the scenario file and then to the built-in
defaults. ``--spin`` adds a Magnus force from a ball spinning at the given rate;
``--spin-axis`` tilts the spin axis about the downrange axis (0 = backspin,
+90 = curve toward +z), which deflects the flight sideways.
``--orbital`` integrates a central-gravity orbit instead of a
surface projectile; the state starts on the +x axis at ``--radius`` with the
launch speed tangent to the orbit and the elements are printed afterwards.
``--j2`` adds the oblateness perturbation and ``--atmosphere`` enables the
piecewise-exponential drag decay (both default off).

All physics lives in :mod:`ballistics`; this module only handles input parsing,
unit conversion, and presentation.
"""

from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import NamedTuple

from ballistics import (
    EARTH_ATMOSPHERE_LAYERS,
    ProjectileSimulator,
    SimulationDiverged,
    atmospheric_drag,
    derivatives,
    ideal_range,
    j2_gravity,
    magnus_lift,
    newtonian_gravity,
    orbital_altitude,
    tabulated_density,
)
from orbital import orbital_elements
from physics_config import DEFAULT_PARAMETERS, ProjectileConstants, coerce_parameters

DATA_PATH = Path(__file__).resolve().parent / "data.csv"

DEFAULT_VELOCITY_KMPH = 170.0
DEFAULT_ANGLE_DEG = 35.0
DEFAULT_TIMESTEP = 0.01
DEFAULT_ORBITAL_RADIUS = 7.0e6

KMPH_TO_MPS = 1000 / 3600

__all__ = [
    "CliArgs",
    "ProjectileConstants",
    "ProjectileSimulator",
    "SimulationDiverged",
    "derivatives",
    "ideal_range",
    "load_scenario",
    "main",
    "orbital_elements",
    "parse_args",
]


class CliArgs(NamedTuple):
    """Parsed command line: scenario, timestep ceiling, mode, and launch inputs."""

    path: Path | str | None
    dt_max: float
    adaptive: bool
    v0_kmph: float | None
    angle_deg: float | None
    orbital: bool
    radius: float
    j2: bool = False
    atmosphere: bool = False
    spin_rpm: float = 0.0
    spin_axis_deg: float = 0.0


def load_scenario(
    path: Path | str | None = None,
    *,
    v0_kmph: float | None = None,
    angle_deg: float | None = None,
) -> tuple[float, float]:
    """Resolve ``velocity_kmph, angle_deg`` per field with fallback.

    Each field uses ``v0_kmph`` / ``angle_deg`` when provided, otherwise the
    scenario file, otherwise the built-in defaults. The file is read only when
    a field still needs it; a missing file, an unparsable number, or a short
    line resolves to the default instead of raising.
    """
    velocity = v0_kmph
    angle = angle_deg
    if velocity is None or angle is None:
        file_velocity, file_angle = _read_scenario(path)
        if velocity is None:
            velocity = file_velocity
        if angle is None:
            angle = file_angle
    return velocity, angle


def _read_scenario(path: Path | str | None) -> tuple[float, float]:
    """Read ``velocity_kmph, angle_deg`` and fall back to the defaults."""
    data_path = Path(path) if path is not None else DATA_PATH
    try:
        line = data_path.read_text(encoding="utf-8").splitlines()[0]
        velocity_raw, angle_raw = line.split(",")[:2]
        return float(velocity_raw.strip()), float(angle_raw.strip())
    except (OSError, IndexError, ValueError) as exc:
        warnings.warn(
            f"could not read scenario from {data_path} ({exc}); "
            f"using defaults {DEFAULT_VELOCITY_KMPH} km/h, {DEFAULT_ANGLE_DEG} deg",
            stacklevel=2,
        )
        return DEFAULT_VELOCITY_KMPH, DEFAULT_ANGLE_DEG


def parse_args(argv: list[str] | None = None) -> CliArgs:
    """Split ``argv`` into scenario, ceiling, mode, and launch inputs.

    Positional arguments are ``[scenario_path] [dt_max]``; ``--adaptive``
    switches the integrator to the adaptive-timestep mode. Launch conditions
    may be overridden with ``--v0=<km/h>`` and ``--angle=<deg>`` (equals form
    only); each field independently falls back to the scenario file and then
    to the built-in defaults. ``--orbital`` selects the central-gravity mode
    and ``--radius=<m>`` sets the initial orbit radius. An empty or omitted
    ``argv`` yields the shipped defaults, which is what ``main()`` relies on;
    the ``__main__`` block is what forwards the real command line.
    """
    args = list(argv or [])
    adaptive = _pop_flag(args, "--adaptive")
    orbital = _pop_flag(args, "--orbital")
    j2 = _pop_flag(args, "--j2")
    atmosphere = _pop_flag(args, "--atmosphere")

    v0: float | None = None
    angle: float | None = None
    radius: float | None = None
    spin_rpm = 0.0
    spin_axis = 0.0
    positional: list[str] = []
    for token in args:
        if token in ("--v0", "--angle", "--radius", "--spin", "--spin-axis"):
            raise SystemExit(
                f"error: {token} requires the equals form, e.g. {token}=170"
            )
        if token.startswith("--v0=") or token.startswith("--angle="):
            name, _, raw = token.partition("=")
            value = _parse_override(name, raw)
            if name == "--v0":
                if v0 is not None:
                    raise SystemExit("error: --v0 given more than once")
                v0 = value
            else:
                if angle is not None:
                    raise SystemExit("error: --angle given more than once")
                angle = value
            continue
        if token.startswith("--radius="):
            if radius is not None:
                raise SystemExit("error: --radius given more than once")
            radius = _parse_override("--radius", token.partition("=")[2])
            continue
        if token.startswith("--spin=") or token.startswith("--spin-axis="):
            name, _, raw = token.partition("=")
            value = _parse_override(name, raw)
            if name == "--spin":
                spin_rpm = value
            else:
                spin_axis = value
            continue
        positional.append(token)

    path: Path | str | None = None
    dt_max = DEFAULT_TIMESTEP
    for token in positional:
        if token == "":
            continue
        try:
            dt_max = float(token)
        except ValueError:
            if path is None:
                path = token
    return CliArgs(
        path=path,
        dt_max=dt_max,
        adaptive=adaptive,
        v0_kmph=v0,
        angle_deg=angle,
        orbital=orbital,
        radius=DEFAULT_ORBITAL_RADIUS if radius is None else radius,
        j2=j2,
        atmosphere=atmosphere,
        spin_rpm=spin_rpm,
        spin_axis_deg=spin_axis,
    )


def _pop_flag(args: list[str], flag: str) -> bool:
    """Remove ``flag`` from ``args`` in place and report whether it was present."""
    if flag in args:
        args.remove(flag)
        return True
    return False


def _parse_override(name: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(f"error: {name} expects a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise SystemExit(f"error: {name} expects a finite number, got {raw!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.orbital:
        return _run_orbital(args)

    velocity_kmph, angle_deg = load_scenario(
        args.path, v0_kmph=args.v0_kmph, angle_deg=args.angle_deg
    )

    velocity_mps = velocity_kmph * KMPH_TO_MPS
    angle_rad = math.radians(angle_deg)

    lift_model = None
    if args.spin_rpm != 0.0:
        lift_model = magnus_lift(
            DEFAULT_PARAMETERS, args.spin_rpm, args.spin_axis_deg
        )

    simulator = ProjectileSimulator(
        velocity_mps,
        angle_rad,
        DEFAULT_PARAMETERS,
        dt=args.dt_max,
        adaptive=args.adaptive,
        lift_model=lift_model,
    )
    ideal = simulator.calculate_ideal_range()
    ground_range, flight_time = simulator.run_simulation()
    result = simulator.result()

    mode = 'RK4, adaptive timestep' if args.adaptive else 'RK4, With Drag'
    print("--- Simulation Results (RK4 Refactored) ---")
    print(f"Input Velocity: {velocity_kmph} km/h")
    print(f"Launch Angle: {angle_deg} deg")
    if args.spin_rpm != 0.0:
        print(f"Spin Rate: {args.spin_rpm:g} rpm")
        print(f"Spin Axis Angle: {args.spin_axis_deg:g} deg")
    print(f"Timestep Ceiling: {args.dt_max:g} s")
    print("\n--- Range Comparison ---")
    print(f"Ideal Range (No Drag): {ideal:.2f} m")
    print(f"Realistic Range ({mode}): {ground_range:.2f} m")
    if args.spin_rpm != 0.0:
        print(f"Lateral Deflection: {result.lateral_range:.2f} m")
    print(f"Actual Flight Time: {flight_time:.2f} s")
    print(f"Integration Steps: {result.steps}")
    if result.timestep_min is not None and result.timestep_min < args.dt_max:
        print(f"Shortest Step Taken: {result.timestep_min:.6g} s")
    if result.timed_out:
        print(
            f"WARNING: simulation stopped at the {DEFAULT_PARAMETERS.max_time:g} s "
            "time limit without reaching the ground"
        )
    return 0


def _run_orbital(args: CliArgs) -> int:
    """Integrate a central-gravity orbit and print its osculating elements.

    The state is placed on the +x axis at ``args.radius`` with the launch
    speed tangent to the orbit (``--angle`` is ignored). Without perturbation
    flags the two-body motion is closed (drag off, inverse-square gravity);
    ``--j2`` adds the oblateness term and ``--atmosphere`` enables the
    piecewise-exponential drag decay.
    """
    if args.radius <= 0.0:
        raise SystemExit("error: --radius must be greater than 0")

    velocity_kmph, _ = load_scenario(args.path, v0_kmph=args.v0_kmph)
    speed_mps = velocity_kmph * KMPH_TO_MPS
    state = (args.radius, 0.0, 0.0, 0.0, speed_mps, 0.0)

    constants = {} if args.atmosphere else {"drag_coefficient": 0.0}
    parameters = coerce_parameters(constants)
    mu = parameters.mu

    if args.j2:
        gravity_model = j2_gravity(mu, parameters.j2, parameters.equatorial_radius)
        gravity_label = "J2 oblateness"
    else:
        gravity_model = newtonian_gravity(mu)
        gravity_label = "Newtonian point mass"

    drag_model = None
    if args.atmosphere:
        drag_model = atmospheric_drag(
            parameters,
            tabulated_density(EARTH_ATMOSPHERE_LAYERS),
            orbital_altitude(parameters.equatorial_radius),
        )

    simulator = ProjectileSimulator.from_state(
        state,
        constants,
        args.dt_max,
        adaptive=args.adaptive,
        gravity_model=gravity_model,
        drag_model=drag_model,
        ground_collision=False,
    )
    simulator.run_simulation()
    result = simulator.result()
    elements = orbital_elements(simulator.state, mu)

    circular_speed = math.sqrt(mu / args.radius)
    print("--- Orbital Simulation ---")
    print(f"Gravity Model: {gravity_label}")
    print(f"Atmosphere: {'on' if args.atmosphere else 'off'}")
    print(f"Central mu: {mu:.6g} m^3/s^2")
    print(f"Initial Radius: {args.radius:.6g} m")
    print(f"Initial Speed: {speed_mps:.6g} m/s")
    print(f"Circular Speed: {circular_speed:.6g} m/s")
    print(f"Timestep Ceiling: {args.dt_max:g} s")
    print("\n--- Orbital Elements ---")
    print(f"Specific Energy: {elements.specific_energy:.6g} J/kg")
    print(f"Semi-major Axis: {_format_optional(elements.semi_major_axis)} m")
    print(f"Eccentricity: {elements.eccentricity:.6g}")
    print(f"Periapsis: {elements.periapsis:.6g} m")
    print(f"Apoapsis: {_format_optional(elements.apoapsis)} m")
    print(f"Period: {_format_optional(elements.period)} s")
    print(f"Inclination: {math.degrees(elements.inclination_rad):.4f} deg")
    print("\n--- Integration ---")
    print(f"Flight Time: {result.flight_time:.6g} s")
    print(f"Integration Steps: {result.steps}")
    if result.timestep_min is not None and result.timestep_min < args.dt_max:
        print(f"Shortest Step Taken: {result.timestep_min:.6g} s")
    return 0


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))