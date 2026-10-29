# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
capability_framework.capabilities.window.vss
============================================
Project the window capability's domain state onto VSS signals.

The capability deliberately does not know about VSS at its core: it publishes
``WindowState`` on the bus, and this adapter turns that into VSS-shaped values.
That keeps the standards mapping a boundary concern, which is the whole point of
the architecture.

Signal mapping comes from generated constants
(:mod:`capability_framework.semantics.vss_paths`), so a path cannot be misspelled
here — it would not exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...semantics.vss_paths import WINDOW_IS_OPEN, WINDOW_POSITION, WINDOW_SWITCH
from .types import WindowState, WindowStatus, WindowZone

__all__ = ["WindowVssProjector", "project_state"]

#: Position change (percentage points) below which a window is not "moving".
_MOVING_THRESHOLD_PCT = 0.5


def project_state(state: WindowState, *, previous_pct: float | None = None) -> Mapping[str, Any]:
    """
    Map one ``WindowState`` onto VSS paths.

    ``Switch`` is derived, not guessed: it reflects the observed direction of
    travel. A capability report does not carry a commanded direction, so deriving
    it from the delta is the honest projection.
    """
    zone = state.zone.value if isinstance(state.zone, WindowZone) else str(state.zone)
    if zone not in WINDOW_POSITION:
        # ``ALL`` is an orchestration scope, not an addressable VSS instance.
        return {}

    values: dict[str, Any] = {}
    position = state.position_pct
    if position is None:
        # Position unknown (ACTUATOR_FAULT): report nothing rather than a lie.
        return values

    position = float(position)
    values[WINDOW_POSITION[zone]] = position
    values[WINDOW_IS_OPEN[zone]] = position > 0.0

    if state.status is WindowStatus.PINCHED:
        # A pinch always reverses the window, so it is travelling open.
        values[WINDOW_SWITCH[zone]] = "OPEN"
    elif previous_pct is None or abs(position - previous_pct) < _MOVING_THRESHOLD_PCT:
        values[WINDOW_SWITCH[zone]] = "INACTIVE"
    elif position > previous_pct:
        values[WINDOW_SWITCH[zone]] = "OPEN"
    else:
        values[WINDOW_SWITCH[zone]] = "CLOSE"

    return values


class WindowVssProjector:
    """A stateful projector: remembers the last position per zone to derive direction."""

    def __init__(self) -> None:
        self._previous: dict[str, float] = {}

    def __call__(self, state: WindowState) -> Mapping[str, Any]:
        zone = state.zone.value if isinstance(state.zone, WindowZone) else str(state.zone)
        values = project_state(state, previous_pct=self._previous.get(zone))
        if state.position_pct is not None and zone in WINDOW_POSITION:
            self._previous[zone] = float(state.position_pct)
        return values
