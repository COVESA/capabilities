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
capability_framework.vehicle_state
==================================
Vehicle-level state types a capability reads in its precondition phase.

Types only, no runtime: a capability reads ``VehicleState`` to gate on power,
drive, OTA and supply voltage without depending on the vehicle-management
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

__all__ = [
    "DriveState",
    "EntryState",
    "OtaState",
    "PowerState",
    "VehicleLifecycleState",
    "VehicleState",
    "vehicle_state_to_dict",
]


class PowerState(str, Enum):
    OFF = "OFF"
    ACC = "ACC"
    ON = "ON"
    CRANKING = "CRANKING"


class DriveState(str, Enum):
    PARKED = "PARKED"
    DRIVE = "DRIVE"
    REVERSE = "REVERSE"


class OtaState(str, Enum):
    IDLE = "IDLE"
    DOWNLOADING = "DOWNLOADING"
    APPLYING = "APPLYING"
    ERROR = "ERROR"


class EntryState(str, Enum):
    IDLE = "IDLE"
    APPROACHING = "APPROACHING"
    SEATED = "SEATED"
    EXITING = "EXITING"


class VehicleLifecycleState(str, Enum):
    FACTORY = "FACTORY"
    TRANSPORT = "TRANSPORT"
    DEALER = "DEALER"
    NORMAL = "NORMAL"
    KOL = "KOL"
    OTA = "OTA"
    DIAGNOSTIC = "DIAGNOSTIC"
    SERVICE = "SERVICE"


@dataclass(frozen=True)
class VehicleState:
    power_state: PowerState = PowerState.OFF
    drive_state: DriveState = DriveState.PARKED
    ota_state: OtaState = OtaState.IDLE
    entry_state: EntryState = EntryState.IDLE
    supply_voltage_v: float = 12.0
    lifecycle: VehicleLifecycleState = VehicleLifecycleState.NORMAL
    state_of_charge: float = 1.0
    available_budget_mA: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def vehicle_state_to_dict(vs: VehicleState) -> dict:
    """JSON-ready view of a VehicleState, shared by the HTTP adapter and the SSE stream."""
    return {
        "power_state": vs.power_state.value,
        "drive_state": vs.drive_state.value,
        "ota_state": vs.ota_state.value,
        "entry_state": vs.entry_state.value,
        "supply_voltage_v": vs.supply_voltage_v,
        "lifecycle": vs.lifecycle.value,
        "state_of_charge": vs.state_of_charge,
        "available_budget_mA": vs.available_budget_mA,
    }
