#!/usr/bin/env python3
"""Build the desktop executables with PyInstaller.

Two single-file executables are produced, one per window:

* ``range_calculator_ballistic`` from :mod:`ballistic_app`
* ``range_calculator_orbital`` from :mod:`orbital_app`

PyInstaller is a build-time tool only; the apps themselves run on the standard
library. Install it into the active environment first::

    pip install pyinstaller

Then run::

    python3 desktop/build.py

The results are written to ``desktop/dist/`` (``.exe`` on Windows, a binary on
macOS). The physics config is bundled next to the flattened modules so
``physics_config`` finds it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_DIR.parent
RANGE_CALCULATOR = REPO_ROOT / "range_calculator"
CONFIG_SOURCE = RANGE_CALCULATOR / "config" / "physics_constants.json"

APPS: tuple[tuple[str, str], ...] = (
    ("range_calculator_ballistic", "ballistic_app.py"),
    ("range_calculator_orbital", "orbital_app.py"),
)


def main() -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "PyInstaller is not installed. Install it with:\n"
            "    pip install pyinstaller",
            file=sys.stderr,
        )
        return 1
    if not CONFIG_SOURCE.is_file():
        print(f"missing config file: {CONFIG_SOURCE}", file=sys.stderr)
        return 1

    # PyInstaller flattens top-level (non-package) modules into the bundle root,
    # so physics_config's __file__-relative "config" directory must land there.
    data_arg = f"{CONFIG_SOURCE}{os.pathsep}config"

    for app_name, entry in APPS:
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            app_name,
            "--paths",
            str(RANGE_CALCULATOR),
            "--add-data",
            data_arg,
            "--distpath",
            str(DESKTOP_DIR / "dist"),
            "--workpath",
            str(DESKTOP_DIR / "build"),
            "--specpath",
            str(DESKTOP_DIR / "build"),
            str(DESKTOP_DIR / entry),
        ]
        print("running:", " ".join(command))
        code = subprocess.call(command)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
