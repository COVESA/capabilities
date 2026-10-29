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
capability_framework.semantics
==============================
Semantic grounding for capabilities against COVESA standards.

- ``vss``      - the Vehicle Signal Specification signal index (generated from the pin)
- ``vdm``      - the Vehicle Data Model GraphQL schema (composed from the pin)
- ``mapping``  - capability catalog entries and their VSS/VDM mappings
- ``units``    - quantization from capability values to VSS representations
- ``snapshot`` - the live VSS-shaped view of what capabilities are doing

Importing this package needs only the catalog layer (``pyyaml``). ``VdmSchema`` is
resolved lazily, so the runnable example does not depend on ``graphql-core``.
"""

from __future__ import annotations

from typing import Any

from .mapping import (
    CatalogError,
    CapabilitySpec,
    Operation,
    SignalRef,
    VdmRef,
    load_capability,
    load_catalog,
)
from .snapshot import Projector, UnknownSignal, VssSnapshot
from .units import IntegerSignal, OutOfRange, UnitMismatch, clamp, quantize, quantize_percent
from .vss import VssCatalog, VssPathError, VssSignal

__all__ = [
    "CatalogError",
    "CapabilitySpec",
    "IntegerSignal",
    "Operation",
    "OutOfRange",
    "Projector",
    "SignalRef",
    "UnitMismatch",
    "UnknownSignal",
    "VdmRef",
    "VdmSchema",
    "VssCatalog",
    "VssPathError",
    "VssSignal",
    "VssSnapshot",
    "clamp",
    "load_capability",
    "load_catalog",
    "quantize",
    "quantize_percent",
]


def __getattr__(name: str) -> Any:
    """Resolve ``VdmSchema`` on first use so ``graphql-core`` stays optional at import time."""
    if name == "VdmSchema":
        from .vdm import VdmSchema

        return VdmSchema
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
