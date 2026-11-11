"""Mutual-gravity N-body dynamics: classical RK4 over the full 6N-dimensional system.

No file I/O happens in this module. Each body is a point mass carrying its
standard gravitational parameter ``mu = G*M`` (the same convention as
:func:`ballistics.newtonian_gravity`) and a six-component state reusing
:data:`ballistics.State`. The system state is a tuple of per-body states, so an
N-body run is the familiar RK4 applied to 6N coupled first-order ODEs:

``a_i = sum_{j != i} mu_j * (r_j - r_i) / |r_j - r_i|^3``

Every body moves under every other body: the field sources are not fixed at the
origin the way :func:`ballistics.newtonian_gravity` assumes, which is exactly
what separates this module from :func:`ballistics.sum_fields`. The latter
combines fields evaluated at a single state and therefore models several
*fixed* centres; :func:`mutual_gravity` evaluates each pair at the bodies'
*current* positions.

The integrator is classical RK4. By default the timestep is fixed: choose ``dt``
as a small fraction of the shortest dynamical timescale in the system, for
example the period of the tightest pair, ``T = 2*pi*sqrt(r^3 / (mu_i + mu_j))``.
With ``adaptive=True`` the caller's ``dt`` becomes a ceiling and every step is
shortened to ``T_min / ADAPTIVE_STEPS_PER_PERIOD``, where ``T_min`` is the
smallest pair period at the current positions. This is the N-body analogue of
the drag-band adaptive mode in :class:`ballistics.ProjectileSimulator`: it keeps
a fixed number of steps per orbit so the fixed-step result does not diverge, and
it never lengthens a step beyond ``dt`` (so it is a stability guard, not an
accuracy upgrade). Two hard guards remain: a non-finite state, and any body
exceeding ``divergence_speed_factor`` times its initial speed, both raise
:class:`ballistics.SimulationDiverged`. Exact positional coincidence of two
bodies is singular and is rejected both at construction time and inside the
field.

Diagnostics (:func:`total_energy`, :func:`linear_momentum`,
:func:`angular_momentum`, :func:`center_of_mass`) are evaluated in units where
``G = 1`` and each body's mass equals its ``mu``. Their constancy over an
integration is physically meaningful in any unit system; their absolute value
carries the ``G = 1`` convention unless the caller works in units where that
holds.

Known limits, stated up front: the bodies are structureless point masses
(no rotation, tides, or deformation), collisions are not modelled (a close
encounter ends the run), and classical RK4 is not symplectic, so the total
energy drifts secularly over long integrations; refine ``dt`` or switch to a
symplectic scheme if long-term energy conservation is the goal.
"""

from __future__ import annotations

import math
from typing import Any, Callable, NamedTuple, Sequence

from ballistics import State, SimulationDiverged, X, Y, Z, VX, VY, VZ
from physics_config import DEFAULT_PARAMETERS

SystemState = tuple[State, ...]
SystemAccelerations = tuple[tuple[float, float, float], ...]
SystemField = Callable[[SystemState], SystemAccelerations]

# Steps per orbit of the tightest pair in adaptive mode. With ``adaptive=True``
# each step is shortened to ``shortest_pair_period / ADAPTIVE_STEPS_PER_PERIOD``.
# RK4 energy drift scales as (steps per period) ** -4, so this is set well above
# the fixed-mode divergence threshold: 100 steps per orbit keeps the drift near
# 1e-6 per orbit, which matters when the caller wants many orbits (exoplanet
# timescales) rather than just a bounded, non-diverging run.
ADAPTIVE_STEPS_PER_PERIOD = 100


class Body(NamedTuple):
    """A single point mass: standard gravitational parameter ``mu`` and its state.

    ``mu`` is G*M in m^3/s^2, matching :func:`ballistics.newtonian_gravity`;
    the dynamics need no separate mass. ``state`` is the usual
    ``(x, y, z, vx, vy, vz)`` tuple in SI units.
    """

    mu: float
    state: State


class SystemResult(NamedTuple):
    """Outcome of an N-body run, available via :meth:`NBodySimulator.result`.

    ``timestep_min`` / ``timestep_max`` are the smallest and largest steps
    actually taken (``None`` before any run). In adaptive mode ``timestep_max``
    is at most the ``dt`` ceiling and ``timestep_min`` shows how far the step had
    to shrink; in fixed mode both equal ``dt`` except for the trimmed final step.
    """

    elapsed_time: float
    steps: int
    timed_out: bool
    timestep_min: float | None = None
    timestep_max: float | None = None


def mutual_gravity(
    mus: Sequence[float],
    min_separation: float = 0.0,
) -> SystemField:
    """System acceleration field for mutual point-mass gravity.

    ``mus`` holds each body's ``mu = G*M``; body ``i`` is accelerated by
    ``sum_{j != i} mu_j * (r_j - r_i) / |r_j - r_i|^3`` using the *current*
    positions of all bodies. With ``min_separation > 0`` the field raises
    :class:`ballistics.SimulationDiverged` as soon as any pair comes closer
    than that distance, which turns an unmodellable encounter into a loud
    failure instead of a silent numerical artefact. Exact coincidence
    (``|r_i - r_j| = 0``) is always singular and always raises.
    """
    values = _coerce_mus(mus)
    threshold = _non_negative("min_separation", min_separation)

    def field(system: SystemState) -> SystemAccelerations:
        if len(system) != len(values):
            raise ValueError(
                f"system has {len(system)} bodies but the field was built "
                f"for {len(values)}"
            )
        accelerations = _pairwise_accelerations(system, values, threshold)
        return accelerations

    return field


def system_derivatives(
    system: SystemState,
    gravity: SystemField,
) -> SystemState:
    """Time derivatives of ``system`` under the acceleration field ``gravity``.

    The first three components of each body's derivative are its velocity, as
    in :func:`ballistics.derivatives_with_models`; the acceleration half comes
    from ``gravity``. This is the equation of motion the RK4 step integrates.
    """
    accelerations = gravity(system)
    return tuple(
        (
            body[VX],
            body[VY],
            body[VZ],
            accelerations[index][0],
            accelerations[index][1],
            accelerations[index][2],
        )
        for index, body in enumerate(system)
    )


def _pairwise_accelerations(
    system: SystemState,
    mus: tuple[float, ...],
    min_separation: float,
) -> SystemAccelerations:
    count = len(system)
    accelerations = [[0.0, 0.0, 0.0] for _ in range(count)]
    minimum_squared = min_separation * min_separation
    for i in range(count):
        xi, yi, zi = system[i][X], system[i][Y], system[i][Z]
        for j in range(i + 1, count):
            dx = system[j][X] - xi
            dy = system[j][Y] - yi
            dz = system[j][Z] - zi
            separation_squared = dx * dx + dy * dy + dz * dz
            if separation_squared == 0.0:
                raise SimulationDiverged(
                    f"bodies {i} and {j} occupy the same position; "
                    f"the mutual gravitational force is singular"
                )
            if min_separation > 0.0 and separation_squared < minimum_squared:
                raise SimulationDiverged(
                    f"bodies {i} and {j} are within the {min_separation:g} m "
                    f"minimum separation (distance "
                    f"{math.sqrt(separation_squared):.6g} m); a close "
                    f"encounter cannot be modelled as point masses"
                )
            inverse_cube = 1.0 / (
                separation_squared * math.sqrt(separation_squared)
            )
            scale_i = mus[j] * inverse_cube
            scale_j = mus[i] * inverse_cube
            accelerations[i][0] += scale_i * dx
            accelerations[i][1] += scale_i * dy
            accelerations[i][2] += scale_i * dz
            accelerations[j][0] -= scale_j * dx
            accelerations[j][1] -= scale_j * dy
            accelerations[j][2] -= scale_j * dz
    return tuple(tuple(components) for components in accelerations)


def total_energy(bodies: Sequence[Body]) -> float:
    """Total mechanical energy in units where ``G = 1`` and mass equals ``mu``.

    ``E = sum_i 1/2 mu_i |v_i|^2 - sum_{i<j} mu_i mu_j / |r_i - r_j|``. Raises
    :class:`ValueError` for overlapping bodies, where the potential is
    undefined. Constancy of this quantity over an integration is the
    energy-conservation diagnostic; see the module docstring for the unit
    convention.
    """
    kinetic = 0.0
    for body in bodies:
        vx, vy, vz = body.state[VX], body.state[VY], body.state[VZ]
        kinetic += 0.5 * body.mu * (vx * vx + vy * vy + vz * vz)
    potential = 0.0
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            separation = _distance(bodies[i].state, bodies[j].state)
            if separation == 0.0:
                raise ValueError(
                    "energy is undefined for bodies at the same position"
                )
            potential -= bodies[i].mu * bodies[j].mu / separation
    return kinetic + potential


def linear_momentum(bodies: Sequence[Body]) -> tuple[float, float, float]:
    """Total linear momentum ``sum_i mu_i v_i`` (same units as :func:`total_energy`)."""
    px = py = pz = 0.0
    for body in bodies:
        px += body.mu * body.state[VX]
        py += body.mu * body.state[VY]
        pz += body.mu * body.state[VZ]
    return px, py, pz


def angular_momentum(bodies: Sequence[Body]) -> tuple[float, float, float]:
    """Total angular momentum ``sum_i mu_i (r_i x v_i)`` about the origin."""
    lx = ly = lz = 0.0
    for body in bodies:
        x, y, z = body.state[X], body.state[Y], body.state[Z]
        vx, vy, vz = body.state[VX], body.state[VY], body.state[VZ]
        lx += body.mu * (y * vz - z * vy)
        ly += body.mu * (z * vx - x * vz)
        lz += body.mu * (x * vy - y * vx)
    return lx, ly, lz


def center_of_mass(bodies: Sequence[Body]) -> tuple[float, float, float]:
    """Mass-weighted centre ``sum_i mu_i r_i / sum_i mu_i`` (mass equals ``mu``)."""
    total = 0.0
    x = y = z = 0.0
    for body in bodies:
        total += body.mu
        x += body.mu * body.state[X]
        y += body.mu * body.state[Y]
        z += body.mu * body.state[Z]
    if total == 0.0:
        raise ValueError("the centre of mass needs a positive total mass")
    return x / total, y / total, z / total


class NBodySimulator:
    """Integrates mutual point-mass gravity with classical RK4.

    The timestep is fixed unless ``adaptive`` is true, in which case ``dt`` is a
    ceiling and each step is shortened to keep :data:`ADAPTIVE_STEPS_PER_PERIOD`
    steps per orbit of the tightest pair (see :meth:`_adaptive_timestep`).

    The system is validated at construction: at least one body, positive
    finite ``mu`` for each, six finite state components, and no two bodies at
    the same starting position. ``run_simulation`` is idempotent unless
    ``resume`` is true, exactly like
    :meth:`ballistics.ProjectileSimulator.run_simulation`.
    """

    def __init__(
        self,
        bodies: Any,
        dt: float = 0.01,
        *,
        max_time: float | None = None,
        divergence_speed_factor: float = 1000.0,
        min_separation: float = 0.0,
        gravity_model: SystemField | None = None,
        adaptive: bool = False,
    ) -> None:
        self.min_separation = _non_negative("min_separation", min_separation)
        self.initial_bodies = _coerce_bodies(bodies, self.min_separation)
        self.mus = tuple(body.mu for body in self.initial_bodies)
        self.dt = _positive("dt", dt)
        self.default_dt = self.dt
        self.adaptive = bool(adaptive)
        self.max_time = (
            DEFAULT_PARAMETERS.max_time if max_time is None
            else _positive("max_time", max_time)
        )
        self.divergence_speed_factor = _positive(
            "divergence_speed_factor", divergence_speed_factor
        )
        self.gravity_model: SystemField = (
            gravity_model if gravity_model is not None
            else mutual_gravity(self.mus, self.min_separation)
        )
        self.initial_system: SystemState = tuple(
            body.state for body in self.initial_bodies
        )
        # The divergence speed limit is relative to the fastest body at t = 0.
        # A system that starts fully at rest has no such baseline, so the
        # speed guard is disabled and only the finite-state guard remains;
        # any growth from rest is physical (or a collapse, which the
        # singular-force guards and the finite-state guard still catch).
        self._baseline_speed = max(
            (_speed(state) for state in self.initial_system), default=0.0
        )
        self.reset()

    @property
    def bodies(self) -> tuple[Body, ...]:
        """The current state of every body, ready for the diagnostic helpers."""
        return tuple(
            Body(mu, state) for mu, state in zip(self.mus, self.system)
        )

    def reset(self) -> None:
        """Restore the initial system so a fresh run can start.

        This also drops any timestep override passed to
        :meth:`run_simulation`, so a failed run never leaves the simulator
        configured with the timestep that broke it.
        """
        self.system: SystemState = self.initial_system
        self.t = 0.0
        self.timed_out = False
        self.dt = self.default_dt
        self.steps = 0
        self.timestep_min: float | None = None
        self.timestep_max: float | None = None

    def run_simulation(
        self,
        dt: float | None = None,
        resume: bool = False,
        *,
        on_step: Callable[[float, SystemState], None] | None = None,
    ) -> float:
        """Integrate until the configured time limit; returns the elapsed time.

        The optional ``on_step`` callback is invoked as ``on_step(t, system)``
        with the initial system and each accepted system, mirroring
        :meth:`ballistics.ProjectileSimulator.run_simulation`. It is a pure
        observation hook: the system is an immutable tuple, so a callback may
        keep a reference without copying. Passing ``None`` (the default)
        records nothing.

        In adaptive mode ``dt`` is a ceiling, not the step actually taken: each
        step is shortened by :meth:`_adaptive_timestep` to the tightest pair's
        timescale. The step never exceeds the value the caller asked for, so this
        guards against divergence without silently claiming more accuracy than
        ``dt`` allows.

        The final step is trimmed so the elapsed time never exceeds
        ``max_time``; the run then sets ``timed_out``. Unless ``resume`` is
        true the system is reset first, so repeated calls reproduce the same
        result.

        Raises:
            SimulationDiverged: a stage produced a non-finite state, a body
                exceeded ``divergence_speed_factor`` times its initial speed,
                or two bodies came within ``min_separation`` of each other,
                which means the timestep is too coarse for this scenario or
                the encounter cannot be modelled as point masses.
            ValueError: ``dt`` is not positive.
        """
        timestep = self.dt if dt is None else _positive("dt", dt)
        if resume:
            if self.timed_out:
                return self.t
        else:
            self.reset()
        self.dt = timestep
        if on_step is not None:
            on_step(self.t, self.system)

        gravity_model = self.gravity_model
        speed_limit = (
            self.divergence_speed_factor * self._baseline_speed
            if self._baseline_speed > 0.0
            else None
        )

        while True:
            h = timestep
            if self.adaptive:
                h = min(h, self._adaptive_timestep(self.system))
            h = min(h, self.max_time - self.t)
            next_system = _rk4_step(self.system, h, gravity_model)
            self.steps += 1
            self._record_timestep(h)
            self._guard_against_divergence(next_system, speed_limit)
            self.system = next_system
            self.t += h
            if on_step is not None:
                on_step(self.t, self.system)
            if self.t >= self.max_time:
                self.timed_out = True
                break

        return self.t

    def _adaptive_timestep(self, system: SystemState) -> float:
        """Step keeping :data:`ADAPTIVE_STEPS_PER_PERIOD` steps per tightest orbit.

        Evaluates every pair's current Kepler period
        ``T = 2*pi*sqrt(r^3 / (mu_i + mu_j))`` and returns
        ``T_min / ADAPTIVE_STEPS_PER_PERIOD``, or ``inf`` for a single body (no
        pair, so no orbit to resolve). The result is only ever used as a ceiling
        on the caller's ``dt``, so it can shrink a step but never lengthen one.
        """
        smallest = self._shortest_pair_period(system)
        if smallest is None:
            return float("inf")
        return smallest / ADAPTIVE_STEPS_PER_PERIOD

    def _shortest_pair_period(self, system: SystemState) -> float | None:
        """Smallest current pair period, or ``None`` when there is no pair."""
        smallest: float | None = None
        for i in range(len(system)):
            for j in range(i + 1, len(system)):
                separation = _distance(system[i], system[j])
                combined_mu = self.mus[i] + self.mus[j]
                if separation <= 0.0 or combined_mu <= 0.0:
                    continue
                period = 2.0 * math.pi * math.sqrt(
                    separation**3 / combined_mu
                )
                if smallest is None or period < smallest:
                    smallest = period
        return smallest

    def _record_timestep(self, timestep: float) -> None:
        if self.timestep_min is None or timestep < self.timestep_min:
            self.timestep_min = timestep
        if self.timestep_max is None or timestep > self.timestep_max:
            self.timestep_max = timestep

    def _guard_against_divergence(
        self,
        system: SystemState,
        speed_limit: float | None,
    ) -> None:
        for index, body in enumerate(system):
            if not all(map(math.isfinite, body)):
                raise SimulationDiverged(
                    f"body {index} reached a non-finite state {body}; "
                    f"the timestep is too coarse for this scenario or the "
                    f"bodies are collapsing onto each other"
                )
            if speed_limit is None:
                continue
            speed = _speed(body)
            if speed > speed_limit:
                raise SimulationDiverged(
                    f"body {index} reached a speed of {speed:.4g} m/s, more "
                    f"than {self.divergence_speed_factor:g}x its initial "
                    f"speed; the timestep is too coarse for this scenario or "
                    f"the bodies are approaching a collision"
                )

    def result(self) -> SystemResult:
        """Snapshot of the run as a :class:`SystemResult`."""
        return SystemResult(
            elapsed_time=self.t,
            steps=self.steps,
            timed_out=self.timed_out,
            timestep_min=self.timestep_min,
            timestep_max=self.timestep_max,
        )


def _rk4_step(
    system: SystemState,
    dt: float,
    gravity: SystemField,
) -> SystemState:
    """One classical RK4 step over the 6N-dimensional system."""
    k1 = system_derivatives(system, gravity)
    s2 = _advance(system, k1, dt / 2)
    k2 = system_derivatives(s2, gravity)
    s3 = _advance(system, k2, dt / 2)
    k3 = system_derivatives(s3, gravity)
    s4 = _advance(system, k3, dt)
    k4 = system_derivatives(s4, gravity)
    return _combine(system, k1, k2, k3, k4, dt)


def _advance(
    system: SystemState,
    derivative: SystemState,
    h: float,
) -> SystemState:
    return tuple(
        tuple(body[i] + h * derivative[body_index][i] for i in range(6))
        for body_index, body in enumerate(system)
    )


def _combine(
    system: SystemState,
    k1: SystemState,
    k2: SystemState,
    k3: SystemState,
    k4: SystemState,
    dt: float,
) -> SystemState:
    return tuple(
        tuple(
            system[body_index][i]
            + dt
            * (k1[body_index][i] + 2 * k2[body_index][i]
               + 2 * k3[body_index][i] + k4[body_index][i])
            / 6
            for i in range(6)
        )
        for body_index in range(len(system))
    )


def _speed(state: State) -> float:
    return math.hypot(state[VX], state[VY], state[VZ])


def _distance(first: State, second: State) -> float:
    return math.sqrt(
        (first[X] - second[X]) ** 2
        + (first[Y] - second[Y]) ** 2
        + (first[Z] - second[Z]) ** 2
    )


def _coerce_bodies(bodies: Any, min_separation: float) -> tuple[Body, ...]:
    """Validate the constructor input and return an immutable body tuple."""
    if not isinstance(bodies, (list, tuple)):
        raise TypeError(
            f"bodies must be a list or tuple, got {type(bodies).__name__}"
        )
    if len(bodies) < 1:
        raise ValueError(
            f"a system needs at least one body, got {len(bodies)}"
        )
    converted: list[Body] = []
    for index, item in enumerate(bodies):
        if not isinstance(item, Body):
            raise TypeError(
                f"bodies[{index}] must be a Body, got {type(item).__name__}"
            )
        mu = _finite(f"bodies[{index}].mu", item.mu)
        if mu <= 0.0:
            raise ValueError(
                f"bodies[{index}].mu must be greater than 0, got {mu}"
            )
        state = _coerce_state(item.state, f"bodies[{index}].state")
        converted.append(Body(mu=mu, state=state))
    _reject_unmodellable_separations(tuple(converted), min_separation)
    return tuple(converted)


def _coerce_state(state: Any, name: str) -> State:
    if isinstance(state, (str, bytes)) or not isinstance(state, (list, tuple)):
        raise TypeError(
            f"{name} must be a sequence of 6 numbers, "
            f"got {type(state).__name__}"
        )
    if len(state) != 6:
        raise ValueError(f"{name} must have 6 components, got {len(state)}")
    return tuple(
        _finite(f"{name}[{i}]", component) for i, component in enumerate(state)
    )


def _reject_unmodellable_separations(
    bodies: tuple[Body, ...],
    min_separation: float,
) -> None:
    minimum_squared = min_separation * min_separation
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            separation_squared = (
                (bodies[i].state[X] - bodies[j].state[X]) ** 2
                + (bodies[i].state[Y] - bodies[j].state[Y]) ** 2
                + (bodies[i].state[Z] - bodies[j].state[Z]) ** 2
            )
            if separation_squared == 0.0:
                raise ValueError(
                    f"bodies {i} and {j} start at the same position; "
                    f"the mutual gravitational force is singular"
                )
            if (
                min_separation > 0.0
                and separation_squared < minimum_squared
            ):
                raise ValueError(
                    f"bodies {i} and {j} start closer than "
                    f"min_separation={min_separation:g} m "
                    f"(distance {math.sqrt(separation_squared):.6g} m)"
                )


def _coerce_mus(mus: Sequence[float]) -> tuple[float, ...]:
    if isinstance(mus, (str, bytes)) or not isinstance(mus, (list, tuple)):
        raise TypeError(
            f"mus must be a list or tuple, got {type(mus).__name__}"
        )
    values = tuple(_finite(f"mus[{index}]", mu) for index, mu in enumerate(mus))
    for index, mu in enumerate(values):
        if mu <= 0.0:
            raise ValueError(f"mus[{index}] must be greater than 0, got {mu}")
    return values


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


def _non_negative(name: str, value: Any) -> float:
    number = _finite(name, value)
    if number < 0.0:
        raise ValueError(f"{name} must be at least 0, got {number}")
    return number
