"""Orbital-element analysis for the two-body problem.

Pure functions over the state vector produced by :mod:`ballistics`; no file I/O
and no simulation logic. The position is taken as the offset from the central
body's centre and ``mu`` is that body's standard gravitational parameter G*M.

The classical element set is derived from the specific energy and the
eccentricity/angular-momentum vectors, so the same code handles circular,
elliptical, parabolic, and hyperbolic states. Open orbits (``e >= 1``) have no
apoapsis or period, which are therefore reported as ``None``.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from ballistics import State, X, Y, Z, VX, VY, VZ


class OrbitalElements(NamedTuple):
    """Osculating orbital elements of a single state vector (SI units)."""

    specific_energy: float
    semi_major_axis: float | None
    eccentricity: float
    periapsis: float
    apoapsis: float | None
    period: float | None
    inclination_rad: float


def orbital_elements(state: State, mu: float) -> OrbitalElements:
    """Return the orbital elements of ``state`` about a body with parameter ``mu``.

    Raises:
        ValueError: the position is at the central body (``|r| == 0``), where the
            elements are undefined, or ``mu`` is not positive.
    """
    if mu <= 0.0:
        raise ValueError(f"mu must be greater than 0, got {mu}")

    rx, ry, rz = state[X], state[Y], state[Z]
    vx, vy, vz = state[VX], state[VY], state[VZ]

    radius_squared = rx * rx + ry * ry + rz * rz
    if radius_squared == 0.0:
        raise ValueError("orbital elements are undefined at the central body")
    radius = math.sqrt(radius_squared)
    speed_squared = vx * vx + vy * vy + vz * vz

    energy = speed_squared / 2.0 - mu / radius
    semi_major_axis = None if energy == 0.0 else -mu / (2.0 * energy)

    radial_dot = rx * vx + ry * vy + rz * vz
    factor = speed_squared - mu / radius
    ex = (factor * rx - radial_dot * vx) / mu
    ey = (factor * ry - radial_dot * vy) / mu
    ez = (factor * rz - radial_dot * vz) / mu
    eccentricity = math.sqrt(ex * ex + ey * ey + ez * ez)

    hx = ry * vz - rz * vy
    hy = rz * vx - rx * vz
    hz = rx * vy - ry * vx
    angular_momentum = math.sqrt(hx * hx + hy * hy + hz * hz)

    periapsis = angular_momentum * angular_momentum / (mu * (1.0 + eccentricity))

    if eccentricity < 1.0 and semi_major_axis is not None:
        apoapsis = semi_major_axis * (1.0 + eccentricity)
        period = 2.0 * math.pi * math.sqrt(semi_major_axis**3 / mu)
    else:
        apoapsis = None
        period = None

    if angular_momentum == 0.0:
        inclination_rad = 0.0
    else:
        inclination_rad = math.acos(
            max(-1.0, min(1.0, hz / angular_momentum))
        )

    return OrbitalElements(
        specific_energy=energy,
        semi_major_axis=semi_major_axis,
        eccentricity=eccentricity,
        periapsis=periapsis,
        apoapsis=apoapsis,
        period=period,
        inclination_rad=inclination_rad,
    )
