"""Trajectory chart drawn on a Tk canvas.

This is the desktop counterpart of ``webapp/src/components/TrajectoryChart.tsx``:
the same axis/grid layout, the same "nice" tick spacing, and the same colours.
No chart library is used, matching the web app's hand-rolled SVG.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Sequence

from gui_model import SimulationOutcome, TrajectoryPoint

MARGIN = {"top": 28, "right": 28, "bottom": 52, "left": 68}

VIEW_XY = "xy"
VIEW_XZ = "xz"
VIEWS = (VIEW_XY, VIEW_XZ)

COLOR_GRID = "#e5edf5"
COLOR_AXIS = "#9fb3c8"
COLOR_TICK = "#7b8794"
COLOR_AXIS_LABEL = "#52606d"
COLOR_TRAJECTORY = "#2f80ed"
COLOR_IDEAL = "#f2994a"
COLOR_IDEAL_LABEL = "#b45309"
COLOR_LAUNCH = "#27ae60"
COLOR_LANDING = "#eb5757"
COLOR_BODY = "#52606d"
COLOR_BACKGROUND = "#ffffff"
COLOR_BORDER = "#d9e2ec"


def nice_step(value_range: float, count: int) -> float:
    """A round tick spacing close to ``value_range / count``.

    Port of ``niceStep`` in ``TrajectoryChart.tsx``.
    """
    if value_range <= 0:
        return 1.0
    raw = value_range / count
    magnitude = 10.0 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def ticks(maximum: float, count: int) -> list[float]:
    """Tick values from 0 up to ``maximum`` (inclusive where it lands on a step)."""
    step = nice_step(maximum, count)
    values: list[float] = []
    value = 0.0
    while value <= maximum + step / 2:
        values.append(round(value, 6))
        value += step
    return values


def axis_ticks(low: float, high: float, count: int) -> list[float]:
    """Round tick values covering ``[low, high]`` at a "nice" step.

    Extends :func:`ticks` to domains that go negative, which orbits need.
    """
    step = nice_step(high - low, count)
    start = math.floor(low / step) * step
    values: list[float] = []
    value = start
    while value <= high + step / 2:
        if value >= low - step / 2:
            values.append(round(value, 6))
        value += step
    return values


def _vertical_values(
    points: Sequence[TrajectoryPoint], view: str
) -> list[float]:
    """The plotted height for each point: ``y`` side-on, ``z`` top-down."""
    if view == VIEW_XZ:
        return [point.z for point in points]
    if view == VIEW_XY:
        return [point.y for point in points]
    raise ValueError(f"unknown view: {view!r}")


def chart_domain(
    points: Sequence[TrajectoryPoint],
    ideal_range: float | None,
    ground_range: float | None,
    central_body: bool,
    view: str = VIEW_XY,
) -> tuple[float, float, float, float]:
    """Bounds ``(x_lo, x_hi, y_lo, y_hi)`` that fit a trajectory for plotting.

    Central-gravity runs pass ``central_body=True``: the origin (the gravitating
    centre) is included and the bounds may go negative, so an orbit is not
    clipped. Flat-surface runs pin both minima to 0 and reproduce the historical
    ``x * 1.05`` / ``y * 1.15`` scaling. ``view`` chooses the vertical axis
    (side-on height ``"xy"`` or top-down lateral offset ``"xz"``).
    """
    xs = [point.x for point in points]
    ys = _vertical_values(points, view)
    if ideal_range is not None and ideal_range > 0:
        xs.append(ideal_range)
    if ground_range is not None and ground_range > 0:
        xs.append(ground_range)

    if not central_body:
        y_lo = min(ys + [0.0])
        return 0.0, max(xs + [1.0]) * 1.05, y_lo, max(ys + [1.0]) * 1.15

    x_lo, x_hi = min(xs + [0.0]), max(xs + [0.0])
    y_lo, y_hi = min(ys + [0.0]), max(ys + [0.0])
    span = max(x_hi - x_lo, y_hi - y_lo, 1.0)
    pad = span * 0.06
    return x_lo - pad, x_hi + pad, y_lo - pad, y_hi + pad


class TrajectoryChart(tk.Canvas):
    """A canvas that renders one simulation's trajectory and ideal-range line."""

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            background=COLOR_BACKGROUND,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            **kwargs,
        )
        self._trajectory: Sequence[TrajectoryPoint] = []
        self._ideal_range: float | None = None
        self._ground_range: float | None = None
        self._central_body = False
        self._view = VIEW_XY
        self.bind("<Configure>", lambda _event: self._redraw())

    def show(self, outcome: SimulationOutcome, view: str | None = None) -> None:
        """Render the trajectory and markers for a completed simulation."""
        self._trajectory = outcome.trajectory
        self._ideal_range = outcome.result.ideal_range
        self._ground_range = outcome.result.ground_range
        self._central_body = outcome.orbital is not None
        if view is not None:
            self._view = view
        self._redraw()

    def set_view(self, view: str) -> None:
        """Switch the vertical axis (``"xy"`` side-on / ``"xz"`` top-down)."""
        if view not in VIEWS:
            raise ValueError(f"unknown view: {view!r}")
        if view != self._view:
            self._view = view
            self._redraw()

    def clear(self) -> None:
        """Remove the current drawing."""
        self._trajectory = []
        self._ideal_range = None
        self._ground_range = None
        self._central_body = False
        self._view = VIEW_XY
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        plot_width = width - MARGIN["left"] - MARGIN["right"]
        plot_height = height - MARGIN["top"] - MARGIN["bottom"]
        if plot_width <= 1 or plot_height <= 1:
            return

        points = self._trajectory
        x_lo, x_hi, y_lo, y_hi = chart_domain(
            points,
            self._ideal_range,
            self._ground_range,
            self._central_body,
            self._view,
        )

        def vertical(point: TrajectoryPoint) -> float:
            return point.z if self._view == VIEW_XZ else point.y

        def sx(x: float) -> float:
            return MARGIN["left"] + (x - x_lo) / (x_hi - x_lo) * plot_width

        def sy(y: float) -> float:
            return MARGIN["top"] + plot_height - (y - y_lo) / (y_hi - y_lo) * plot_height

        left = MARGIN["left"]
        top = MARGIN["top"]
        right = left + plot_width
        bottom = top + plot_height

        y_axis = sy(0.0) if y_lo <= 0.0 <= y_hi else bottom
        x_axis = sx(0.0) if x_lo <= 0.0 <= x_hi else left

        for value in axis_ticks(y_lo, y_hi, 5):
            y = sy(value)
            self.create_line(left, y, right, y, fill=COLOR_GRID)
            self.create_text(
                x_axis - 8, y, text=f"{value:.0f}", fill=COLOR_TICK, anchor="e"
            )

        for value in axis_ticks(x_lo, x_hi, 6):
            x = sx(value)
            self.create_line(x, top, x, bottom, fill=COLOR_GRID)
            self.create_text(
                x, y_axis + 14, text=f"{value:.0f}", fill=COLOR_TICK, anchor="n"
            )

        self.create_line(left, y_axis, right, y_axis, fill=COLOR_AXIS, width=2)
        self.create_line(x_axis, top, x_axis, bottom, fill=COLOR_AXIS, width=2)

        if self._central_body:
            self.create_oval(
                sx(0.0) - 6,
                sy(0.0) - 6,
                sx(0.0) + 6,
                sy(0.0) + 6,
                fill=COLOR_BODY,
                outline=COLOR_BACKGROUND,
            )

        if self._ideal_range is not None and self._ideal_range > 0:
            x = sx(self._ideal_range)
            self.create_line(x, top, x, bottom, fill=COLOR_IDEAL, dash=(6, 5))
            self.create_text(
                x - 6,
                top + 14,
                text=f"ideal {self._ideal_range:.1f} m",
                fill=COLOR_IDEAL_LABEL,
                anchor="e",
            )

        if points:
            coords: list[float] = []
            for point in points:
                coords.extend((sx(point.x), sy(vertical(point))))
            if len(coords) >= 4:
                self.create_line(*coords, fill=COLOR_TRAJECTORY, width=3)

            launch = points[0]
            last = points[-1]
            if not self._central_body:
                self.create_oval(
                    sx(last.x) - 5,
                    sy(vertical(last)) - 5,
                    sx(last.x) + 5,
                    sy(vertical(last)) + 5,
                    fill=COLOR_LANDING,
                    outline=COLOR_BACKGROUND,
                )
            self.create_oval(
                sx(launch.x) - 5,
                sy(vertical(launch)) - 5,
                sx(launch.x) + 5,
                sy(vertical(launch)) + 5,
                fill=COLOR_LAUNCH,
                outline=COLOR_BACKGROUND,
            )

        self.create_text(
            left + plot_width / 2,
            height - 10,
            text="horizontal distance x (m)",
            fill=COLOR_AXIS_LABEL,
            anchor="s",
        )
        self.create_text(
            16,
            top + plot_height / 2,
            text="lateral z (m)" if self._view == VIEW_XZ else "height y (m)",
            fill=COLOR_AXIS_LABEL,
            angle=90,
            anchor="center",
        )
