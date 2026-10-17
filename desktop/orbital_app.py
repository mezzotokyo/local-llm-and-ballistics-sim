"""Desktop GUI for central-gravity orbits (newtonian / J2).

This is one of the two desktop entry points (see :mod:`app_common`). It shows
only the orbital controls: gravity model, orbit radius (and speed), drag density
model, and timestep. The trajectory is drawn side-on, with the central body at
the origin.

Run it with::

    python3 desktop/orbital_app.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import gui_model
from app_common import BaseApp
from gui_model import LaunchConditions, SimulationOutcome
from trajectory_chart import TrajectoryChart


class OrbitalApp(BaseApp):
    """The central-gravity orbit window."""

    def __init__(self) -> None:
        super().__init__(
            title="Range Calculator Desktop — 軌道 (Orbital)",
            geometry="1020x760",
            minsize=(780, 620),
        )

        self._gravity_var = tk.StringVar(
            value=gui_model.gravity_label("newtonian")
        )
        self._radius_var = tk.DoubleVar(value=gui_model.DEFAULT_ORBITAL_RADIUS)
        self._auto_speed_var = tk.BooleanVar(value=True)
        self._speed_var = tk.DoubleVar(
            value=gui_model.orbital_speed(gui_model.DEFAULT_ORBITAL_RADIUS)
        )
        self._density_var = tk.StringVar(value=gui_model.density_label("none"))
        self._dt_var = tk.StringVar(value="1.0")
        self._adaptive_var = tk.BooleanVar(value=gui_model.DEFAULT_ADAPTIVE)

        self._gravity_presets = tuple(
            (value, label)
            for value, label in gui_model.GRAVITY_PRESETS
            if value != "constant"
        )

        self._build_ui()
        self.activate()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header, text="Range Calculator Desktop — 軌道", font=("", 15, "bold")
        ).pack(anchor="w")
        ttk.Label(
            header, text="中心重力（ニュートン / J2）の軌道"
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
        panel = ttk.LabelFrame(parent, text="Orbital conditions", padding=14)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        gravity_row = ttk.Frame(panel)
        gravity_row.pack(fill="x", pady=(0, 8))
        ttk.Label(gravity_row, text="重力モデル").pack(side="left")
        self._gravity_box = ttk.Combobox(
            gravity_row,
            textvariable=self._gravity_var,
            values=[label for _value, label in self._gravity_presets],
            state="readonly",
            width=26,
        )
        self._gravity_box.pack(side="right")

        radius_row = ttk.Frame(panel)
        radius_row.pack(fill="x")
        self._radius_label = ttk.Label(radius_row, text="")
        self._radius_label.pack(anchor="w")
        ttk.Scale(
            radius_row,
            from_=gui_model.RADIUS_MIN,
            to=gui_model.RADIUS_MAX,
            orient="horizontal",
            variable=self._radius_var,
            command=self._on_radius_change,
        ).pack(fill="x")

        speed_row = ttk.Frame(panel)
        speed_row.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            speed_row,
            text="円軌道速度を自動設定",
            variable=self._auto_speed_var,
            command=self._on_auto_speed_change,
        ).pack(anchor="w")
        self._speed_label = ttk.Label(panel, text="")
        self._speed_label.pack(anchor="w")
        self._speed_scale = ttk.Scale(
            panel,
            from_=gui_model.ORBITAL_SPEED_MIN,
            to=gui_model.ORBITAL_SPEED_MAX,
            orient="horizontal",
            variable=self._speed_var,
            command=lambda _value: self._update_speed_label(),
        )
        self._speed_scale.pack(fill="x")

        cd_row = ttk.Frame(panel)
        cd_row.pack(fill="x", pady=(10, 0))
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

        self._on_auto_speed_change()

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

        self._render_metric_rows(gui_model.DEFAULT_ORBITAL_METRIC_ROWS)

    # ------------------------------------------------------------------ helpers

    def _on_radius_change(self, _value: str | None = None) -> None:
        if self._auto_speed_var.get():
            self._speed_var.set(gui_model.orbital_speed(self._radius_var.get()))
        self._update_orbital_labels()

    def _on_auto_speed_change(self) -> None:
        if self._auto_speed_var.get():
            self._speed_var.set(gui_model.orbital_speed(self._radius_var.get()))
            self._speed_scale.configure(state="disabled")
        else:
            self._speed_scale.configure(state="normal")
        self._update_orbital_labels()

    def _update_orbital_labels(self) -> None:
        radius_km = self._radius_var.get() / 1000.0
        self._radius_label.configure(text=f"軌道半径 r {radius_km:,.0f} km")
        self._update_speed_label()

    def _update_speed_label(self) -> None:
        self._speed_label.configure(
            text=f"軌道速度 v {self._speed_var.get():,.0f} m/s"
        )

    # ------------------------------------------------------------------ actions

    def _read_conditions(self) -> LaunchConditions:
        speed_mps = None
        if not self._auto_speed_var.get():
            speed_mps = float(self._speed_var.get())
        return gui_model.make_conditions(
            gravity_model=self._selected_value(
                self._gravity_var, self._gravity_presets
            ),
            dt=float(self._dt_var.get()),
            adaptive=bool(self._adaptive_var.get()),
            drag_coefficient=gui_model.DRAG_COEFFICIENT_DEFAULT,
            density_model=self._selected_value(
                self._density_var, gui_model.DENSITY_PRESETS
            ),
            radius=float(self._radius_var.get()),
            speed_mps=speed_mps,
        )

    def _run(self) -> None:
        message = gui_model.validate_dt(self._dt_var.get())
        if message is not None:
            self._error_var.set(message)
            return
        self._error_var.set("")
        self._warning_var.set("")
        self._begin_run(self._read_conditions())

    def _apply_outcome(self, outcome: SimulationOutcome) -> None:
        self._render_metric_rows(gui_model.result_metrics(outcome))
        self._warning_var.set("")
        self._chart.show(outcome)
        self._set_idle()


def main() -> None:
    app = OrbitalApp()
    app.mainloop()


if __name__ == "__main__":
    main()
