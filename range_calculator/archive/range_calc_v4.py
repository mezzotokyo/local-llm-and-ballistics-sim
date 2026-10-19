"""Command line entry point: reads a launch scenario and prints the range.

All physics lives in :mod:`ballistics`; this module only handles input parsing,
unit conversion, and presentation.
"""

from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

from ballistics import ProjectileSimulator, SimulationDiverged, derivatives, ideal_range
from physics_config import DEFAULT_PARAMETERS, ProjectileConstants

DATA_PATH = Path(__file__).resolve().parent / "data.csv"

DEFAULT_VELOCITY_KMPH = 170.0
DEFAULT_ANGLE_DEG = 35.0

KMPH_TO_MPS = 1000 / 3600

__all__ = [
    "ProjectileConstants",
    "ProjectileSimulator",
    "SimulationDiverged",
    "derivatives",
    "ideal_range",
    "load_scenario",
    "main",
]


def load_scenario(path: Path | str | None = None) -> tuple[float, float]:
    """Read ``velocity_kmph, angle_deg`` and fall back to the defaults.

    A missing file, an unparsable number, or a short line all resolve to the
    default scenario instead of raising.
    """
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


def main(argv: list[str] | None = None) -> int:
    velocity_kmph, angle_deg = load_scenario(argv[0] if argv else None)

    velocity_mps = velocity_kmph * KMPH_TO_MPS
    angle_rad = math.radians(angle_deg)

    simulator = ProjectileSimulator(velocity_mps, angle_rad, DEFAULT_PARAMETERS)
    ideal = simulator.calculate_ideal_range()
    ground_range, flight_time = simulator.run_simulation()
    result = simulator.result()

    print("--- Simulation Results (RK4 Refactored) ---")
    print(f"Input Velocity: {velocity_kmph} km/h")
    print(f"Launch Angle: {angle_deg} deg")
    print("\n--- Range Comparison ---")
    print(f"Ideal Range (No Drag): {ideal:.2f} m")
    print(f"Realistic Range (RK4, With Drag): {ground_range:.2f} m")
    print(f"Actual Flight Time: {flight_time:.2f} s")
    if result.timed_out:
        print(
            f"WARNING: simulation stopped at the {DEFAULT_PARAMETERS.max_time:g} s "
            "time limit without reaching the ground"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))