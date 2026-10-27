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

"""Window capability and window-orchestrator commands, states and typed reasons."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..base import RequestSource

#: The package's northbound API version; the only place it is written.
API_VERSION = "2.0.0"


class WindowStatus(str, Enum):
    STATIONARY = "STATIONARY"
    MOVING = "MOVING"
    PINCHED = "PINCHED"      # obstacle detected — auto-reversed
    INHIBITED = "INHIBITED"  # blocked by vehicle state or the safety gate
    REJECTED = "REJECTED"    # lost arbitration


class WindowZone(str, Enum):
    DRIVER_FRONT = "DRIVER_FRONT"
    PASSENGER_FRONT = "PASSENGER_FRONT"
    DRIVER_REAR = "DRIVER_REAR"
    PASSENGER_REAR = "PASSENGER_REAR"
    ALL = "ALL"


class WindowInhibitReason(str, Enum):
    """Domain-specific typed inhibit reasons for the window capability."""
    POWER_OFF = "POWER_OFF"
    VEHICLE_IN_MOTION_LOCK = "VEHICLE_IN_MOTION_LOCK"
    OTA_IN_PROGRESS = "OTA_IN_PROGRESS"
    UNDERVOLTAGE = "UNDERVOLTAGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    PINCH_DETECTED = "PINCH_DETECTED"
    THERMAL_PROTECTION = "THERMAL_PROTECTION"
    CHILD_LOCK_ACTIVE = "CHILD_LOCK_ACTIVE"
    WINDOW_BUSY = "WINDOW_BUSY"
    ACTUATOR_FAULT = "ACTUATOR_FAULT"
    RELEASED = "RELEASED"    # interrupted by the lock holder's release
    TIMEOUT = "TIMEOUT"      # actuator call outlived timeout_s


@dataclass(frozen=True)
class MoveWindowCommand:
    """Immutable command to move a vehicle window."""
    source: RequestSource
    zone: WindowZone
    target_pct: float           # 0.0 = fully closed, 100.0 = fully open
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_s: float = 30.0


@dataclass(frozen=True)
class WindowState:
    """Immutable window state response."""
    status: WindowStatus
    position_pct: float | None   # None only when unknown (ACTUATOR_FAULT)
    zone: WindowZone
    reason: WindowInhibitReason | None = None
    message: str | None = None   # human-readable (never branch on this)
    retry_after_s: float | None = None
    winning_source: RequestSource | None = None
    request_id: str | None = None
    api_version: str = API_VERSION
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Window domain capability orchestrator (intra-domain multi-zone sequencing)
# ─────────────────────────────────────────────────────────────────────────────

class WindowGroup(str, Enum):
    """Named groups of window zones used by the window domain orchestrator."""
    ROW_1_FRONT = "ROW_1_FRONT"
    ROW_2_REAR = "ROW_2_REAR"
    DRIVER_SIDE = "DRIVER_SIDE"
    PASSENGER_SIDE = "PASSENGER_SIDE"
    ALL = "ALL"


class WindowSequenceMode(str, Enum):
    """High-level orchestration modes exposed by cascade_open / cascade_close / sync."""
    CASCADE_OPEN = "CASCADE_OPEN"     # ROW_1_FRONT first, then ROW_2_REAR
    CASCADE_CLOSE = "CASCADE_CLOSE"   # ROW_2_REAR first, then ROW_1_FRONT
    SYNC = "SYNC"                     # all zones in one stage
    CUSTOM = "CUSTOM"                 # caller-supplied stages


class WindowSequenceStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    STAGE_COMPLETE = "STAGE_COMPLETE"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"   # some stages / zones rejected or inhibited
    ABORTED = "ABORTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class WindowSequenceStage:
    """One stage of a multi-zone window sequence."""
    group: WindowGroup
    target_pct: float
    completion_threshold_pct: float = 5.0


@dataclass(frozen=True)
class WindowSequenceCommand:
    """Immutable command for a multi-zone window sequence."""
    source: RequestSource
    mode: WindowSequenceMode
    stages: tuple[WindowSequenceStage, ...]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_s: float = 60.0


@dataclass(frozen=True)
class WindowSequenceState:
    """Immutable state response for a window orchestration sequence."""
    status: WindowSequenceStatus
    active_stage_index: int
    per_zone: dict[str, WindowState]   # WindowZone.value → latest WindowState
    reason: str | None = None
    request_id: str | None = None
    api_version: str = API_VERSION
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
