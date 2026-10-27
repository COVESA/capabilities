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
capability_framework.explorer
=============================
The interactive API catalog and playground views: the stepable boundary diagram
and the physics playground, distilled from the reference explorer.

* :func:`create_blueprint` — Flask routes for the catalog, diagrams, model
  views and the playground simulation.
* :func:`window_motor_bond_graph` — SVG bond graph of the window motor.
"""

from .blueprint import create_blueprint

__all__ = ["create_blueprint"]
