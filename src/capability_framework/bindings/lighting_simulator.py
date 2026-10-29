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
capability_framework.bindings.lighting_simulator
================================================
In-process simulation binding for the lighting southbound port.

An LED driver settles in milliseconds, so there is no plant model here: the
binding records the commanded output per zone, exactly as a real binding would
map the port onto a light driver and read its output back.

Only southbound types cross this boundary.
"""

from __future__ import annotations

import logging

from ..southbound import LightingActuatorPort, LightOutput

__all__ = ["LightingSimulatorPort"]

log = logging.getLogger(__name__)

ZONES = ("DRIVER_FRONT", "PASSENGER_FRONT", "DRIVER_REAR", "PASSENGER_REAR")
DEFAULT_COLOR = "#FFFFFF"


class LightingSimulatorPort(LightingActuatorPort):
    """In-process ambient-light actuator: every zone starts off and white."""

    def __init__(self) -> None:
        self._zones: dict[str, LightOutput] = {
            zone: LightOutput(intensity_pct=0.0, color=DEFAULT_COLOR) for zone in ZONES
        }

    async def set_ambient_light(self, zone: str, intensity_pct: float,
                                color: str | None = None) -> LightOutput:
        if zone == "ALL":
            for z in ZONES:
                await self.set_ambient_light(z, intensity_pct, color)
            return self._zones[ZONES[0]]

        current = self._zones.get(zone, LightOutput(0.0, DEFAULT_COLOR))
        output = LightOutput(
            intensity_pct=max(0.0, min(100.0, float(intensity_pct))),
            color=color or current.color,
        )
        self._zones[zone] = output
        log.debug("LightingSimulatorPort: %s → %.1f%% %s", zone, output.intensity_pct, output.color)
        return output

    async def get_ambient_light(self, zone: str) -> LightOutput:
        if zone == "ALL":
            zone = ZONES[0]
        return self._zones.get(zone, LightOutput(0.0, DEFAULT_COLOR))
