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
capability_framework.capabilities.lighting.vss
==============================================
Project the lighting capability's domain state onto VSS signals.

The northbound API carries a single intensity where 0 % means off. VSS models
the same light as ``IsLightOn`` plus ``Intensity`` (uint8 percent, range 1-100),
so this adapter splits it: 0 % publishes ``IsLightOn = false`` and leaves
``Intensity`` untouched, because VSS has no "0 %" intensity to report.

Signal mapping comes from generated constants
(:mod:`capability_framework.semantics.vss_paths`), so a path cannot be misspelled.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...semantics.vss_paths import LIGHTING_COLOR, LIGHTING_INTENSITY, LIGHTING_IS_ON
from .types import LightingState, LightingZone

__all__ = ["project_state"]

#: VSS AmbientLight.Intensity lower bound: 1 = maximum attenuation.
_VSS_MIN_INTENSITY = 1.0


def project_state(state: LightingState) -> Mapping[str, Any]:
    """Map one ``LightingState`` onto VSS paths. ``ALL`` fans out to every zone."""
    if state.intensity_pct is None:
        # Output unknown (ACTUATOR_FAULT): report nothing rather than a lie.
        return {}

    zone = state.zone.value if isinstance(state.zone, LightingZone) else str(state.zone)
    zones = sorted(LIGHTING_IS_ON) if zone == LightingZone.ALL.value else [zone]

    intensity = float(state.intensity_pct)
    values: dict[str, Any] = {}
    for z in zones:
        if z not in LIGHTING_IS_ON:
            continue
        values[LIGHTING_IS_ON[z]] = intensity > 0.0
        if intensity > 0.0:
            values[LIGHTING_INTENSITY[z]] = max(_VSS_MIN_INTENSITY, min(100.0, intensity))
        if state.color:
            values[LIGHTING_COLOR[z]] = state.color
    return values
