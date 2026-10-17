"""Desktop GUI for flat-surface projectiles (drag + spin / Magnus lift).

This is one of the two desktop entry points (see :mod:`app_common`). It shows
only the ballistic controls: launch speed, angle, drag coefficient, density
model, timestep, and the spin rate / axis that drive the Magnus lift. The chart
can switch between the side-on (x-y) and top-down (x-z) views, the latter making
the lateral deflection from a tilted spin axis visible.

Run it with::

    python3 desktop/ballistic_app.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import gui_model
from app_common import BaseApp
from gui_model import LaunchConditions, SimulationOutcome
from trajectory_chart import VIEW_XY, VIEW_XZ, TrajectoryChart


class BallisticApp(BaseApp):
    """The flat-surface projectile window."""

    def __init__(self) -> None:
        super().__init__(
            title="Range Calculator Desktop — 弾道 (Ballistic)",
            geometry="1020x860",
            minsize=(780, 680),
        )

        self._velocity_var = tk.DoubleVar(value=gui_model.DEFAULT_VELOCITY_KMPH)
        self._angle_var = tk.DoubleVar(value=gui_model.DEFAULT_ANGLE_DEG)
        self._dt_var = tk.StringVar(value=str(gui_model.DEFAULT_TIMESTEP))
        self._adaptive_var = tk.BooleanVar(value=gui_model.DEFAULT_ADAPTIVE)
        self._density_var = tk.StringVar(value=gui_model.density_label("constant"))
        self._spin_rate_var = tk.DoubleVar(value=gui_model.DEFAULT_SPIN_RPM)
        self._spin_axis_var = tk.DoubleVar(value=gui_model.DEFAULT_SPIN_AXIS_DEG)
        self._view_var = tk.StringVar(value=VIEW_XY)

        self._build_ui()
        self.activate()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header, text="Range Calculator Desktop — 弾道", font=("", 15, "bold")
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="地表弾道（抗力・スピンによる Magnus 揚力つき）",
        ).pack(anchor="w")

        body = ttk.Frame(self, padding=(20, 8, 20, 8))
        body.grid(row=1, column=0, sticky="ew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self._build_controls(body)
        self._build_results(body)

        self._chart = TrajectoryChart(self)
        self._chart.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))

    def _build_controls(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Launch conditions", padding=14)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self._add_scale(
            panel,
            "発射速度",
            "km/h",
            self._velocity_var,
            gui_model.VELOCITY_MIN,
            gui_model.VELOCITY_MAX,
            digits=1,
        )
        self._add_scale(
            panel,
            "発射角",
            "deg",
            self._angle_var,
            gui_model.ANGLE_MIN,
            gui_model.ANGLE_MAX,
            digits=1,
        )

        cd_row = ttk.Frame(panel)
        cd_row.pack(fill="x", pady=(8, 0))
        ttk.Label(cd_row, text="抗力係数 Cd").pack(side="left")
        ttk.Label(
            cd_row,
            text=f"{gui_model.DRAG_COEFFICIENT_DEFAULT}（球体）",
            foreground="#52606d",
        ).pack(side="right")

        density_row = ttk.Frame(panel)
        density_row.pack(fill="x", pady=(8, 0))
        ttk.Label(density_row, text="抗力（密度）モデル").pack(side="left")
        self._density_box = ttk.Combobox(
            density_row,
            textvariable=self._density_var,
            values=[label for _value, label in gui_model.DENSITY_PRESETS],
            state="readonly",
            width=26,
        )
        self._density_box.pack(side="right")

        spin = ttk.LabelFrame(panel, text="スピン（Magnus 揚力）", padding=10)
        spin.pack(fill="x", pady=(10, 0))
        self._add_scale(
            spin,
            "回転数",
            "rpm",
            self._spin_rate_var,
            gui_model.SPIN_RATE_MIN,
            gui_model.SPIN_RATE_MAX,
            digits=0,
        )
        self._add_scale(
            spin,
            "スピン軸角",
            "deg",
            self._spin_axis_var,
            gui_model.SPIN_AXIS_MIN,
            gui_model.SPIN_AXIS_MAX,
            digits=0,
        )

        dt_row = ttk.Frame(panel)
        dt_row.pack(fill="x", pady=(10, 0))
        ttk.Label(dt_row, text="刻み幅 dt (s)").pack(side="left")
        dt_entry = ttk.Entry(dt_row, textvariable=self._dt_var, width=14)
        dt_entry.pack(side="right")
        dt_entry.bind("<Return>", lambda _event: self._run())

        ttk.Checkbutton(
            panel,
            text="adaptive 刻み（安定性上限で自動短縮）",
            variable=self._adaptive_var,
        ).pack(anchor="w", pady=(10, 0))

        view_row = ttk.Frame(panel)
        view_row.pack(fill="x", pady=(10, 0))
        ttk.Label(view_row, text="表示").pack(side="left")
        ttk.Radiobutton(
            view_row, text="断面 (x–y)", value=VIEW_XY, variable=self._view_var,
            command=self._on_view_change,
        ).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(
            view_row, text="上面 (x–z)", value=VIEW_XZ, variable=self._view_var,
            command=self._on_view_change,
        ).pack(side="left")

        self._run_button = ttk.Button(
            panel, text=self.run_label, command=self._run
        )
        self._run_button.pack(anchor="w", pady=(12, 0))

        ttk.Label(
            panel,
            textvariable=self._error_var,
            foreground="#b91c1c",
            wraplength=340,
        ).pack(anchor="w", pady=(8, 0))

    def _build_results(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Result", padding=14)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.columnconfigure(1, weight=1)
        self._metrics_panel = panel

        ttk.Label(
            panel,
            textvariable=self._warning_var,
            foreground="#92400e",
            wraplength=340,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._render_metric_rows(gui_model.DEFAULT_METRIC_ROWS)

    # ------------------------------------------------------------------ actions

    def _on_view_change(self) -> None:
        self._chart.set_view(self._view_var.get())

    def _read_conditions(self) -> LaunchConditions:
        return gui_model.make_conditions(
            gravity_model="constant",
            velocity_kmph=round(self._velocity_var.get()),
            angle_deg=round(self._angle_var.get()),
            dt=float(self._dt_var.get()),
            adaptive=bool(self._adaptive_var.get()),
            drag_coefficient=gui_model.DRAG_COEFFICIENT_DEFAULT,
            density_model=self._selected_value(
                self._density_var, gui_model.DENSITY_PRESETS
            ),
            spin_rate=float(self._spin_rate_var.get()),
            spin_axis_deg=float(self._spin_axis_var.get()),
        )

    def _run(self) -> None:
        if self._running:
            return
        message = gui_model.validate_dt(self._dt_var.get())
        if message is not None:
            self._error_var.set(message)
            return
        self._error_var.set("")
        self._warning_var.set("")
        self._begin_run(self._read_conditions())

    def _apply_outcome(self, outcome: SimulationOutcome) -> None:
        result = outcome.result
        self._render_metric_rows(gui_model.result_metrics(outcome))
        self._warning_var.set(
            "時間上限に達しました。着弾前に計算が終了しています。"
            if result.timed_out
            else ""
        )
        self._chart.show(outcome, self._view_var.get())
        self._set_idle()


def main() -> None:
    app = BallisticApp()
    app.mainloop()


if __name__ == "__main__":
    main()
