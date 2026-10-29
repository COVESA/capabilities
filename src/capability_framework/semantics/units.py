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
capability_framework.semantics.units
====================================
Quantization and unit rules for crossing from a capability's API into VSS.

A capability API is allowed to be richer than VSS — the window API exposes
``position_pct`` as a float, while VSS models ``Window.Position`` as a
``uint8`` percentage. That difference is fine as long as it is handled at one
place, deliberately, with the range taken from the standard rather than from
local assumptions.

This module is that place.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vss import VssSignal

__all__ = [
    "IntegerSignal",
    "OutOfRange",
    "UnitMismatch",
    "clamp",
    "quantize",
    "quantize_percent",
]


class OutOfRange(ValueError):
    """Raised when a value cannot be represented by the target VSS signal."""


class UnitMismatch(ValueError):
    """Raised when a capability's unit disagrees with the standard's."""


def clamp(value: float, signal: VssSignal) -> float:
    """Clamp *value* into the signal's declared range."""
    if signal.minimum is not None and value < signal.minimum:
        return signal.minimum
    if signal.maximum is not None and value > signal.maximum:
        return signal.maximum
    return value


@dataclass(frozen=True)
class IntegerSignal:
    """The integer encoding of a VSS signal."""

    declared: bool
    minimum: int
    maximum: int


_INTEGER_TYPES = {
    "uint8": (0, 255),
    "uint16": (0, 65535),
    "uint32": (0, 4294967295),
    "uint64": (0, 18446744073709551615),
    "int8": (-128, 127),
    "int16": (-32768, 32767),
    "int32": (-2147483648, 2147483647),
    "int64": (-9223372036854775808, 9223372036854775807),
}


def integer_type(signal: VssSignal) -> IntegerSignal | None:
    """The integer bounds for *signal*, or ``None`` if it is not an integer type."""
    if not signal.datatype or signal.datatype not in _INTEGER_TYPES:
        return None
    type_min, type_max = _INTEGER_TYPES[signal.datatype]
    minimum = type_min if signal.minimum is None else max(type_min, int(signal.minimum))
    maximum = type_max if signal.maximum is None else min(type_max, int(signal.maximum))
    return IntegerSignal(declared=True, minimum=minimum, maximum=maximum)


def quantize(value: float, signal: VssSignal) -> float | int | bool | str:
    """
    Convert a capability value into the representation the standard declares.

    - integer datatypes are clamped to the VSS range, then rounded half-up
    - everything else is clamped only

    The range always comes from the pinned standard, never from the caller.
    """
    if signal.datatype == "boolean":
        return bool(value)
    if signal.datatype == "string":
        return str(value)

    bounds = integer_type(signal)
    if bounds is not None:
        clamped = clamp(float(value), signal)
        return int(clamped + 0.5) if clamped >= 0 else -int(-clamped + 0.5)
    return clamp(float(value), signal)


def quantize_percent(value: float, signal: VssSignal, *, percent_unit: str = "percent") -> int:
    """
    Quantize a percentage into a VSS integer percentage signal.

    Raises ``UnitMismatch`` if the standard does not express the signal as a
    percentage, and ``OutOfRange`` if the value is outside the declared range —
    a capability that asks for 140% is a bug, not something to silently clamp.
    """
    if signal.unit != percent_unit:
        raise UnitMismatch(
            f"{signal.path} is in {signal.unit!r}, not {percent_unit!r}; "
            "convert units before quantizing"
        )
    if not signal.accepts(float(value)):
        raise OutOfRange(
            f"{value!r} is outside {signal.path} range "
            f"[{signal.minimum}, {signal.maximum}]"
        )
    quantized = quantize(value, signal)
    return int(quantized)
