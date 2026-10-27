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

"""Window capability: manager, domain orchestrator, and their typed commands/states."""

from .manager import WindowManager, WindowPlantModel
from .orchestrator import WindowCapabilityOrchestrator
from .types import (
    API_VERSION,
    MoveWindowCommand,
    WindowGroup,
    WindowInhibitReason,
    WindowSequenceCommand,
    WindowSequenceMode,
    WindowSequenceStage,
    WindowSequenceState,
    WindowSequenceStatus,
    WindowState,
    WindowStatus,
    WindowZone,
)

__all__ = [
    "API_VERSION",
    "MoveWindowCommand",
    "WindowCapabilityOrchestrator",
    "WindowGroup",
    "WindowInhibitReason",
    "WindowManager",
    "WindowPlantModel",
    "WindowSequenceCommand",
    "WindowSequenceMode",
    "WindowSequenceStage",
    "WindowSequenceState",
    "WindowSequenceStatus",
    "WindowState",
    "WindowStatus",
    "WindowZone",
]
