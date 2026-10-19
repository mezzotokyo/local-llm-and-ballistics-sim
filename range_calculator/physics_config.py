"""Physical parameter profile: loading from config file and validation.

This module owns every physical constant used by the simulation and is
deliberately free of simulation logic so that it can be imported from tests,
the CLI, or any other entry point.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "physics_constants.json"

PositiveFields = (
    "max_time",
    "gravity",
    "mass",
    "diameter",
    "mu",
    "equatorial_radius",
    "scale_height",
)
NonNegativeFields = ("air_density", "drag_coefficient", "j2", "sea_level_density")


@dataclass(frozen=True)
class PhysicalParameters:
    """Immutable bundle of the parameters that define a simulation scenario.

    ``mu`` is the standard gravitational parameter G*M of the central body, used
    by :func:`ballistics.newtonian_gravity`; it is unrelated to the flat-earth
    ``gravity`` acceleration used by the default ballistics model. ``j2`` and
    ``equatorial_radius`` parametrise the oblateness perturbation
    (:func:`ballistics.j2_gravity`), while ``scale_height`` and
    ``sea_level_density`` parametrise the single-exponential atmosphere
    (:func:`ballistics.exponential_density`).
    """

    max_time: float = 300.0
    gravity: float = 9.81
    air_density: float = 1.225
    mass: float = 0.149
    diameter: float = 0.075
    drag_coefficient: float = 0.47
    mu: float = 3.986004418e14
    j2: float = 1.08263e-3
    equatorial_radius: float = 6.378137e6
    scale_height: float = 8500.0
    sea_level_density: float = 1.225

    def __post_init__(self) -> None:
        for name in PositiveFields:
            _check(name, getattr(self, name), minimum=0.0, strict=True)
        for name in NonNegativeFields:
            _check(name, getattr(self, name), minimum=0.0, strict=False)

    def frontal_area(self) -> float:
        """Cross-sectional area of the projectile (m^2)."""
        return math.pi * (self.diameter / 2) ** 2

    def drag_scaling_factor(self) -> float:
        """The factor k in F = -k * v * |v|, i.e. (1/2 * rho * A * Cd) / m."""
        return (
            0.5
            * self.air_density
            * self.frontal_area()
            * self.drag_coefficient
            / self.mass
        )

    def with_drag_scaling_factor(self, k: float) -> "PhysicalParameters":
        """Return a copy whose drag scaling factor equals ``k``.

        Used to keep the legacy ``{'drag_scaling_factor': k}`` mapping accepted by
        :class:`ballistics.ProjectileSimulator` working.
        """
        _check("drag_scaling_factor", k, minimum=0.0, strict=False)
        denominator = 0.5 * self.air_density * self.frontal_area()
        if denominator == 0.0:
            if k != 0.0:
                raise ValueError(
                    "drag_scaling_factor cannot be non-zero when air_density or "
                    "diameter is zero"
                )
            return replace(self, drag_coefficient=0.0)
        return replace(self, drag_coefficient=k * self.mass / denominator)


def _check(name: str, value: Any, minimum: float, strict: bool) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if strict and value <= minimum:
        raise ValueError(f"{name} must be greater than {minimum}, got {value}")
    if not strict and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")


def _as_float(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    return float(value)


def load_parameters(path: Path | str | None = None) -> PhysicalParameters:
    """Load the parameter profile from ``path`` (defaults to ``CONFIG_PATH``).

    Missing keys fall back to the built-in defaults, unknown keys raise, and a
    missing file yields the built-in defaults with a warning so that the tool
    keeps working outside a configured checkout.
    """
    config_path = Path(path) if path is not None else CONFIG_PATH
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        warnings.warn(
            f"physics config not found at {config_path}; using built-in defaults",
            stacklevel=2,
        )
        return PhysicalParameters()

    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path} is not valid JSON: {exc}") from exc

    if not isinstance(values, dict):
        raise TypeError(f"{config_path} must contain a JSON object")

    known = {field.name for field in fields(PhysicalParameters)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown keys in {config_path}: {sorted(unknown)}")

    overrides = {name: _as_float(name, value) for name, value in values.items()}
    return replace(PhysicalParameters(), **overrides)


DEFAULT_PARAMETERS = load_parameters()


class ProjectileConstants:
    """Backward-compatible view of the default profile from the config file.

    New code should pass a :class:`PhysicalParameters` instance around instead of
    reaching for class attributes.
    """

    MAX_TIME = DEFAULT_PARAMETERS.max_time
    GRAVITY = DEFAULT_PARAMETERS.gravity
    AIR_DENSITY = DEFAULT_PARAMETERS.air_density
    MASS = DEFAULT_PARAMETERS.mass
    DIAMETER = DEFAULT_PARAMETERS.diameter
    DRAG_COEFFICIENT = DEFAULT_PARAMETERS.drag_coefficient
    MU = DEFAULT_PARAMETERS.mu
    J2 = DEFAULT_PARAMETERS.j2
    EQUATORIAL_RADIUS = DEFAULT_PARAMETERS.equatorial_radius
    SCALE_HEIGHT = DEFAULT_PARAMETERS.scale_height
    SEA_LEVEL_DENSITY = DEFAULT_PARAMETERS.sea_level_density

    @staticmethod
    def default() -> PhysicalParameters:
        return DEFAULT_PARAMETERS

    @staticmethod
    def frontal_area() -> float:
        return DEFAULT_PARAMETERS.frontal_area()

    @staticmethod
    def drag_scaling_factor() -> float:
        return DEFAULT_PARAMETERS.drag_scaling_factor()


def coerce_parameters(constants: Any = None) -> PhysicalParameters:
    """Normalise the ``constants`` argument accepted by the simulator.

    Accepts ``None`` (default profile), a :class:`PhysicalParameters` instance,
    or a mapping keyed either by field names or by the legacy
    ``drag_scaling_factor`` entry.
    """
    if constants is None:
        return DEFAULT_PARAMETERS
    if isinstance(constants, PhysicalParameters):
        return constants
    if not isinstance(constants, Mapping):
        raise TypeError(
            "constants must be None, a PhysicalParameters, or a mapping, got "
            f"{type(constants).__name__}"
        )

    values = dict(constants)
    known = {field.name for field in fields(PhysicalParameters)}
    unknown = set(values) - known - {"drag_scaling_factor"}
    if unknown:
        raise ValueError(f"unknown constants keys: {sorted(unknown)}")

    parameters = replace(
        DEFAULT_PARAMETERS,
        **{name: _as_float(name, value) for name, value in values.items() if name in known},
    )
    if "drag_scaling_factor" in values:
        k = _as_float("drag_scaling_factor", values["drag_scaling_factor"])
        parameters = parameters.with_drag_scaling_factor(k)
    return parameters