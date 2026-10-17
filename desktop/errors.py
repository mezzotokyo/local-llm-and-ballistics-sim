"""Localisation of the physics core's timestep errors for the desktop GUI.

This mirrors ``webapp/server/server.py``'s ``localize_error`` deliberately: each
entry point in this repository stays self-contained, so the desktop app does not
import the web API. The duplication is guarded by
``desktop/tests/test_agreement.py``, which fails if the two implementations ever
drift apart, so update both when a message changes.

The core (:mod:`ballistics`) keeps its messages in English because they are
asserted by the unit tests. This module is the presentation boundary, so only
user-facing timestep failures are rewritten here; anything that does not match a
known pattern is returned unchanged.
"""

from __future__ import annotations

import re

_TOO_COARSE_RE = re.compile(
    r"timestep dt=(?P<dt>\S+) is too coarse: an upward launch reached the "
    r"ground within the first step\. Reduce dt below (?P<stable>\S+)\."
)


def localize_error(message: str) -> str:
    """Translate a physics-core error message into Japanese for the UI."""
    match = _TOO_COARSE_RE.search(message)
    if match:
        return (
            f"刻み幅 dt={match['dt']} は粗すぎます。上方向への発射が最初のステップで"
            f"地面に到達しました。dt を {match['stable']} 未満にしてください。"
        )
    if "non-finite state" in message:
        return (
            "刻み幅 dt が大きすぎて計算が発散しました（非有限値）。"
            "dt を小さくしてください。"
        )
    if "more than" in message and "launch speed" in message:
        return (
            "刻み幅 dt が大きすぎて計算速度が発散しました。dt を小さくしてください。"
        )
    return message
