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
capability_framework.explorer.bond_graph
========================================
Pure-Python SVG renderer for the window motor's 4-stage bond graph.

The graph mirrors the physics in :mod:`capability_framework.models.window_motor`:
an effort source (supply voltage) drives a coil (R, L), a gyrator (GY) couples
the electrical and mechanical domains, an inertia (J) and bearing (B) carry the
rotational energy, and a transformer (TF) turns it into the linear pane motion
against its load.

No external dependencies — emits an SVG string.
"""

from __future__ import annotations

import html
from typing import Any

_EFFORT_COLOUR = "#f0883e"
_FLOW_COLOUR = "#58a6ff"


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _stage(x: float, y: float, w: float, h: float, element: str, label: str,
           detail: str, colour: str) -> str:
    return (
        f'<g>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
        f'fill="#161b22" stroke="{colour}" stroke-width="1.6"/>'
        f'<text x="{x + w / 2:.1f}" y="{y + 24:.1f}" font-size="13" fill="{colour}" '
        f'text-anchor="middle" font-weight="bold" font-family="monospace">{_esc(element)}</text>'
        f'<text x="{x + w / 2:.1f}" y="{y + 44:.1f}" font-size="11" fill="#e6edf3" '
        f'text-anchor="middle" font-family="monospace">{_esc(label)}</text>'
        f'<text x="{x + w / 2:.1f}" y="{y + 62:.1f}" font-size="10" fill="#8b949e" '
        f'text-anchor="middle" font-family="monospace">{_esc(detail)}</text>'
        f'</g>'
    )


def window_motor_bond_graph(params: dict[str, Any] | None = None) -> str:
    """Render the window motor bond graph as an SVG string."""
    p = params or {}

    def val(key: str, default: str, scale: float = 1.0, unit: str = "") -> str:
        v = p.get(key)
        if v is None:
            return default
        try:
            return f"{float(v) * scale:g}{unit}"
        except (TypeError, ValueError):
            return default

    w, h = 1120, 320
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" style="background:#0d1117;font-family:monospace">',
        '<defs>'
        '<marker id="bg-arrow" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#8b949e"/></marker>'
        '</defs>',
        f'<text x="{w / 2:.1f}" y="30" font-size="15" fill="#e6edf3" text-anchor="middle" '
        f'font-weight="bold">Window Lift Motor — 4-stage bond graph</text>',
    ]

    stages = [
        ("SE", "Voltage source", f"{val('supply_voltage_v', '12')} V", _EFFORT_COLOUR),
        ("R, L", "Coil", f"R {val('motor_resistance_ohm', '—')} Ω · L", _FLOW_COLOUR),
        ("GY", "Gyrator", "electrical ↔ mechanical", "#a371f7"),
        ("J, B", "Rotor inertia + damping", f"J · B {val('linkage_damping', '—')}", "#3fb950"),
        ("TF", "Rack & pinion", f"gain {val('actuator_gain_m_rad', '—')} m/rad", "#db61a2"),
    ]
    box_w, box_h, gap = 190.0, 90.0, 32.0
    total = len(stages) * box_w + (len(stages) - 1) * gap
    x = (w - total) / 2
    y = 130.0
    for element, label, detail, colour in stages:
        parts.append(_stage(x, y, box_w, box_h, element, label, detail, colour))
        if element != stages[-1][0]:
            parts.append(
                f'<line x1="{x + box_w:.1f}" y1="{y + box_h / 2:.1f}" '
                f'x2="{x + box_w + gap:.1f}" y2="{y + box_h / 2:.1f}" '
                f'stroke="#8b949e" stroke-width="2" marker-end="url(#bg-arrow)"/>'
            )
        x += box_w + gap

    parts.append(
        f'<text x="{w / 2:.1f}" y="{y + box_h + 40:.1f}" font-size="11" fill="#8b949e" '
        f'text-anchor="middle">output ▸ pane position 0–300 mm  ·  effort in ▸ voltage  ·  '
        f'flow back ◂ current</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
