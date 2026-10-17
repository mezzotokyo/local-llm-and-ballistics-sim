"""Shared Tkinter plumbing for the desktop apps.

The desktop is split into two self-contained windows so each one shows only its
own controls and results:

* :mod:`ballistic_app` -- flat-surface projectiles (drag, spin / Magnus lift).
* :mod:`orbital_app` -- central-gravity orbits (newtonian / J2).

Both derive from :class:`BaseApp`, which owns the pieces that do not depend on
the physics: running :func:`gui_model.simulate` on a worker thread, marshalling
the result back through a queue, rendering the metric table, and surfacing
errors / warnings. Subclasses provide the controls, read the launch conditions,
and draw the trajectory.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Sequence

import errors
import gui_model
from gui_model import LaunchConditions, SimulationOutcome

POLL_INTERVAL_MS = 50
INITIAL_RUN_DELAY_MS = 150


class BaseApp(tk.Tk):
    """Common window behaviour for a single-model simulation window."""

    run_label = "シミュレーション実行"
    busy_label = "計算中..."

    def __init__(self, title: str, geometry: str, minsize: tuple[int, int]) -> None:
        super().__init__()
        self.title(title)
        self.geometry(geometry)
        self.minsize(*minsize)

        self._results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._running = False

        self._metric_vars: dict[str, tk.StringVar] = {}
        self._metric_widgets: list[tk.Widget] = []
        self._error_var = tk.StringVar(value="")
        self._warning_var = tk.StringVar(value="")
        self._run_button: ttk.Button | None = None
        self._metrics_panel: ttk.LabelFrame | None = None

    # ------------------------------------------------------------------ startup

    def activate(self) -> None:
        """Start polling for results and trigger the first run.

        Call once the subclass has finished building its widgets.
        """
        self.after(POLL_INTERVAL_MS, self._poll_results)
        self.after(INITIAL_RUN_DELAY_MS, self._run)

    # -------------------------------------------------------------- metric table

    def _render_metric_rows(self, rows: Sequence[tuple[str, str, str]]) -> None:
        panel = self._metrics_panel
        if panel is None:
            return
        for widget in self._metric_widgets:
            widget.destroy()
        self._metric_widgets = []
        self._metric_vars = {}

        for index, (key, label, value) in enumerate(rows):
            label_widget = ttk.Label(panel, text=label)
            label_widget.grid(row=index + 1, column=0, sticky="w", pady=2)
            value_var = tk.StringVar(value=f"{value}")
            self._metric_vars[key] = value_var
            value_widget = ttk.Label(
                panel, textvariable=value_var, font=("", 11, "bold")
            )
            value_widget.grid(
                row=index + 1, column=1, sticky="w", padx=(16, 0), pady=2
            )
            self._metric_widgets.extend((label_widget, value_widget))

    @staticmethod
    def _selected_value(variable: tk.StringVar, presets: tuple) -> str:
        selected = variable.get()
        for value, label in presets:
            if label == selected:
                return value
        return presets[0][0]

    @staticmethod
    def _add_scale(
        parent: ttk.Frame,
        title: str,
        unit: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        digits: int,
    ) -> ttk.Scale:
        """A labelled horizontal slider bound to ``variable``."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        value_label = ttk.Label(row, text="")
        value_label.pack(anchor="w")

        def update_label(_value: str | None = None) -> None:
            value_label.configure(
                text=f"{title} {variable.get():.{digits}f} {unit}"
            )

        update_label()
        scale = ttk.Scale(
            row,
            from_=minimum,
            to=maximum,
            orient="horizontal",
            variable=variable,
            command=update_label,
        )
        scale.pack(fill="x")
        return scale

    # ------------------------------------------------------------------ running

    def _begin_run(self, conditions: LaunchConditions) -> None:
        if self._running:
            return
        self._running = True
        if self._run_button is not None:
            self._run_button.configure(text=self.busy_label, state="disabled")
        threading.Thread(
            target=self._worker, args=(conditions,), daemon=True
        ).start()

    def _worker(self, conditions: LaunchConditions) -> None:
        try:
            outcome = gui_model.simulate(conditions)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            self._results.put(
                ("error", f"エラー: {errors.localize_error(str(exc))}")
            )
        else:
            self._results.put(("ok", outcome))

    def _poll_results(self) -> None:
        try:
            while True:
                status, payload = self._results.get_nowait()
                if status == "ok":
                    self._apply_outcome(payload)  # type: ignore[arg-type]
                else:
                    self._error_var.set(str(payload))
                    self._set_idle()
        except queue.Empty:
            pass
        self.after(POLL_INTERVAL_MS, self._poll_results)

    def _set_idle(self) -> None:
        self._running = False
        if self._run_button is not None:
            self._run_button.configure(text=self.run_label, state="normal")

    # --------------------------------------------------------------- overridable

    def _read_conditions(self) -> LaunchConditions:
        raise NotImplementedError

    def _run(self) -> None:
        raise NotImplementedError

    def _apply_outcome(self, outcome: SimulationOutcome) -> None:
        raise NotImplementedError
