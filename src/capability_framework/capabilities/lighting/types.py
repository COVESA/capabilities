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

"""Interior lighting capability commands, states and typed reasons."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..base import RequestSource

#: The package's northbound API version; the only place it is written.
API_VERSION = "1.0.0"

#: The "#RRGGBB" format VSS declares for AmbientLight.Color.
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class LightingStatus(str, Enum):
    ON = "ON"
    OFF = "OFF"
    INHIBITED = "INHIBITED"  # blocked by vehicle state or the safety gate
    REJECTED = "REJECTED"    # lost arbitration


class LightingZone(str, Enum):
    DRIVER_FRONT = "DRIVER_FRONT"
    PASSENGER_FRONT = "PASSENGER_FRONT"
    DRIVER_REAR = "DRIVER_REAR"
    PASSENGER_REAR = "PASSENGER_REAR"
    ALL = "ALL"


class LightingInhibitReason(str, Enum):
    """Domain-specific typed inhibit reasons for the lighting capability."""
    POWER_OFF = "POWER_OFF"
    OTA_IN_PROGRESS = "OTA_IN_PROGRESS"
    UNDERVOLTAGE = "UNDERVOLTAGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    INVALID_COLOR = "INVALID_COLOR"
    LIGHTING_BUSY = "LIGHTING_BUSY"
    ACTUATOR_FAULT = "ACTUATOR_FAULT"
    RELEASED = "RELEASED"    # interrupted by the lock holder's release
    TIMEOUT = "TIMEOUT"      # actuator call outlived timeout_s


@dataclass(frozen=True)
class SetInteriorLightCommand:
    """Immutable command to set a zone's interior (ambient) light."""
    source: RequestSource
    zone: LightingZone
    intensity_pct: float        # 0.0 = off, 100.0 = full brightness
    color: str | None = None    # "#RRGGBB"; None keeps the current color
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_s: float = 5.0


@dataclass(frozen=True)
class LightingState:
    """Immutable lighting state response."""
    status: LightingStatus
    intensity_pct: float | None  # None only when unknown (ACTUATOR_FAULT)
    color: str | None
    zone: LightingZone
    reason: LightingInhibitReason | None = None
    message: str | None = None   # human-readable (never branch on this)
    retry_after_s: float | None = None
    winning_source: RequestSource | None = None
    request_id: str | None = None
    api_version: str = API_VERSION
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
