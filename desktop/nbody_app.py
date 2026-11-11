"""Desktop GUI for mutual-gravity N-body systems.

This is the third desktop entry point (see :mod:`app_common`). It shows the
scenario preset (Sun-centred or Earth-centred), the per-body inputs (name,
bulk density, radius, state) which stay freely editable after a preset is
loaded, and the timestep / time span. A preset starts from its central body
alone at the origin at rest; from the second body on, each body can be loaded
from a catalogue of the Sun, the planets, and the Moon, which seeds a circular
orbit about the central body. Each body's ``mu`` is derived from its density
and radius (``mu = G * density * 4/3 pi r^3``) and shown read-only. A run is
recorded frame by frame and played back with a slider under the chart.

Run it with::

    python3 desktop/nbody_app.py
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

import errors
import gui_model
from app_common import BaseApp
from gui_model import NBodyConditions, NBodyOutcome
from trajectory_chart import NBodyChart

# Playback length in wall-clock seconds; the slider advances
# ``frame_count / (PLAY_SECONDS * PLAY_FPS)`` frames per tick.
PLAY_SECONDS = 12.0
PLAY_FPS = 30

# The UI row order must match gui_model.NBodyRow (name, density, radius,
# then the six state components).
NBODY_ROW_ORDER: tuple[str, ...] = (
    "name", "density", "radius", "x", "y", "z", "vx", "vy", "vz",
)

BODY_FIELD_LABELS: dict[str, str] = {
    "name": "名前",
    "density": "体積密度 (kg/m^3)",
    "radius": "半径 (m)",
    "x": "x (m)",
    "y": "y (m)",
    "z": "z (m)",
    "vx": "vx (m/s)",
    "vy": "vy (m/s)",
    "vz": "vz (m/s)",
}

# Entry rows inside one body group; the mu line below them is read-only.
BODY_ENTRY_ROWS: tuple[tuple[str, ...], ...] = (
    ("name", "density", "radius"),
    ("x", "y", "z"),
    ("vx", "vy", "vz"),
)

# Per-body catalogue dropdown: the catalogue names plus a sentinel that leaves
# the hand-entered values untouched (used by the central body and by "add").
CUSTOM_CATALOG_LABEL = "（カスタム）"
CATALOG_LABELS: tuple[str, ...] = tuple(
    entry[0] for entry in gui_model.NBODY_CATALOG
) + (CUSTOM_CATALOG_LABEL,)

# Label of the sentinel the focus selector uses for the barycentre (the system
# centre of mass, i.e. the origin once the preset momentum is cancelled).
BARYCENTRE_LABEL = "重心（原点）"


class _ScrolledFrame(ttk.Frame):
    """A vertically scrollable container: canvas + scrollbar + inner frame.

    The body-input column grows with every added body; without scrolling it
    would eventually push the chart out of the window. The inner frame is the
    public surface: widgets are packed into ``self.inner`` as usual. The canvas
    keeps a small requested height so the frame stretches to the space it is
    given (via grid ``weight``) instead of demanding a fixed block that would
    push the fixed controls below it off-screen.
    """

    def __init__(self, master: tk.Misc, height: int = 160) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(
            self, highlightthickness=0, borderwidth=0, height=height
        )
        scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.inner = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            ),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(window, width=event.width),
        )
        # Windows / macOS send MouseWheel; some X11 builds send Button-4/5.
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind(
            "<Button-4>", lambda _event: self.canvas.yview_scroll(-1, "units")
        )
        self.canvas.bind(
            "<Button-5>", lambda _event: self.canvas.yview_scroll(1, "units")
        )

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def fit_content_width(self) -> None:
        """Make the canvas at least as wide as its content needs.

        A Tk canvas has no natural width — its ``-width`` default is ``10c``
        (about 378 px here) — and ``inner`` is clamped to the canvas, so a row
        of three 131 px entry fields would be compressed and truncate its
        values. Widening the window does not help on its own: the column this
        sits in is sticky ``nsw`` and never grows with the window.
        """
        self.update_idletasks()
        required = self.inner.winfo_reqwidth()
        if required > self.canvas.winfo_width():
            self.canvas.configure(width=required)


class NBodyApp(BaseApp):
    """The mutual-gravity N-body window."""

    def __init__(self) -> None:
        super().__init__(
            title="Range Calculator Desktop — 多体 (N-body)",
            geometry="1200x800",
            # 650 collapsed the body list to 3 px (160 requested); 780 leaves it
            # 133 px so the per-body inputs stay reachable.
            minsize=(900, 780),
        )

        self._preset_var = tk.StringVar(value=gui_model.NBODY_PRESETS[0][1])
        self._adaptive_var = tk.BooleanVar(value=gui_model.DEFAULT_ADAPTIVE)
        self._dt_var = tk.StringVar()
        self._time_var = tk.StringVar()
        self._frame_var = tk.DoubleVar(value=0.0)
        self._focus_var = tk.StringVar(value=BARYCENTRE_LABEL)
        self._body_vars: list[dict[str, tk.StringVar]] = []
        self._last_outcome: NBodyOutcome | None = None
        self._playing = False
        self._play_after_id: str | None = None

        self._build_ui()
        self._load_preset()
        self.activate()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        # Side-by-side layout: the input / result column is scrollable on the
        # left, so the chart on the right always keeps its height no matter
        # how many bodies are configured.
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            header,
            text="Range Calculator Desktop — 多体 (N-body)",
            font=("", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header, text="相互重力（点質量）の多体シミュレーション"
        ).pack(anchor="w")

        body = ttk.Frame(self, padding=(20, 8, 20, 12))
        body.grid(row=1, column=0, columnspan=2, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self._build_controls(left)
        self._build_results(left)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._chart = NBodyChart(right)
        self._chart.grid(row=0, column=0, sticky="nsew")
        self._build_playback(right)

    def _build_controls(self, parent: ttk.Frame) -> None:
        # Only the body groups scroll. The preset, the timestep / time span,
        # the add/remove buttons, and the run button stay pinned in the panel
        # so they never scroll out of reach however many bodies are configured.
        # Grid (not pack) keeps the pinned rows at their natural height and
        # lets the body list absorb any resizing, so shrinking the window
        # never clips the run button or the error message.
        panel = ttk.LabelFrame(parent, text="N-body conditions", padding=14)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        top = ttk.Frame(panel)
        top.grid(row=0, column=0, sticky="ew")

        preset_row = ttk.Frame(top)
        preset_row.pack(fill="x", pady=(0, 8))
        ttk.Label(preset_row, text="プリセット").pack(side="left")
        preset_box = ttk.Combobox(
            preset_row,
            textvariable=self._preset_var,
            values=[label for _value, label in gui_model.NBODY_PRESETS],
            state="readonly",
            width=28,
        )
        preset_box.pack(side="right")
        preset_box.bind("<<ComboboxSelected>>", self._load_preset)

        dt_row = ttk.Frame(top)
        dt_row.pack(fill="x")
        ttk.Label(dt_row, text="刻み幅 dt (s)").pack(side="left")
        dt_entry = ttk.Entry(dt_row, textvariable=self._dt_var, width=14)
        dt_entry.pack(side="right")
        dt_entry.bind("<Return>", lambda _event: self._run())

        time_row = ttk.Frame(top)
        time_row.pack(fill="x", pady=(6, 0))
        ttk.Label(time_row, text="最大時間 (s)").pack(side="left")
        time_entry = ttk.Entry(time_row, textvariable=self._time_var, width=14)
        time_entry.pack(side="right")
        time_entry.bind("<Return>", lambda _event: self._run())

        ttk.Checkbutton(
            top,
            text="adaptive 刻み（dt を上限に最短のペア周期で自動短縮）",
            variable=self._adaptive_var,
        ).pack(anchor="w", pady=(6, 0))

        ttk.Label(
            panel,
            text="天体（天体 1 が中心。2 つ目以降は周回対象とカタログで配置）",
        ).grid(row=1, column=0, sticky="w", pady=(10, 4))

        self._controls_scroll = _ScrolledFrame(panel)
        self._controls_scroll.grid(row=2, column=0, sticky="nsew")
        self._bodies_container = self._controls_scroll.inner

        bottom = ttk.Frame(panel)
        bottom.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        buttons = ttk.Frame(bottom)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="天体を追加", command=self._add_body).pack(
            side="left"
        )
        ttk.Button(
            buttons, text="最後の天体を削除", command=self._remove_body
        ).pack(side="left", padx=(8, 0))

        self._run_button = ttk.Button(
            bottom, text=self.run_label, command=self._run
        )
        self._run_button.pack(anchor="w", pady=(12, 0))

        ttk.Label(
            bottom,
            textvariable=self._error_var,
            foreground="#b91c1c",
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def _build_results(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Result", padding=14)
        panel.grid(row=1, column=0, sticky="new", pady=(12, 0))
        panel.columnconfigure(1, weight=1)
        self._metrics_panel = panel

        ttk.Label(
            panel,
            textvariable=self._warning_var,
            foreground="#92400e",
            wraplength=340,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._render_metric_rows(gui_model.DEFAULT_NBODY_METRIC_ROWS)

    def _build_playback(self, parent: ttk.Frame) -> None:
        focus_row = ttk.Frame(parent)
        focus_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(focus_row, text="表示中心").pack(side="left")
        self._focus_box = ttk.Combobox(
            focus_row,
            textvariable=self._focus_var,
            values=[],
            state="readonly",
            width=22,
        )
        self._focus_box.pack(side="right")
        self._focus_box.bind("<<ComboboxSelected>>", self._on_focus_selected)

        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        row.columnconfigure(1, weight=1)

        self._play_button = ttk.Button(
            row, text="再生", command=self._toggle_playback, width=6
        )
        self._play_button.grid(row=0, column=0, sticky="w")

        self._frame_scale = ttk.Scale(
            row,
            from_=0,
            to=0,
            orient="horizontal",
            variable=self._frame_var,
            command=self._on_frame_change,
        )
        self._frame_scale.grid(row=0, column=1, sticky="ew", padx=12)

        self._time_label = ttk.Label(row, text="t = -", width=26, anchor="e")
        self._time_label.grid(row=0, column=2, sticky="e")

    # ------------------------------------------------------------------ helpers

    def _load_preset(self, *_args: object) -> None:
        value = self._selected_value(self._preset_var, gui_model.NBODY_PRESETS)
        conditions = gui_model.nbody_preset_conditions(value)
        self._dt_var.set(f"{conditions.dt:g}")
        self._time_var.set(f"{conditions.max_time:.0f}")
        specs = conditions.bodies
        self._body_vars = [
            self._fields_from_spec(spec, index, [body.name for body in specs[:index]])
            for index, spec in enumerate(specs)
        ]
        self._rebuild_body_groups()

    @staticmethod
    def _fields_from_spec(
        spec: gui_model.NBodySpec,
        index: int,
        prior_names: list[str],
    ) -> dict[str, tk.StringVar]:
        host_index = 0
        if index > 0:
            primary = gui_model.nbody_catalog_primary(spec.name)
            if primary in prior_names:
                host_index = prior_names.index(primary)
        fields: dict[str, tk.StringVar] = {
            "name": tk.StringVar(value=spec.name),
            "density": tk.StringVar(value=repr(spec.density)),
            "radius": tk.StringVar(value=repr(spec.radius)),
            # Per-body catalogue selector (index >= 1); the sentinel keeps the
            # hand-entered values, which is also the initial state.
            "catalog": tk.StringVar(value=CUSTOM_CATALOG_LABEL),
            # Which body this one orbits about (an index into the body list).
            # The natural primary (the Earth for the Moon and the satellite)
            # is chosen when it is already present.
            "host": tk.StringVar(value=str(host_index)),
            # Height above the host surface. Empty means "use the catalogue's
            # own distance"; when set it places any body (satellite, or e.g. the
            # Moon around Mars) at host_radius + altitude.
            "altitude": tk.StringVar(value=""),
            # Read-only display of the derived mu; kept in sync by traces.
            "mu_display": tk.StringVar(value=f"μ = {spec.mu:.6e} m^3/s^2"),
        }
        for key, value in zip(gui_model.NBODY_STATE_FIELDS, spec.state):
            fields[key] = tk.StringVar(value=repr(value))

        def sync_mu(
            *_args: object, density=fields["density"], radius=fields["radius"],
            display=fields["mu_display"],
        ) -> None:
            try:
                mu = gui_model.nbody_mu(
                    float(density.get()), float(radius.get())
                )
            except ValueError:
                display.set("μ = -")
            else:
                display.set(f"μ = {mu:.6e} m^3/s^2")

        fields["density"].trace_add("write", sync_mu)
        fields["radius"].trace_add("write", sync_mu)
        return fields

    def _rebuild_body_groups(self) -> None:
        for child in self._bodies_container.winfo_children():
            child.destroy()
        for index, fields in enumerate(self._body_vars):
            title = "天体 1（中心）" if index == 0 else f"天体 {index + 1}"
            group = ttk.LabelFrame(
                self._bodies_container, text=title, padding=8
            )
            group.pack(fill="x", pady=(0, 6))
            if index == 0:
                ttk.Label(
                    group,
                    text="中心天体（初期値は座標原点・静止）",
                    font=("", 9),
                ).pack(anchor="w", pady=(0, 4))
            else:
                self._build_catalog_row(group, index, fields)
            for row_fields in BODY_ENTRY_ROWS:
                entry_row = ttk.Frame(group)
                entry_row.pack(fill="x", pady=(0, 4))
                for field in row_fields:
                    cell = ttk.Frame(entry_row)
                    cell.pack(side="left", expand=True, fill="x", padx=(0, 6))
                    ttk.Label(
                        cell, text=BODY_FIELD_LABELS[field], font=("", 9)
                    ).pack(anchor="w")
                    entry = ttk.Entry(cell, textvariable=fields[field], width=13)
                    entry.pack(fill="x")
                    entry.bind("<Return>", lambda _event: self._run())
            ttk.Label(
                group, textvariable=fields["mu_display"], font=("", 9)
            ).pack(anchor="w", pady=(2, 0))
        # The row width depends on which fields are present, so the canvas is
        # re-measured after every rebuild (preset, add, remove).
        self._controls_scroll.fit_content_width()

    @staticmethod
    def _host_label(index: int) -> str:
        # Positional only: the label must not imply a fixed identity, so the
        # Moon can be placed around any body (e.g. renamed to Mars).
        return f"天体 {index + 1}"

    def _build_catalog_row(
        self, group: ttk.LabelFrame, index: int, fields: dict[str, tk.StringVar]
    ) -> None:
        # 周回対象: the combobox lists the preceding bodies by label while the
        # "host" variable stores the selected *index*, so it is driven via
        # ``current`` (not a textvariable) to keep label and index in step.
        host_row = ttk.Frame(group)
        host_row.pack(fill="x", pady=(0, 4))
        ttk.Label(host_row, text="周回対象", font=("", 9)).pack(side="left")
        host_box = ttk.Combobox(
            host_row,
            values=[self._host_label(i) for i in range(index)],
            state="readonly",
            width=18,
        )
        host_box.pack(side="right")
        host_box.current(min(self._host_index(fields), index - 1))

        def on_host_selected(_event: object) -> None:
            fields["host"].set(str(host_box.current()))
            self._apply_catalog(index)

        host_box.bind("<<ComboboxSelected>>", on_host_selected)

        catalog_row = ttk.Frame(group)
        catalog_row.pack(fill="x", pady=(0, 4))
        ttk.Label(catalog_row, text="天体カタログ", font=("", 9)).pack(side="left")
        catalog_box = ttk.Combobox(
            catalog_row,
            textvariable=fields["catalog"],
            values=list(CATALOG_LABELS),
            state="readonly",
            width=12,
        )
        catalog_box.pack(side="right")

        def on_catalog_selected(_event: object) -> None:
            self._reset_altitude_default(fields)
            self._apply_catalog(index)

        catalog_box.bind("<<ComboboxSelected>>", on_catalog_selected)

        altitude_row = ttk.Frame(group)
        altitude_row.pack(fill="x", pady=(0, 4))
        ttk.Label(
            altitude_row, text="高度 (m)（周回対象の地表から）", font=("", 9)
        ).pack(side="left")
        altitude_entry = ttk.Entry(
            altitude_row, textvariable=fields["altitude"], width=12
        )
        altitude_entry.pack(side="right")
        altitude_entry.bind(
            "<Return>", lambda _event: self._apply_catalog(index)
        )

    def _apply_catalog(self, index: int) -> None:
        """Load a catalogue body's density/radius and a circular orbit state.

        The body is placed in a circular orbit about the currently selected
        host body (周回対象), whose mu and position come from the live inputs,
        so an edited host is honoured. The satellite takes its radius from the
        altitude field instead. The ``（カスタム）`` sentinel leaves the inputs
        untouched.
        """
        fields = self._body_vars[index]
        label = fields["catalog"].get()
        if label == CUSTOM_CATALOG_LABEL or index == 0:
            return
        host_fields, host_index = self._host_fields(index)
        try:
            host_radius = float(host_fields["radius"].get())
            host_density = float(host_fields["density"].get())
            host_state = tuple(
                float(host_fields[field].get())
                for field in gui_model.NBODY_STATE_FIELDS
            )
        except ValueError:
            self._error_var.set(
                f"天体 {host_index + 1}（周回対象）の密度・半径・状態を"
                f"先に数値で入力してください。"
            )
            return
        try:
            spec = gui_model.nbody_catalog_spec(
                label,
                host_state,
                gui_model.nbody_mu(host_density, host_radius),
                host_radius,
                self._altitude(fields),
            )
        except (KeyError, ValueError) as exc:
            self._error_var.set(f"カタログの軌道を設定できません: {exc}")
            return
        self._error_var.set("")
        fields["name"].set(spec.name)
        fields["density"].set(repr(spec.density))
        fields["radius"].set(repr(spec.radius))
        for key, value in zip(gui_model.NBODY_STATE_FIELDS, spec.state):
            fields[key].set(repr(value))

    @staticmethod
    def _host_index(fields: dict[str, tk.StringVar]) -> int:
        try:
            return int(float(fields["host"].get()))
        except ValueError:
            return 0

    def _host_fields(
        self, index: int
    ) -> tuple[dict[str, tk.StringVar], int]:
        host_index = max(0, min(self._host_index(self._body_vars[index]), index - 1))
        return self._body_vars[host_index], host_index

    @staticmethod
    def _altitude(fields: dict[str, tk.StringVar]) -> float | None:
        try:
            return float(fields["altitude"].get())
        except ValueError:
            return None

    @staticmethod
    def _reset_altitude_default(fields: dict[str, tk.StringVar]) -> None:
        """Seed the altitude field for the newly selected catalogue body.

        The satellite keeps its catalogue altitude as an editable default;
        ordinary bodies start empty (use their catalogue distance) so a stale
        satellite altitude never leaks onto a planet.
        """
        if fields["catalog"].get() == gui_model.NBODY_SATELLITE:
            fields["altitude"].set(
                str(int(gui_model.NBODY_SATELLITE_ALTITUDE_DEFAULT))
            )
        else:
            fields["altitude"].set("")

    def _add_body(self) -> None:
        # A blank, editable body; the per-body catalogue dropdown then seeds its
        # density/radius and a circular orbit about the centre on selection.
        spec = gui_model.NBodySpec(
            name=f"天体{len(self._body_vars) + 1}",
            density=1000.0,
            radius=1.0,
            state=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        )
        prior_names = [fields["name"].get() for fields in self._body_vars]
        self._body_vars.append(
            self._fields_from_spec(spec, len(self._body_vars), prior_names)
        )
        self._rebuild_body_groups()

    def _remove_body(self) -> None:
        if len(self._body_vars) <= 1:
            return
        self._body_vars.pop()
        self._rebuild_body_groups()

    def _update_time_label(self, index: int) -> None:
        outcome = self._last_outcome
        if outcome is None or not outcome.frames:
            self._time_label.configure(text="t = -")
            return
        frame = outcome.frames[min(max(index, 0), len(outcome.frames) - 1)]
        days = frame.t / 86400.0
        self._time_label.configure(
            text=f"t = {frame.t:,.0f} s（{days:.2f} 日）"
        )

    # ----------------------------------------------------------------- playback

    def _on_frame_change(self, value: str) -> None:
        try:
            index = int(round(float(value)))
        except ValueError:
            return
        index = self._chart.set_frame(index)
        if abs(self._frame_var.get() - index) > 0.5:
            self._frame_var.set(index)
        self._update_time_label(index)

    def _toggle_playback(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        frame_count = self._chart.frame_count
        if frame_count < 2:
            return
        self._playing = True
        self._play_button.configure(text="停止")
        step = max(1, math.ceil(frame_count / (PLAY_SECONDS * PLAY_FPS)))

        def tick() -> None:
            if not self._playing:
                return
            index = (self._chart.current_index + step) % frame_count
            self._frame_var.set(index)
            self._chart.set_frame(index)
            self._update_time_label(index)
            self._play_after_id = self.after(int(1000 / PLAY_FPS), tick)

        tick()

    def _stop_playback(self) -> None:
        self._playing = False
        if self._play_after_id is not None:
            try:
                self.after_cancel(self._play_after_id)
            except tk.TclError:
                pass
            self._play_after_id = None
        if hasattr(self, "_play_button"):
            self._play_button.configure(text="再生")

    @staticmethod
    def _focus_label(index: int, name: str) -> str:
        return f"天体 {index + 1}（{name}）"

    def _on_focus_selected(self, *_args: object) -> None:
        # The combobox is [重心（原点）, 天体 1, ...]; the chart uses -1 for the
        # barycentre (origin) and a body index otherwise.
        self._chart.set_focus(self._focus_box.current() - 1)

    # ------------------------------------------------------------------ actions

    def _read_conditions(self) -> NBodyConditions:
        rows = [
            tuple(fields[key].get() for key in NBODY_ROW_ORDER)
            for fields in self._body_vars
        ]
        return gui_model.nbody_conditions_from_rows(
            rows,
            self._dt_var.get(),
            self._time_var.get(),
            adaptive=self._adaptive_var.get(),
        )

    def _run(self) -> None:
        try:
            conditions = self._read_conditions()
        except ValueError as exc:
            self._error_var.set(str(exc))
            return
        message = gui_model.validate_nbody_conditions(conditions)
        if message is not None:
            self._error_var.set(message)
            return
        self._error_var.set("")
        warning = gui_model.nbody_timestep_warning(conditions)
        self._warning_var.set(warning or "")
        self._begin_run(conditions)

    def _worker(self, conditions: NBodyConditions) -> None:
        try:
            outcome = gui_model.run_nbody(conditions)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            self._results.put(
                ("error", f"エラー: {errors.localize_error(str(exc))}")
            )
        else:
            self._results.put(("ok", outcome))

    def _apply_outcome(self, outcome: NBodyOutcome) -> None:
        self._stop_playback()
        self._last_outcome = outcome
        self._render_metric_rows(gui_model.nbody_result_metrics(outcome))
        self._focus_box.configure(
            values=[BARYCENTRE_LABEL]
            + [
                self._focus_label(index, body.name)
                for index, body in enumerate(outcome.conditions.bodies)
            ]
        )
        self._focus_var.set(BARYCENTRE_LABEL)
        self._chart.show(outcome, focus=-1)
        self._frame_scale.configure(to=max(len(outcome.frames) - 1, 0))
        self._frame_var.set(0)
        self._update_time_label(0)
        self._set_idle()
        # Start the playback automatically so the run animates on arrival.
        self._start_playback()


def main() -> None:
    app = NBodyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
