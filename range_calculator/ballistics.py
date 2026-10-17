"""Pure projectile-flight physics: RK4 integration with quadratic air drag.

No file I/O happens in this module. Callers supply a :class:`PhysicalParameters`
profile (or the legacy constants mapping) and receive the flight result, which
makes the integrator directly unit-testable.

Gravity is a pluggable acceleration field: :func:`constant_gravity` reproduces
the flat-earth ballistics model and :func:`newtonian_gravity` provides the
inverse-square field used for orbital mechanics.

:class:`ProjectileSimulator` integrates either at a fixed timestep or, with
``adaptive=True``, at a timestep shortened to stay inside the RK4 stability
band. The adaptive mode is a divergence safeguard: it shortens a step that would
breach the stability bound, but never lengthens one past the caller's ``dt``, so
it cannot make a result more accurate than the fixed mode at the same ``dt``.
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Callable, NamedTuple

from physics_config import DEFAULT_PARAMETERS, coerce_parameters

State = tuple[float, float, float, float, float, float]

X, Y, Z, VX, VY, VZ = range(6)

GravityModel = Callable[[State], "tuple[float, float, float]"]
DragModel = Callable[[State], "tuple[float, float, float]"]
DensityModel = Callable[[float], float]

LAUNCH_X = 0.0
LAUNCH_Y = 0.0
LAUNCH_Z = 0.0

STABILITY_LIMIT = 0.5
UPWARD_TOLERANCE = 1e-9

# Earth defaults for the optional perturbation terms. The gravity model only
# uses ``mu`` directly; ``j2`` and ``equatorial_radius`` parametrise the
# oblateness term, and the atmospheric table is a classic piecewise-exponential
# fit (base altitude, density, scale height) for the 0-1000 km range.
J2_EARTH = 1.08263e-3
EQUATORIAL_RADIUS_EARTH = 6.378137e6
SCALE_HEIGHT_EARTH = 8500.0
SEA_LEVEL_DENSITY_EARTH = 1.225

# Magnus (spin) lift defaults for the linear-with-saturation model
# ``C_L = min(slope * S, max)`` with the spin factor ``S = omega * R / v``. The
# slope and cap are first-order fits for a spinning ball rather than a precise
# aerodynamic model; see SPEC.md's "適用限界" section.
LIFT_COEFFICIENT_SLOPE = 1.0
LIFT_COEFFICIENT_MAX = 0.3

EARTH_ATMOSPHERE_LAYERS: tuple[tuple[float, float, float], ...] = (
    (0.0, 1.225, 7249.0),
    (25000.0, 3.899e-2, 6349.0),
    (30000.0, 1.774e-2, 6682.0),
    (40000.0, 3.972e-3, 7554.0),
    (50000.0, 1.057e-3, 8382.0),
    (60000.0, 3.206e-4, 7714.0),
    (70000.0, 8.770e-5, 6549.0),
    (80000.0, 1.905e-5, 5799.0),
    (90000.0, 3.396e-6, 5382.0),
    (100000.0, 5.297e-7, 5877.0),
    (110000.0, 9.661e-8, 7263.0),
    (120000.0, 2.438e-8, 9473.0),
    (130000.0, 8.484e-9, 12636.0),
    (140000.0, 3.845e-9, 16149.0),
    (150000.0, 2.070e-9, 22523.0),
    (180000.0, 5.464e-10, 29740.0),
    (200000.0, 2.789e-10, 37105.0),
    (250000.0, 7.248e-11, 45546.0),
    (300000.0, 2.418e-11, 53628.0),
    (350000.0, 9.518e-12, 53298.0),
    (400000.0, 3.725e-12, 58515.0),
    (450000.0, 1.585e-12, 60828.0),
    (500000.0, 6.967e-13, 63822.0),
    (600000.0, 1.454e-13, 71835.0),
    (700000.0, 3.614e-14, 88667.0),
    (800000.0, 1.170e-14, 124640.0),
    (900000.0, 5.245e-15, 181050.0),
    (1000000.0, 3.019e-15, 268000.0),
)


class SimulationDiverged(RuntimeError):
    """Raised when the integration stops producing physically meaningful states."""


def derivatives(
    state: State,
    k: float,
    gravity: float = DEFAULT_PARAMETERS.gravity,
) -> State:
    """Time derivatives of ``state = (x, y, z, vx, vy, vz)``.

    ``k`` is the drag scaling factor (1/2 * rho * A * Cd) / m, so that the drag
    acceleration is -k * v * |v|. Gravity acts along the vertical ``y`` axis, so
    the returned tuple is (dx/dt, dy/dt, dz/dt, dvx/dt, dvy/dt, dvz/dt).

    ``gravity`` is the constant flat-earth acceleration; use
    :func:`derivatives_with_gravity` for a position-dependent field.
    """
    return _derivatives(state, k, (0.0, -gravity, 0.0))


def derivatives_with_gravity(
    state: State,
    k: float,
    gravity: GravityModel,
) -> State:
    """Time derivatives of ``state`` under the acceleration field ``gravity``.

    ``gravity`` maps a state to its gravitational acceleration ``(ax, ay, az)``,
    which is added to the drag acceleration. Use :func:`constant_gravity` for the
    flat-earth model and :func:`newtonian_gravity` for an inverse-square field
    about the origin.
    """
    return _derivatives(state, k, gravity(state))


def _derivatives(
    state: State,
    k: float,
    acceleration: tuple[float, float, float],
) -> State:
    vx, vy, vz = state[VX], state[VY], state[VZ]
    speed = math.hypot(vx, vy, vz)
    ax, ay, az = acceleration
    return (
        vx,
        vy,
        vz,
        -k * vx * speed + ax,
        -k * vy * speed + ay,
        -k * vz * speed + az,
    )


def constant_gravity(gravity: float | None = None) -> GravityModel:
    """Flat-earth gravity field pointing down the ``-y`` axis.

    ``gravity`` defaults to the profile value; pass ``0.0`` for a field-free run.
    """
    value = DEFAULT_PARAMETERS.gravity if gravity is None else gravity
    return lambda state: (0.0, -value, 0.0)


def newtonian_gravity(mu: float) -> GravityModel:
    """Inverse-square gravity ``a = -mu * r / |r|^3`` toward the origin.

    ``mu`` is the standard gravitational parameter G*M of the central body, and
    the state's position is taken as the offset from that body's centre.
    """
    def field(state: State) -> tuple[float, float, float]:
        x, y, z = state[X], state[Y], state[Z]
        radius_squared = x * x + y * y + z * z
        scale = -mu / (radius_squared * math.sqrt(radius_squared))
        return scale * x, scale * y, scale * z

    return field


def j2_gravity(
    mu: float,
    j2: float = J2_EARTH,
    equatorial_radius: float = EQUATORIAL_RADIUS_EARTH,
) -> GravityModel:
    """Point-mass gravity plus the J2 oblateness perturbation.

    The field is :func:`newtonian_gravity` plus the standard second-degree
    zonal term, using the ``z`` axis as the body's rotation (polar) axis:

    ``a_J2 = -(3/2) J2 mu R^2 / r^5 * ((1 - 5 s^2) x, (1 - 5 s^2) y,
    (3 - 5 s^2) z)`` with ``s = z / r``.

    With ``j2 = 0`` the field is exactly :func:`newtonian_gravity`, so the
    perturbation is strictly opt-in.
    """
    base = newtonian_gravity(mu)

    def field(state: State) -> tuple[float, float, float]:
        ax, ay, az = base(state)
        if j2 == 0.0:
            return ax, ay, az
        x, y, z = state[X], state[Y], state[Z]
        radius_squared = x * x + y * y + z * z
        if radius_squared == 0.0:
            return ax, ay, az
        radius = math.sqrt(radius_squared)
        s = z / radius
        factor = -1.5 * j2 * mu * equatorial_radius**2 / (
            radius_squared * radius_squared * radius
        )
        return (
            ax + factor * (1.0 - 5.0 * s * s) * x,
            ay + factor * (1.0 - 5.0 * s * s) * y,
            az + factor * (3.0 - 5.0 * s * s) * z,
        )

    return field


def sum_fields(*fields: GravityModel) -> GravityModel:
    """Combine acceleration fields by componentwise addition.

    This is the composition hook for multi-body scenarios: each central body
    contributes its own field (with its own ``mu``/``j2``) and the summed field
    can be handed to the integrator unchanged.
    """
    def combined(state: State) -> tuple[float, float, float]:
        ax = ay = az = 0.0
        for field in fields:
            fx, fy, fz = field(state)
            ax += fx
            ay += fy
            az += fz
        return ax, ay, az

    return combined


def constant_density(density: float) -> DensityModel:
    """Altitude-independent density ``rho(h) = density``."""
    return lambda altitude: density


def exponential_density(
    reference_density: float,
    scale_height: float,
    reference_altitude: float = 0.0,
) -> DensityModel:
    """Single-scale-height atmosphere ``rho(h) = rho0 exp(-(h - h0)/H)``.

    Suitable for a rough decay estimate rather than precise prediction; the
    real scale height varies strongly with altitude (use
    :func:`tabulated_density` for a piecewise fit).
    """
    if scale_height <= 0.0:
        raise ValueError("scale_height must be greater than 0")

    def density(altitude: float) -> float:
        return reference_density * math.exp(
            -(altitude - reference_altitude) / scale_height
        )

    return density


def tabulated_density(
    layers: tuple[tuple[float, float, float], ...],
) -> DensityModel:
    """Piecewise-exponential atmosphere from ``(base_altitude, rho, H)`` layers.

    The layers are sorted by base altitude; a query at altitude ``h`` uses the
    highest layer whose base is ``<= h``, evaluating
    ``rho_base exp(-(h - base)/H)``. ``EARTH_ATMOSPHERE_LAYERS`` is a ready-made
    0-1000 km table. An empty table is rejected.
    """
    ordered = tuple(sorted(layers, key=lambda layer: layer[0]))
    if not ordered:
        raise ValueError("layers must not be empty")
    for base, rho, scale in ordered:
        if scale <= 0.0:
            raise ValueError("each layer scale height must be greater than 0")
        if rho < 0.0:
            raise ValueError("each layer density must be at least 0")

    def density(altitude: float) -> float:
        base, rho0, scale = ordered[0]
        for layer_base, layer_rho, layer_scale in ordered:
            if altitude >= layer_base:
                base, rho0, scale = layer_base, layer_rho, layer_scale
            else:
                break
        return rho0 * math.exp(-(altitude - base) / scale)

    return density


def constant_drag(k: float) -> DragModel:
    """Drag acceleration ``-k |v| v`` for a constant scaling factor ``k``.

    Identical to the drag term baked into :func:`derivatives`, so a run wired
    with this model reproduces the legacy result exactly.
    """
    def drag(state: State) -> tuple[float, float, float]:
        vx, vy, vz = state[VX], state[VY], state[VZ]
        speed = math.hypot(vx, vy, vz)
        return -k * vx * speed, -k * vy * speed, -k * vz * speed

    return drag


def orbital_altitude(equatorial_radius: float) -> Callable[[State], float]:
    """Altitude callable ``|r| - R`` for a central-body (spherical) scenario."""
    return lambda state: math.hypot(state[X], state[Y], state[Z]) - equatorial_radius


def flat_altitude() -> Callable[[State], float]:
    """Altitude callable ``y`` for the flat-earth ballistics scenario."""
    return lambda state: state[Y]


def atmospheric_drag(
    parameters: "PhysicalParameters",
    density_model: DensityModel,
    altitude: Callable[[State], float],
) -> DragModel:
    """Quadratic drag whose density comes from ``density_model(altitude(state))``.

    The scaling factor becomes position dependent, ``k(h) = (1/2) rho(h) A Cd /
    m``, so this models orbital decay rather than the constant-density
    projectile case. Use :func:`constant_drag` for the latter.
    """
    area = parameters.frontal_area()
    coefficient = parameters.drag_coefficient
    mass = parameters.mass

    def drag(state: State) -> tuple[float, float, float]:
        density = density_model(altitude(state))
        if density < 0.0:
            density = 0.0
        k = 0.5 * density * area * coefficient / mass
        vx, vy, vz = state[VX], state[VY], state[VZ]
        speed = math.hypot(vx, vy, vz)
        return -k * vx * speed, -k * vy * speed, -k * vz * speed

    return drag


def spin_axis_vector(spin_axis_angle_deg: float) -> tuple[float, float, float]:
    """Unit spin axis for a launch travelling down the ``+x`` axis.

    The axis starts along ``+z`` (pure backspin/underspin, so the Magnus force is
    vertical) and is rotated by ``spin_axis_angle_deg`` about ``+x``: at ``0`` the
    ball is lifted straight up for a positive spin rate, at ``+90`` it curves
    toward ``+z`` and at ``-90`` toward ``-z``, while ``±180`` inverts the lift
    (topspin). The sign of the spin rate then selects the force direction along
    the given axis.
    """
    angle = math.radians(spin_axis_angle_deg)
    return 0.0, -math.sin(angle), math.cos(angle)


def magnus_lift(
    parameters: "PhysicalParameters",
    spin_rate_rpm: float,
    spin_axis_angle_deg: float = 0.0,
    density_model: DensityModel | None = None,
    altitude: Callable[[State], float] | None = None,
    *,
    slope: float = LIFT_COEFFICIENT_SLOPE,
    max_coefficient: float = LIFT_COEFFICIENT_MAX,
) -> DragModel:
    """Magnus lift acceleration field for a ball spinning about a fixed axis.

    The lift coefficient follows the linear-with-saturation model
    ``C_L = min(slope * S, max)`` with the spin factor ``S = |omega| * R / v``
    (``R`` = radius, ``omega`` in rad/s). The acceleration
    ``a = (1/2 rho A C_L / m) * v * (axis x v)`` is perpendicular to the
    velocity, so tilting the axis curves the flight sideways; the sign of
    ``spin_rate_rpm`` selects the force direction. See :func:`spin_axis_vector`
    for the axis convention. Density is the profile ``air_density`` unless a
    ``density_model`` and ``altitude`` are supplied. A zero spin rate yields a
    zero field, so it can be wired in unconditionally.
    """
    area = parameters.frontal_area()
    mass = parameters.mass
    radius = 0.5 * parameters.diameter
    omega = spin_rate_rpm * (2.0 * math.pi / 60.0)
    direction = 1.0 if omega >= 0.0 else -1.0
    _, axis_y, axis_z = spin_axis_vector(spin_axis_angle_deg)

    def lift(state: State) -> tuple[float, float, float]:
        vx, vy, vz = state[VX], state[VY], state[VZ]
        speed = math.hypot(vx, vy, vz)
        if speed == 0.0 or omega == 0.0:
            return 0.0, 0.0, 0.0
        spin_ratio = abs(omega) * radius / speed
        coefficient = min(slope * spin_ratio, max_coefficient)
        if density_model is not None and altitude is not None:
            density = density_model(altitude(state))
        else:
            density = parameters.air_density
        if density < 0.0:
            density = 0.0
        scale = direction * 0.5 * density * area * coefficient / mass * speed
        # axis x velocity, with axis = (0, axis_y, axis_z)
        cross_x = axis_y * vz - axis_z * vy
        cross_y = axis_z * vx
        cross_z = -axis_y * vx
        return scale * cross_x, scale * cross_y, scale * cross_z

    return lift


def derivatives_with_models(
    state: State,
    gravity: GravityModel,
    drag: DragModel | None = None,
    lift: DragModel | None = None,
) -> State:
    """Time derivatives under gravity plus optional drag and Magnus lift fields.

    This is the general form of :func:`derivatives_with_gravity`: the drag and
    lift terms are themselves state-dependent acceleration fields, which lets
    density vary with position and the Magnus force follow the current velocity.
    ``drag=None`` gives the drag-free two-body equations, so orbital runs need no
    scalar ``k``; ``lift=None`` disables the spin force.
    """
    vx, vy, vz = state[VX], state[VY], state[VZ]
    ax, ay, az = gravity(state)
    if drag is not None:
        dx, dy, dz = drag(state)
        ax += dx
        ay += dy
        az += dz
    if lift is not None:
        lx, ly, lz = lift(state)
        ax += lx
        ay += ly
        az += lz
    return vx, vy, vz, ax, ay, az


def ideal_range(
    initial_velocity: float,
    launch_angle_rad: float,
    gravity: float = DEFAULT_PARAMETERS.gravity,
) -> float:
    """Closed-form ground range assuming no air resistance."""
    return (
        initial_velocity**2 * math.sin(2 * launch_angle_rad) / gravity
    )


class FlightResult(NamedTuple):
    """Detailed outcome of a flight, available via :meth:`ProjectileSimulator.result`."""

    ground_range: float
    lateral_range: float
    flight_time: float
    impact_speed: float
    landed: bool
    timed_out: bool
    steps: int
    timestep_min: float | None
    timestep_max: float | None


class ProjectileSimulator:
    """Integrates a projectile launch with the classical RK4 method.

    With ``adaptive=False`` (the default) every step uses the configured ``dt``.
    With ``adaptive=True`` the configured ``dt`` becomes an upper bound and each
    step is shortened by :meth:`_next_timestep` to stay inside the RK4
    stability band.
    """

    def __init__(
        self,
        initial_velocity: float,
        launch_angle_rad: float,
        constants: Any = None,
        dt: float = 0.01,
        *,
        divergence_speed_factor: float = 1000.0,
        adaptive: bool = False,
        gravity_model: GravityModel | None = None,
        drag_model: DragModel | None = None,
        lift_model: DragModel | None = None,
        ground_collision: bool = True,
    ) -> None:
        self.parameters = coerce_parameters(constants)
        self.initial_velocity = _finite("initial_velocity", initial_velocity)
        self.launch_angle_rad = _finite("launch_angle_rad", launch_angle_rad)
        self.dt = _positive("dt", dt)
        self.default_dt = self.dt
        self.adaptive = bool(adaptive)
        self.divergence_speed_factor = _positive(
            "divergence_speed_factor", divergence_speed_factor
        )
        self.k = self.parameters.drag_scaling_factor()
        self.gravity = self.parameters.gravity
        self.max_time = self.parameters.max_time
        self.gravity_model: GravityModel = (
            gravity_model if gravity_model is not None
            else constant_gravity(self.gravity)
        )
        self.custom_drag = drag_model is not None
        self.drag_model: DragModel = (
            drag_model if drag_model is not None
            else constant_drag(self.k)
        )
        self.lift_model: DragModel | None = lift_model
        self.ground_collision = bool(ground_collision)
        self.initial_state: State = (
            LAUNCH_X,
            LAUNCH_Y,
            LAUNCH_Z,
            self.initial_velocity * math.cos(self.launch_angle_rad),
            self.initial_velocity * math.sin(self.launch_angle_rad),
            0.0,
        )
        self.reset()

    @classmethod
    def from_state(
        cls,
        state: State,
        constants: Any = None,
        dt: float = 0.01,
        *,
        divergence_speed_factor: float = 1000.0,
        adaptive: bool = False,
        gravity_model: GravityModel | None = None,
        drag_model: DragModel | None = None,
        lift_model: DragModel | None = None,
        ground_collision: bool = True,
    ) -> "ProjectileSimulator":
        """Build a simulator that starts from an explicit ``state``.

        The launch velocity and angle of :meth:`__init__` only describe the
        ballistics parameterisation (origin at the launch point). Scenarios whose
        origin is the central body instead, such as orbits, need the full state;
        the launch speed and angle are derived from ``state`` so the divergence
        guards keep a sensible baseline.
        """
        speed = math.hypot(state[VX], state[VY], state[VZ])
        angle = math.atan2(state[VY], state[VX])
        simulator = cls(
            speed,
            angle,
            constants,
            dt,
            divergence_speed_factor=divergence_speed_factor,
            adaptive=adaptive,
            gravity_model=gravity_model,
            drag_model=drag_model,
            lift_model=lift_model,
            ground_collision=ground_collision,
        )
        simulator.initial_state = state
        simulator.reset()
        return simulator

    def reset(self) -> None:
        """Restore the configured launch conditions so a fresh run can start.

        This also drops any timestep override passed to
        :meth:`run_simulation`, so a failed run never leaves the simulator
        configured with the timestep that broke it.
        """
        self.state: State = self.initial_state
        self.t = 0.0
        self.landed = False
        self.timed_out = False
        self.dt = self.default_dt
        self.steps = 0
        self.timestep_min: float | None = None
        self.timestep_max: float | None = None

    def calculate_ideal_range(self) -> float:
        """Ground range that would be reached without air resistance."""
        return ideal_range(self.initial_velocity, self.launch_angle_rad, self.gravity)

    def run_simulation(
        self,
        dt: float | None = None,
        resume: bool = False,
        *,
        on_step: Callable[[float, State], None] | None = None,
    ) -> tuple[float, float]:
        """Integrate until ground impact or the configured time limit.

        Returns ``(ground_range, flight_time)``; use :meth:`result` for the
        impact speed and landing flags.

        The optional ``on_step`` callback is invoked as ``on_step(t, state)``
        with the launch state, each accepted intermediate state, and the final
        landing state. It is a pure observation hook: it does not influence the
        integration, so it is safe to use for recording a trajectory. Passing
        ``None`` (the default) keeps the behaviour identical to before.

        The call is idempotent: unless ``resume`` is true the state is reset to
        the launch conditions first, so repeated calls reproduce the same result.

        In adaptive mode ``dt`` is a ceiling, not the step actually taken: every
        step is shortened by :meth:`_next_timestep`. The step therefore never
        exceeds the value the caller asked for, so this shortens coarse
        timesteps without silently claiming more accuracy than ``dt`` allows.

        Raises:
            SimulationDiverged: the integration produced non-finite states or
                velocities beyond ``divergence_speed_factor`` times the launch
                speed, which means the timestep is too coarse for the physics.
            ValueError: an upward launch reached the ground inside the first
                timestep, which means the timestep is too coarse to be trusted.
                This stays active in adaptive mode because without drag there is
                no stability band to shrink into.
        """
        timestep = self.dt if dt is None else _positive("dt", dt)
        if resume:
            if self.landed:
                return self.state[X], self.t
        else:
            self.reset()
        self.dt = timestep
        if on_step is not None:
            on_step(self.t, self.state)

        k, gravity_model, dt = self.k, self.gravity_model, self.dt
        drag_model = self.drag_model
        lift_model = self.lift_model
        launch_speed = math.hypot(self.state[VX], self.state[VY], self.state[VZ])
        if not self.adaptive and not self.custom_drag:
            self._warn_if_unstable(dt, k, launch_speed)
        speed_limit = max(
            launch_speed * self.divergence_speed_factor,
            self.gravity * self.max_time,
        )
        launched_upwards = (
            self.initial_state[VY] > UPWARD_TOLERANCE * launch_speed
        )

        while True:
            if self.adaptive:
                h = self._next_timestep(self.state, dt, k)
                # max_time - t is strictly positive here: the loop below breaks
                # as soon as t reaches the limit, so this only trims the
                # overshoot instead of stalling the integration.
                h = min(h, self.max_time - self.t)
            else:
                h = dt
            next_state = self._rk4_step(self.state, h, gravity_model, drag_model, lift_model)
            next_t = self.t + h
            self._record_timestep(h)

            self._guard_against_divergence(next_state, speed_limit)

            if self.ground_collision and next_state[Y] < 0.0:
                if self.steps == 1 and launched_upwards:
                    raise ValueError(
                        f"timestep dt={h:g} is too coarse: an upward launch reached "
                        f"the ground within the first step. Reduce dt below "
                        f"{self._stable_timestep(k, launch_speed):g}."
                    )
                self.state, self.t = self._interpolate_ground_crossing(
                    self.state, next_state, self.t, h
                )
                self.landed = True
                if on_step is not None:
                    on_step(self.t, self.state)
                break

            self.state = next_state
            self.t = next_t
            if on_step is not None:
                on_step(self.t, self.state)
            if self.t >= self.max_time:
                self.timed_out = True
                break

        return self.state[X], self.t

    def _next_timestep(self, state: State, dt_max: float, k: float) -> float:
        """Step to take from ``state``, never longer than ``dt_max``.

        The only limit is the RK4 stability bound ``STABILITY_LIMIT / (k * speed)``,
        the same divergence guard as :meth:`_stable_timestep` but evaluated at the
        speed reached here rather than at the launch speed.

        The result is never larger than ``dt_max``, so the step only shrinks. That
        makes this a divergence safeguard rather than an accuracy upgrade: the
        overall error still scales with the caller's ``dt_max``.

        A cap on the time remaining until impact was tried here and removed. Any
        bound of the form ``h <= c * y / -vy`` with ``c < 1`` lets the step cover
        only a fixed fraction of the height still to fall, so ``y`` decays
        geometrically towards zero and never passes it; since landing is detected
        by the strict test ``y < 0``, the integration would never terminate. The
        cap is also redundant, because the ground crossing is already resolved by
        the interpolation in :meth:`_interpolate_ground_crossing`.
        """
        speed = math.hypot(state[VX], state[VY], state[VZ])
        return min(dt_max, self._stable_timestep(k, speed))

    def _record_timestep(self, timestep: float) -> None:
        self.steps += 1
        if self.timestep_min is None or timestep < self.timestep_min:
            self.timestep_min = timestep
        if self.timestep_max is None or timestep > self.timestep_max:
            self.timestep_max = timestep

    @staticmethod
    def _stable_timestep(k: float, speed: float) -> float:
        """Largest timestep that keeps the explicit RK4 within its stability band."""
        if k <= 0.0 or speed <= 0.0:
            return float("inf")
        return STABILITY_LIMIT / (k * speed)

    def _warn_if_unstable(self, dt: float, k: float, launch_speed: float) -> None:
        """Warn when dt breaches the explicit-RK4 stability band.

        Only the fixed-timestep mode reaches this; adaptive mode shortens the
        step instead of warning. This is a divergence guard, not an accuracy
        guarantee: the measured range error still grows roughly as
        (dt * k * v)**2, so keeping dt below the advertised value only bounds
        divergence, not the error magnitude. Tight accuracy needs a much smaller
        dt, or an adaptive timestep.
        """
        stable_dt = self._stable_timestep(k, launch_speed)
        if dt <= stable_dt:
            return
        warnings.warn(
            f"timestep dt={dt:g} is too coarse for a {launch_speed:.3f} m/s launch: "
            f"dt*k*v = {dt * k * launch_speed:.3f} exceeds {STABILITY_LIMIT}, so the "
            f"RK4 result may be inaccurate. Use dt <= {stable_dt:g} to stay stable.",
            RuntimeWarning,
            stacklevel=3,
        )

    def _guard_against_divergence(self, state: State, speed_limit: float) -> None:
        if not all(map(math.isfinite, state)):
            raise SimulationDiverged(
                f"integration produced a non-finite state {state}; "
                f"the timestep is too coarse for this scenario"
            )
        speed = math.hypot(state[VX], state[VY], state[VZ])
        if speed > speed_limit:
            raise SimulationDiverged(
                f"integration produced a speed of {speed:.4g} m/s, more than "
                f"{self.divergence_speed_factor:g}x the launch speed; "
                f"the timestep is too coarse for this scenario"
            )

    def result(self) -> FlightResult:
        """Snapshot of the current state as a :class:`FlightResult`."""
        return FlightResult(
            ground_range=self.state[X],
            lateral_range=self.state[Z],
            flight_time=self.t,
            impact_speed=math.hypot(self.state[VX], self.state[VY], self.state[VZ]),
            landed=self.landed,
            timed_out=self.timed_out,
            steps=self.steps,
            timestep_min=self.timestep_min,
            timestep_max=self.timestep_max,
        )

    @staticmethod
    def _rk4_step(
        state: State,
        dt: float,
        gravity: GravityModel,
        drag: DragModel | None = None,
        lift: DragModel | None = None,
    ) -> State:
        k1 = derivatives_with_models(state, gravity, drag, lift)
        s2 = _advance(state, k1, dt / 2)
        k2 = derivatives_with_models(s2, gravity, drag, lift)
        s3 = _advance(state, k2, dt / 2)
        k3 = derivatives_with_models(s3, gravity, drag, lift)
        s4 = _advance(state, k3, dt)
        k4 = derivatives_with_models(s4, gravity, drag, lift)
        return tuple(
            state[i] + dt * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) / 6
            for i in range(len(state))
        )

    @staticmethod
    def _interpolate_ground_crossing(
        state: State, next_state: State, t: float, dt: float
    ) -> tuple[State, float]:
        """Interpolate the exact y = 0 crossing inside a timestep.

        Returns the crossing state together with its time.
        """
        span = state[Y] - next_state[Y]
        ratio = state[Y] / span if span != 0.0 else 1.0
        ratio = min(max(ratio, 0.0), 1.0)
        crossed: State = (
            state[X] + ratio * (next_state[X] - state[X]),
            0.0,
            state[Z] + ratio * (next_state[Z] - state[Z]),
            state[VX] + ratio * (next_state[VX] - state[VX]),
            state[VY] + ratio * (next_state[VY] - state[VY]),
            state[VZ] + ratio * (next_state[VZ] - state[VZ]),
        )
        return crossed, t + ratio * dt


def _advance(state: State, derivative: State, h: float) -> State:
    return tuple(state[i] + h * derivative[i] for i in range(len(state)))


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    return float(value)


def _positive(name: str, value: Any) -> float:
    number = _finite(name, value)
    if number <= 0.0:
        raise ValueError(f"{name} must be greater than 0, got {number}")
    return number