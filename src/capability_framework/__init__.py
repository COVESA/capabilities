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

"""Capability framework — reference implementation.

A minimal, hardware-agnostic capability framework: a capability exposes a
semantic *northbound* API to callers above it and depends on an abstract
*southbound* port below it. The worked example is a power window.

Layers:

- :mod:`capability_framework.events` — the async event bus capabilities publish on
- :mod:`capability_framework.southbound` — the abstract actuator ports + deployment profile
- :mod:`capability_framework.capabilities` — the capability base class and the window capability
- :mod:`capability_framework.vehicle_state` — the vehicle-state view a capability reads preconditions from
- :mod:`capability_framework.models` — physics plant models (the runnable window motor)
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
