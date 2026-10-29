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
capability_framework.checker
============================
The capability rule checker: proves a catalog entry against the pinned standards
and against its own contract.

Run it with ``capability-check``. Rules are grouped by prefix:

======  ======================================================
Prefix  Concern
======  ======================================================
CAP-0   catalog structure (identity, versioning, taxonomy, links)
CAP-1   northbound contract ↔ catalog agreement
CAP-2   VSS grounding (path, datatype, unit, direction)
CAP-3   VDM grounding (type, field, instance tags, fidelity)
======  ======================================================
"""

from __future__ import annotations

from .engine import CheckContext, report, run_checks
from .rules import Finding, Severity

__all__ = ["CheckContext", "Finding", "Severity", "report", "run_checks"]
