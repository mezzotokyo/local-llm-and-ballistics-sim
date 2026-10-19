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

The N-body patterns at the end are desktop-only: the web API has no N-body
endpoint, so those core messages from :mod:`nbody` have no counterpart in
``server.py`` to keep in sync.
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
    # N-body (nbody.py) messages: desktop-only, no webapp counterpart.
    if "minimum separation" in message:
        return (
            "天体同士が最小間隔より接近しました。点質量としてモデル化できない"
            "近接遭遇です。dt を小さくするか条件を見直してください。"
        )
    if "occupy the same position" in message:
        return (
            "2 つの天体が同じ位置にあります。重力が特異になるため"
            "計算できません。位置を変更してください。"
        )
    if "more than" in message and "initial speed" in message:
        return (
            "刻み幅 dt が大きすぎて計算速度が発散しました。dt を小さくしてください。"
        )
    return message
