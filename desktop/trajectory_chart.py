"""Trajectory chart drawn on a Tk canvas.

This is the desktop counterpart of ``webapp/src/components/TrajectoryChart.tsx``:
the same axis/grid layout, the same "nice" tick spacing, and the same colours.
No chart library is used, matching the web app's hand-rolled SVG.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Sequence

from gui_model import NBodyFrame, NBodyOutcome, SimulationOutcome, TrajectoryPoint

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

# Per-body colours for the N-body chart, cycled when a system has more bodies.
NBODY_COLORS: tuple[str, ...] = (
    "#2f80ed",
    "#f2994a",
    "#27ae60",
    "#eb5757",
    "#9b51e0",
    "#f2c94c",
    "#56ccf2",
    "#6fcf97",
)


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


def equal_aspect_domain(
    xs: Sequence[float],
    ys: Sequence[float],
    plot_width: float,
    plot_height: float,
    pad_fraction: float = 0.06,
) -> tuple[float, float, float, float]:
    """Bounds ``(x_lo, x_hi, y_lo, y_hi)`` fitting points at an equal scale.

    N-body orbits must keep their shape (a circle stays a circle), so after
    padding both spans by ``pad_fraction`` the smaller units-per-pixel side is
    expanded until both axes share one: ``span_x / plot_width`` equals
    ``span_y / plot_height``. An empty input gets a unit box; a degenerate
    span (all points equal on an axis) is widened to 1 m before padding.
    """
    if not xs or not ys:
        return -1.0, 1.0, -1.0, 1.0
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    span_x = max(x_hi - x_lo, 1.0)
    span_y = max(y_hi - y_lo, 1.0)
    span_x *= 1.0 + 2.0 * pad_fraction
    span_y *= 1.0 + 2.0 * pad_fraction
    if plot_width > 0 and plot_height > 0:
        scale = max(span_x / plot_width, span_y / plot_height)
        span_x = max(span_x, scale * plot_width)
        span_y = max(span_y, scale * plot_height)
    x_center = (x_lo + x_hi) / 2.0
    y_center = (y_lo + y_hi) / 2.0
    return (
        x_center - span_x / 2.0,
        x_center + span_x / 2.0,
        y_center - span_y / 2.0,
        y_center + span_y / 2.0,
    )


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


class NBodyChart(tk.Canvas):
    """A canvas rendering an N-body run frame by frame.

    The playback slider drives :meth:`set_frame`: each body draws its trail up
    to the current frame, a marker at its current position, and a colour
    legend so several bodies stay distinguishable. The domain is computed once
    in :meth:`show` over *all* frames at an equal aspect scale, so the view does
    not jump or distort while scrubbing. :meth:`set_focus` re-centres the view
    on a chosen body (positions are drawn relative to it) so a small orbit next
    to a much larger one stays visible.
    """

    marker_radius = 6

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            background=COLOR_BACKGROUND,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            **kwargs,
        )
        self._frames: Sequence[NBodyFrame] = ()
        self._names: tuple[str, ...] = ()
        self._index = 0
        # Display centre: -1 keeps the origin (the barycentre); an index centres
        # the view on that body's instantaneous position.
        self._focus = -1
        self._xs: list[float] = []
        self._ys: list[float] = []
        self.bind("<Configure>", lambda _event: self._redraw())

    @property
    def frame_count(self) -> int:
        """Number of recorded frames of the loaded run."""
        return len(self._frames)

    @property
    def current_index(self) -> int:
        """Index of the frame currently displayed."""
        return self._index

    def show(self, outcome: NBodyOutcome, focus: int = -1) -> None:
        """Load a completed run and display its first frame.

        ``focus`` selects the display centre: ``-1`` keeps the origin (the
        barycentre), any other value centres the view on that body so its
        motion fills the plot however small it is next to the rest of the
        system.
        """
        self._frames = tuple(outcome.frames)
        self._names = tuple(spec.name for spec in outcome.conditions.bodies)
        self._index = 0
        self._focus = max(-1, min(int(focus), len(self._names) - 1))
        self._recompute_domain()
        self._redraw()

    def set_focus(self, index: int) -> int:
        """Centre the view on a body (``-1`` for the origin); returns it."""
        clamped = max(-1, min(int(index), len(self._names) - 1))
        if clamped != self._focus:
            self._focus = clamped
            self._recompute_domain()
            self._redraw()
        return clamped

    def _relative(self, frame: NBodyFrame, body_index: int) -> tuple[float, float]:
        position = frame.positions[body_index]
        if 0 <= self._focus < len(frame.positions):
            origin = frame.positions[self._focus]
            return position[0] - origin[0], position[1] - origin[1]
        return position[0], position[1]

    def _recompute_domain(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        for frame in self._frames:
            for body_index in range(len(frame.positions)):
                x, y = self._relative(frame, body_index)
                xs.append(x)
                ys.append(y)
        self._xs = xs
        self._ys = ys

    def set_frame(self, index: int) -> int:
        """Jump to ``index`` (clamped to the recorded frames); returns it."""
        if not self._frames:
            return 0
        clamped = max(0, min(int(index), len(self._frames) - 1))
        if clamped != self._index:
            self._index = clamped
            self._redraw()
        return clamped

    def clear(self) -> None:
        """Remove the current run."""
        self._frames = ()
        self._names = ()
        self._index = 0
        self._focus = -1
        self._xs = []
        self._ys = []
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        plot_width = width - MARGIN["left"] - MARGIN["right"]
        plot_height = height - MARGIN["top"] - MARGIN["bottom"]
        if plot_width <= 1 or plot_height <= 1 or not self._frames:
            return

        x_lo, x_hi, y_lo, y_hi = equal_aspect_domain(
            self._xs, self._ys, plot_width, plot_height
        )

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

        frame = self._frames[self._index]
        radius = self.marker_radius
        for body_index, name in enumerate(self._names):
            color = NBODY_COLORS[body_index % len(NBODY_COLORS)]
            coords: list[float] = []
            for past in self._frames[: self._index + 1]:
                if body_index < len(past.positions):
                    rx, ry = self._relative(past, body_index)
                    coords.extend((sx(rx), sy(ry)))
            if len(coords) >= 4:
                self.create_line(*coords, fill=color, width=2)
            if body_index < len(frame.positions):
                rx, ry = self._relative(frame, body_index)
                center_x, center_y = sx(rx), sy(ry)
                self.create_oval(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    fill=color,
                    outline=COLOR_BACKGROUND,
                    width=2,
                )
                self.create_text(
                    center_x + radius + 4,
                    center_y,
                    text=name,
                    fill=color,
                    anchor="w",
                    font=("", 10, "bold"),
                )

        for body_index, name in enumerate(self._names):
            color = NBODY_COLORS[body_index % len(NBODY_COLORS)]
            legend_y = top + 12 + body_index * 16
            self.create_oval(
                left + 8, legend_y - 4, left + 16, legend_y + 4,
                fill=color, outline=COLOR_BACKGROUND,
            )
            self.create_text(
                left + 22, legend_y, text=name, fill=COLOR_AXIS_LABEL, anchor="w"
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
            text="vertical distance y (m)",
            fill=COLOR_AXIS_LABEL,
            angle=90,
            anchor="center",
        )
