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

# ---------------------------------------------------------------------------
# GENERATED FILE - DO NOT EDIT.
#
# Expanded from catalog/capabilities/*.yaml and verified against the pinned VSS.
# Regenerate with: python scripts/gen_vss_paths.py
# ---------------------------------------------------------------------------

"""Concrete VSS signal paths for every capability in the catalog."""

from __future__ import annotations

from types import MappingProxyType

#: VSS release the paths were verified against.
VSS_VERSION = '6.1'

#: signal id -> {instance: path}
SIGNALS = MappingProxyType({
    # window
    'window.is_open': MappingProxyType({
        'DRIVER_FRONT': 'Vehicle.Cabin.Door.Row1.DriverSide.Window.IsOpen',
        'DRIVER_REAR': 'Vehicle.Cabin.Door.Row2.DriverSide.Window.IsOpen',
        'PASSENGER_FRONT': 'Vehicle.Cabin.Door.Row1.PassengerSide.Window.IsOpen',
        'PASSENGER_REAR': 'Vehicle.Cabin.Door.Row2.PassengerSide.Window.IsOpen',
    }),
    'window.position': MappingProxyType({
        'DRIVER_FRONT': 'Vehicle.Cabin.Door.Row1.DriverSide.Window.Position',
        'DRIVER_REAR': 'Vehicle.Cabin.Door.Row2.DriverSide.Window.Position',
        'PASSENGER_FRONT': 'Vehicle.Cabin.Door.Row1.PassengerSide.Window.Position',
        'PASSENGER_REAR': 'Vehicle.Cabin.Door.Row2.PassengerSide.Window.Position',
    }),
    'window.switch': MappingProxyType({
        'DRIVER_FRONT': 'Vehicle.Cabin.Door.Row1.DriverSide.Window.Switch',
        'DRIVER_REAR': 'Vehicle.Cabin.Door.Row2.DriverSide.Window.Switch',
        'PASSENGER_FRONT': 'Vehicle.Cabin.Door.Row1.PassengerSide.Window.Switch',
        'PASSENGER_REAR': 'Vehicle.Cabin.Door.Row2.PassengerSide.Window.Switch',
    }),
})

#: every concrete path, deduplicated and sorted
ALL_PATHS = (
    'Vehicle.Cabin.Door.Row1.DriverSide.Window.IsOpen',
    'Vehicle.Cabin.Door.Row1.DriverSide.Window.Position',
    'Vehicle.Cabin.Door.Row1.DriverSide.Window.Switch',
    'Vehicle.Cabin.Door.Row1.PassengerSide.Window.IsOpen',
    'Vehicle.Cabin.Door.Row1.PassengerSide.Window.Position',
    'Vehicle.Cabin.Door.Row1.PassengerSide.Window.Switch',
    'Vehicle.Cabin.Door.Row2.DriverSide.Window.IsOpen',
    'Vehicle.Cabin.Door.Row2.DriverSide.Window.Position',
    'Vehicle.Cabin.Door.Row2.DriverSide.Window.Switch',
    'Vehicle.Cabin.Door.Row2.PassengerSide.Window.IsOpen',
    'Vehicle.Cabin.Door.Row2.PassengerSide.Window.Position',
    'Vehicle.Cabin.Door.Row2.PassengerSide.Window.Switch',
)

# Per-signal aliases
WINDOW_POSITION = SIGNALS['window.position']
WINDOW_IS_OPEN = SIGNALS['window.is_open']
WINDOW_SWITCH = SIGNALS['window.switch']

__all__ = ["ALL_PATHS", "SIGNALS", "VSS_VERSION", 'WINDOW_POSITION', 'WINDOW_IS_OPEN', 'WINDOW_SWITCH']
