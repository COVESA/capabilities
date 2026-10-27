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
capability_framework.southbound
===============================
The capability southbound interface: per-capability actuator ports, the
deployment-physics profile, and ``ActuatorError``.

Hardware bindings depend on this package only. It imports nothing else.
"""

from .ports import (
    ActuatorError,
    ActuatorPortBase,
    WindowActuatorPort,
)
from .profile import PROFILE_SOURCE_TRUST, ActuatorProfile, MoveOutcome, ProfileSource

__all__ = [
    "ActuatorError",
    "ActuatorPortBase",
    "ActuatorProfile",
    "MoveOutcome",
    "PROFILE_SOURCE_TRUST",
    "ProfileSource",
    "WindowActuatorPort",
]
