"""GUI-independent logic for the desktop apps.

Everything here is free of Tkinter so it can be unit-tested headlessly. The GUIs
(:mod:`app_common`, :mod:`ballistic_app`, :mod:`orbital_app`) only wire widgets
to these functions.

The drag-coefficient presets, default launch conditions, and the dt validation
messages mirror ``webapp/src/lib/sim.ts``. That duplication is intentional (each
entry point stays self-contained) and is guarded by
``desktop/tests/test_agreement.py``, which parses ``sim.ts`` and fails if the
values or labels ever drift apart. Update both when a preset or message changes.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
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
from orbital import OrbitalElements, orbital_elements  # noqa: E402
from physics_config import DEFAULT_PARAMETERS, coerce_parameters  # noqa: E402

KMPH_TO_MPS = 1000 / 3600

GRAVITY_MODELS = ("constant", "newtonian", "j2")
DRAG_MODELS = ("constant", "exponential", "tabulated")

DT_MIN = 0.0001
DT_MAX = 10.0

VELOCITY_MIN = 10.0
VELOCITY_MAX = 500.0
ANGLE_MIN = 1.0
ANGLE_MAX = 89.0

DEFAULT_VELOCITY_KMPH = 170.0
DEFAULT_ANGLE_DEG = 35.0
DEFAULT_TIMESTEP = 0.01
DEFAULT_ADAPTIVE = False
DRAG_COEFFICIENT_DEFAULT = 0.47
DEFAULT_SPIN_RPM = 0.0
DEFAULT_SPIN_AXIS_DEG = 0.0

SPIN_RATE_MIN = 0.0
SPIN_RATE_MAX = 6000.0
SPIN_AXIS_MIN = -180.0
SPIN_AXIS_MAX = 180.0

# The only supported drag coefficient is the default sphere; the value and label
# mirror DRAG_PRESETS in webapp/src/lib/sim.ts. Kept as a list so the agreement
# test still guards the default against drift.
DRAG_PRESETS: tuple[tuple[float, str], ...] = (
    (DRAG_COEFFICIENT_DEFAULT, "球体（既定値）"),
)

MAX_TRAJECTORY_POINTS = 2000

# Order and labels for the gravity / drag-density selectors. The values are the
# exact strings :func:`simulate` accepts (see GRAVITY_MODELS / DRAG_MODELS).
GRAVITY_PRESETS: tuple[tuple[str, str], ...] = (
    ("constant", "一定（地表弾道）"),
    ("newtonian", "ニュートン（軌道）"),
    ("j2", "ニュートン+J2（軌道）"),
)

# "none" disables drag entirely; the remaining values map onto DRAG_MODELS and
# ``None`` is realised by forcing ``drag_coefficient`` to 0.
DENSITY_PRESETS: tuple[tuple[str, str], ...] = (
    ("none", "なし"),
    ("constant", "一様（既定）"),
    ("exponential", "指数（高度依存）"),
    ("tabulated", "区分指数（0–1000 km）"),
)

DEFAULT_ORBITAL_RADIUS = 7.0e6

RADIUS_MIN = 6.5e6
RADIUS_MAX = 4.2e7
ORBITAL_SPEED_MIN = 100.0
ORBITAL_SPEED_MAX = 12000.0

# Closed orbits are integrated for one full period times this margin, so the
# trajectory visibly closes instead of stopping after the projectile max_time.
ORBITAL_PERIOD_MARGIN = 1.05

# Upper bound on the number of integration steps for one orbit. A full period at
# the projectile dt (0.01 s) would need ~600k steps (~30 s of wall time), so the
# orbital timestep is raised to ``period / this`` when the caller asks for finer.
MAX_ORBITAL_STEPS = 4000

# Placeholder rows shown before the first run (ballistic shape, values blank).
# Kept in sync with :func:`result_metrics` by ``test_gui_model``.
DEFAULT_METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("ideal_range", "理想射程（抗力なし）", "-"),
    ("ground_range", "実射程（抗力あり）", "-"),
    ("reduction", "到達距離の低減率", "-"),
    ("lateral_range", "横方向のずれ z", "-"),
    ("flight_time", "飛行時間", "-"),
    ("impact_speed", "着弾速度", "-"),
    ("steps", "積分ステップ数", "-"),
    ("timestep", "刻み幅", "-"),
    ("landed", "着弾", "-"),
)

# Placeholder rows for the orbital window before the first run. Kept in sync
# with :func:`result_metrics` for an orbital outcome by ``test_gui_model``.
DEFAULT_ORBITAL_METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("semi_major_axis", "長半径 a", "-"),
    ("eccentricity", "離心率 e", "-"),
    ("periapsis", "近点半径 r_p", "-"),
    ("apoapsis", "遠点半径 r_a", "-"),
    ("period", "公転周期 T", "-"),
    ("inclination", "軌道傾斜角 i", "-"),
    ("flight_time", "積分時間", "-"),
    ("steps", "積分ステップ数", "-"),
    ("timestep", "刻み幅", "-"),
)


@dataclass(frozen=True)
class LaunchConditions:
    """The launch inputs collected from the UI, before running a simulation.

    ``gravity_model`` selects the acceleration field: ``"constant"`` (the flat
    surface field used for projectiles), ``"newtonian"`` (central gravity, in
    which case ``initial_state`` supplies the full 6-component state and
    ``velocity_kmph``/``angle_deg`` are ignored), or ``"j2"`` (Newtonian plus
    the oblateness perturbation). ``drag_model`` selects the drag law:
    ``"constant"`` (density from the profile's ``air_density``), or a
    position-dependent atmosphere (``"exponential"`` or ``"tabulated"``).
    """

    velocity_kmph: float = DEFAULT_VELOCITY_KMPH
    angle_deg: float = DEFAULT_ANGLE_DEG
    dt: float = DEFAULT_TIMESTEP
    adaptive: bool = DEFAULT_ADAPTIVE
    drag_coefficient: float = DRAG_COEFFICIENT_DEFAULT
    gravity_model: str = "constant"
    drag_model: str = "constant"
    j2: float | None = None
    initial_state: tuple[float, float, float, float, float, float] | None = None
    spin_rate: float = DEFAULT_SPIN_RPM
    spin_axis_deg: float = DEFAULT_SPIN_AXIS_DEG


@dataclass(frozen=True)
class TrajectoryPoint:
    """One recorded integration step, in the same shape the web API returns."""

    t: float
    x: float
    y: float
    vx: float
    vy: float
    speed: float
    z: float = 0.0


@dataclass(frozen=True)
class SimulationResult:
    """Outcome metrics, named to match the web API's ``result`` object.

    ``ideal_range`` is ``None`` for central-gravity runs, where the flat-surface
    closed form does not apply.
    """

    ideal_range: float | None
    ground_range: float | None
    flight_time: float
    impact_speed: float
    landed: bool
    timed_out: bool
    steps: int
    timestep_min: float | None
    timestep_max: float | None
    lateral_range: float = 0.0


@dataclass(frozen=True)
class SimulationOutcome:
    """A full run: the conditions, the metrics, and the recorded trajectory.

    ``orbital`` carries the osculating elements for central-gravity runs and is
    ``None`` for surface projectiles.
    """

    conditions: LaunchConditions
    result: SimulationResult
    trajectory: list[TrajectoryPoint] = field(default_factory=list)
    orbital: OrbitalElements | None = None

    @property
    def reduction_percent(self) -> float:
        """Distance lost to drag as a percentage of the ideal range."""
        ideal = self.result.ideal_range
        if ideal is None or ideal <= 0.0:
            return 0.0
        return (ideal - self.result.ground_range) / ideal * 100.0


def preset_label(value: float) -> str:
    """Dropdown label for a drag coefficient, matching the web UI.

    Known presets render as ``<label>（Cd=<value>）``; unknown values fall back
    to ``Cd=<value>``.
    """
    for preset_value, preset in DRAG_PRESETS:
        if math.isclose(preset_value, value, rel_tol=0.0, abs_tol=1e-12):
            return f"{preset}（Cd={preset_value:g}）"
    return f"Cd={value:g}"


def gravity_label(value: str) -> str:
    """Human label for a gravity-model value (falls back to the raw value)."""
    for candidate, label in GRAVITY_PRESETS:
        if candidate == value:
            return label
    return value


def density_label(value: str) -> str:
    """Human label for a drag-density value (falls back to the raw value)."""
    for candidate, label in DENSITY_PRESETS:
        if candidate == value:
            return label
    return value


def orbital_speed(radius: float, mu: float = DEFAULT_PARAMETERS.mu) -> float:
    """Circular-orbit speed ``sqrt(mu / r)`` at ``radius`` (SI units)."""
    if radius <= 0.0:
        raise ValueError("radius must be greater than 0")
    return math.sqrt(mu / radius)


def orbital_time_span(
    state: tuple[float, float, float, float, float, float],
    mu: float = DEFAULT_PARAMETERS.mu,
    margin: float = ORBITAL_PERIOD_MARGIN,
) -> float | None:
    """Integration span for a central-gravity run: one orbital period × ``margin``.

    A closed orbit is integrated for a full revolution so the trajectory closes,
    rather than stopping at the projectile ``max_time`` (300 s) after a short arc.
    Open orbits (``period is None``) return ``None`` so the caller keeps the
    configured ``max_time``.
    """
    elements = orbital_elements(state, mu)
    if elements.period is None:
        return None
    return elements.period * margin


def orbital_timestep(
    state: tuple[float, float, float, float, float, float],
    requested_dt: float,
    mu: float = DEFAULT_PARAMETERS.mu,
    max_steps: int = MAX_ORBITAL_STEPS,
    margin: float = ORBITAL_PERIOD_MARGIN,
) -> float:
    """Orbital timestep bounded by ``max_steps`` over one orbit.

    Returns ``max(requested_dt, period * margin / max_steps)`` for a closed orbit
    so a full revolution stays affordable; open orbits return ``requested_dt``.
    A coarser ``requested_dt`` is always honoured (fewer steps than the bound).
    """
    span = orbital_time_span(state, mu, margin)
    if span is None:
        return requested_dt
    return max(requested_dt, span / max_steps)


def make_conditions(
    *,
    gravity_model: str = "constant",
    velocity_kmph: float = DEFAULT_VELOCITY_KMPH,
    angle_deg: float = DEFAULT_ANGLE_DEG,
    dt: float = DEFAULT_TIMESTEP,
    adaptive: bool = DEFAULT_ADAPTIVE,
    drag_coefficient: float = DRAG_COEFFICIENT_DEFAULT,
    density_model: str = "constant",
    radius: float = DEFAULT_ORBITAL_RADIUS,
    speed_mps: float | None = None,
    spin_rate: float = DEFAULT_SPIN_RPM,
    spin_axis_deg: float = DEFAULT_SPIN_AXIS_DEG,
) -> LaunchConditions:
    """Assemble :class:`LaunchConditions` from the UI's raw control values.

    ``density_model`` is a :data:`DENSITY_PRESETS` value; ``"none"`` disables drag
    (``drag_coefficient = 0``). For a central-gravity model the state is a
    circular orbit at ``radius`` (speed defaults to the circular speed), which
    makes ``velocity_kmph`` / ``angle_deg`` irrelevant. ``spin_rate`` /
    ``spin_axis_deg`` drive the Magnus force and apply to the flat-surface
    ballistic model only.
    """
    if gravity_model not in GRAVITY_MODELS:
        raise ValueError(f"unknown gravity_model: {gravity_model!r}")
    if density_model not in tuple(value for value, _ in DENSITY_PRESETS):
        raise ValueError(f"unknown density_model: {density_model!r}")

    drag_model = "constant" if density_model == "none" else density_model
    coefficient = 0.0 if density_model == "none" else drag_coefficient

    initial_state = None
    if gravity_model != "constant":
        speed = orbital_speed(radius) if speed_mps is None else speed_mps
        initial_state = (radius, 0.0, 0.0, 0.0, speed, 0.0)

    return LaunchConditions(
        velocity_kmph=velocity_kmph,
        angle_deg=angle_deg,
        dt=dt,
        adaptive=adaptive,
        drag_coefficient=coefficient,
        gravity_model=gravity_model,
        drag_model=drag_model,
        initial_state=initial_state,
        spin_rate=spin_rate,
        spin_axis_deg=spin_axis_deg,
    )


def format_optional(value: float | None, digits: int = 2) -> str:
    """Fixed-decimal formatting that renders ``None`` as a dash."""
    if value is None:
        return "-"
    return format_number(value, digits)


def result_metrics(outcome: SimulationOutcome) -> list[tuple[str, str, str]]:
    """``(key, label, value)`` rows for the results panel.

    Ballistic runs report range metrics; central-gravity runs report the
    osculating elements instead. Both share step/timestep rows.
    """
    result = outcome.result
    timestep_label = "最短刻み" if outcome.conditions.adaptive else "刻み幅"
    timestep = (
        f"{format_decimal(result.timestep_min)} s"
        if result.timestep_min is not None
        else "-"
    )

    if outcome.orbital is None:
        return [
            ("ideal_range", "理想射程（抗力なし）", f"{format_number(result.ideal_range)} m"),
            ("ground_range", "実射程（抗力あり）", f"{format_number(result.ground_range)} m"),
            ("reduction", "到達距離の低減率", f"{format_number(outcome.reduction_percent, 1)} %"),
            ("lateral_range", "横方向のずれ z", f"{format_number(result.lateral_range)} m"),
            ("flight_time", "飛行時間", f"{format_number(result.flight_time)} s"),
            ("impact_speed", "着弾速度", f"{format_number(result.impact_speed)} m/s"),
            ("steps", "積分ステップ数", str(result.steps)),
            ("timestep", timestep_label, timestep),
            ("landed", "着弾", "yes" if result.landed else "no"),
        ]

    elements = outcome.orbital
    return [
        ("semi_major_axis", "長半径 a", f"{format_optional(elements.semi_major_axis)} m"),
        ("eccentricity", "離心率 e", f"{format_number(elements.eccentricity, 6)}"),
        ("periapsis", "近点半径 r_p", f"{format_number(elements.periapsis)} m"),
        ("apoapsis", "遠点半径 r_a", f"{format_optional(elements.apoapsis)} m"),
        ("period", "公転周期 T", f"{format_optional(elements.period)} s"),
        (
            "inclination",
            "軌道傾斜角 i",
            f"{format_number(math.degrees(elements.inclination_rad), 4)} deg",
        ),
        ("flight_time", "積分時間", f"{format_number(result.flight_time)} s"),
        ("steps", "積分ステップ数", str(result.steps)),
        ("timestep", timestep_label, timestep),
    ]


def validate_dt(text: str) -> str | None:
    """Validate the dt entry text, returning a Japanese message or ``None``.

    Mirrors ``dtValidityMessage`` in ``webapp/src/lib/sim.ts`` for the checks that
    make sense outside a browser (bad input, range, and step mismatch).
    """
    try:
        value = float(text)
    except (TypeError, ValueError):
        return "刻み幅 dt には数値を指定してください。"
    if not math.isfinite(value):
        return "刻み幅 dt には数値を指定してください。"
    if value < DT_MIN:
        return f"刻み幅 dt は {DT_MIN} 以上で指定してください。"
    if value > DT_MAX:
        return f"刻み幅 dt は {DT_MAX} 以下で指定してください。"
    steps = value / DT_MIN
    if not math.isclose(steps, round(steps), rel_tol=0.0, abs_tol=1e-6):
        return f"刻み幅 dt は {DT_MIN} 単位で指定してください。"
    return None


def simulate(conditions: LaunchConditions) -> SimulationOutcome:
    """Run one launch through the tested physics core and collect its trajectory.

    A ``"constant"`` gravity model reproduces the flat-surface projectile
    behaviour; ``"newtonian"`` and ``"j2"`` integrate central gravity from
    ``initial_state`` and additionally report the osculating elements. Raises
    whatever the core raises (:class:`SimulationDiverged` or ``ValueError`` for
    a too-coarse timestep); the caller localises the message for display.
    """
    constants = {"drag_coefficient": conditions.drag_coefficient}
    if conditions.j2 is not None:
        constants["j2"] = conditions.j2
    profile = coerce_parameters(constants)
    orbital = conditions.gravity_model in ("newtonian", "j2")

    if conditions.gravity_model == "constant":
        mu = None
        gravity_model = None
        span = None
    elif conditions.gravity_model in ("newtonian", "j2"):
        if conditions.initial_state is None:
            raise ValueError(
                f"initial_state is required for {conditions.gravity_model} gravity"
            )
        mu = profile.mu
        if conditions.gravity_model == "j2":
            gravity_model = j2_gravity(
                mu, profile.j2, profile.equatorial_radius
            )
        else:
            gravity_model = newtonian_gravity(mu)
        span = orbital_time_span(conditions.initial_state, mu)
        if span is not None:
            constants["max_time"] = span
            profile = coerce_parameters(constants)
    else:
        raise ValueError(f"unknown gravity_model: {conditions.gravity_model!r}")

    timestep = conditions.dt
    if span is not None:
        timestep = max(timestep, span / MAX_ORBITAL_STEPS)

    if conditions.drag_model not in DRAG_MODELS:
        raise ValueError(f"unknown drag_model: {conditions.drag_model!r}")
    drag_model = None
    if conditions.drag_model != "constant":
        altitude = (
            orbital_altitude(profile.equatorial_radius)
            if orbital
            else flat_altitude()
        )
        if conditions.drag_model == "exponential":
            density = exponential_density(
                profile.sea_level_density, profile.scale_height
            )
        else:
            density = tabulated_density(EARTH_ATMOSPHERE_LAYERS)
        drag_model = atmospheric_drag(profile, density, altitude)

    if conditions.gravity_model == "constant":
        lift_model = None
        if conditions.spin_rate != 0.0:
            lift_model = magnus_lift(
                profile, conditions.spin_rate, conditions.spin_axis_deg
            )
        simulator = ProjectileSimulator(
            conditions.velocity_kmph * KMPH_TO_MPS,
            math.radians(conditions.angle_deg),
            constants,
            dt=timestep,
            adaptive=conditions.adaptive,
            drag_model=drag_model,
            lift_model=lift_model,
        )
    else:
        simulator = ProjectileSimulator.from_state(
            conditions.initial_state,
            constants,
            timestep,
            adaptive=conditions.adaptive,
            gravity_model=gravity_model,
            drag_model=drag_model,
            ground_collision=False,
        )

    trajectory: list[TrajectoryPoint] = []

    def record(t: float, state: tuple[float, float, float, float, float, float]) -> None:
        x, y, z, vx, vy, vz = state
        trajectory.append(
            TrajectoryPoint(
                t=t, x=x, y=y, vx=vx, vy=vy, speed=math.hypot(vx, vy, vz), z=z
            )
        )

    ideal = None if mu is not None else simulator.calculate_ideal_range()
    simulator.run_simulation(on_step=record)
    raw = simulator.result()

    result = SimulationResult(
        ideal_range=ideal,
        ground_range=raw.ground_range,
        flight_time=raw.flight_time,
        impact_speed=raw.impact_speed,
        landed=raw.landed,
        timed_out=raw.timed_out,
        steps=raw.steps,
        timestep_min=raw.timestep_min,
        timestep_max=raw.timestep_max,
        lateral_range=raw.lateral_range,
    )
    orbital = None if mu is None else orbital_elements(simulator.state, mu)
    return SimulationOutcome(
        conditions=conditions,
        result=result,
        trajectory=_downsample(trajectory, MAX_TRAJECTORY_POINTS),
        orbital=orbital,
    )


def _downsample(
    points: list[TrajectoryPoint], limit: int
) -> list[TrajectoryPoint]:
    """Thin a trajectory to at most ``limit`` points, always keeping the last."""
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def format_number(value: float, digits: int = 2) -> str:
    """Fixed-decimal formatting, mirroring the web UI's ``format`` helper."""
    return f"{value:.{digits}f}"


def format_decimal(value: float, significant_digits: int = 6) -> str:
    """Compact significant-digit formatting for timestep values.

    Mirrors ``formatDecimal`` in ``webapp/src/lib/sim.ts``.
    """
    if not math.isfinite(value):
        return str(value)
    return f"{float(f'{value:.{significant_digits}g}'):g}"


__all__ = [
    "ANGLE_MAX",
    "ANGLE_MIN",
    "DEFAULT_ADAPTIVE",
    "DEFAULT_ANGLE_DEG",
    "DEFAULT_METRIC_ROWS",
    "DEFAULT_ORBITAL_METRIC_ROWS",
    "DEFAULT_ORBITAL_RADIUS",
    "DEFAULT_SPIN_AXIS_DEG",
    "DEFAULT_SPIN_RPM",
    "DEFAULT_TIMESTEP",
    "DEFAULT_VELOCITY_KMPH",
    "DENSITY_PRESETS",
    "DRAG_COEFFICIENT_DEFAULT",
    "DRAG_MODELS",
    "DRAG_PRESETS",
    "DT_MAX",
    "DT_MIN",
    "GRAVITY_MODELS",
    "GRAVITY_PRESETS",
    "LaunchConditions",
    "MAX_ORBITAL_STEPS",
    "ORBITAL_PERIOD_MARGIN",
    "ORBITAL_SPEED_MAX",
    "ORBITAL_SPEED_MIN",
    "OrbitalElements",
    "RADIUS_MAX",
    "RADIUS_MIN",
    "SimulationDiverged",
    "SimulationOutcome",
    "SimulationResult",
    "SPIN_AXIS_MAX",
    "SPIN_AXIS_MIN",
    "SPIN_RATE_MAX",
    "SPIN_RATE_MIN",
    "TrajectoryPoint",
    "VELOCITY_MAX",
    "VELOCITY_MIN",
    "density_label",
    "format_decimal",
    "format_number",
    "format_optional",
    "gravity_label",
    "make_conditions",
    "orbital_speed",
    "orbital_time_span",
    "orbital_timestep",
    "preset_label",
    "result_metrics",
    "simulate",
    "validate_dt",
]
