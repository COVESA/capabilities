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
domain/models/capability_diagram.py
===================================
Pure-Python SVG generators for capability architecture visualisation.

Two complementary views are produced per capability, both data-driven from
the API-catalog descriptor (so any capability renders automatically):

  1. boundary  — I/O block diagram (the capability as a black box):
       • Northbound typed Request command in  (left)
       • VehicleState precondition subscribe   (top)
       • State response + EventBus publish out (right)
       • Southbound ActuatorPort → Hardware    (bottom)
     The internal block lists the mandatory five-phase pipeline
     (ARBITRATE → PRECONDITION → SAFETY → ACTUATOR → PUBLISH).

  2. architecture — upstream/downstream context per the SDV layer topology
     defined in architecture-guardrails.yaml:
       Feature / App / Orchestrator
         → (Northbound API, typed Request)
       Capability Manager  ◄── VehicleStateDeterminator (VEHICLE_STATE)
         → (Southbound API, ActuatorPort)
       Hardware Binding (Sim / SOME-IP / CAN)
       … and the EventBus state topic this manager owns.

No external dependencies — emits an SVG string.
"""

from __future__ import annotations

import html
from typing import Any


# ---------------------------------------------------------------------------
# Minimal self-contained SVG helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape text for SVG element content and quoted attributes."""
    return html.escape(str(text), quote=True)


def _box(x: float, y: float, w: float, h: float, *, fill: str, stroke: str = "#222",
         rx: float = 8, sw: float = 1.5, dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def _text(x: float, y: float, s: str, *, size: float = 12, fill: str = "#0d1117",
          anchor: str = "middle", weight: str = "normal", italic: bool = False,
          family: str = "monospace") -> str:
    style = ' font-style="italic"' if italic else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" '
            f'font-family="{family}"{style}>{_esc(s)}</text>')


def _multiline(x: float, y: float, lines: list[str], *, size: float = 11,
               fill: str = "#0d1117", anchor: str = "middle", weight: str = "normal",
               line_h: float = 15, family: str = "monospace") -> str:
    out = []
    for i, ln in enumerate(lines):
        out.append(_text(x, y + i * line_h, ln, size=size, fill=fill,
                         anchor=anchor, weight=weight, family=family))
    return "\n".join(out)


def _arrow(x1: float, y1: float, x2: float, y2: float, *, colour: str = "#444",
           sw: float = 2.0, dash: str = "", marker: str = "arrow", marker_start: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#{marker})"' if marker else ""
    ms = f' marker-start="url(#{marker_start})"' if marker_start else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{colour}" stroke-width="{sw}"{d}{ms}{m}/>')


def _svg_header(width: float, height: float) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" style="background:#0d1117;'
        f'font-family:monospace">'
        '<defs>'
        '<marker id="arrow" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#8b949e"/></marker>'
        '<marker id="arrowStart" markerWidth="9" markerHeight="7" refX="1" refY="3.5" '
        'orient="auto"><path d="M8,0 L0,3.5 L8,7 Z" fill="#8b949e"/></marker>'
        '<marker id="arrowG" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#3fb950"/></marker>'
        '<marker id="arrowGStart" markerWidth="9" markerHeight="7" refX="1" refY="3.5" '
        'orient="auto"><path d="M8,0 L0,3.5 L8,7 Z" fill="#3fb950"/></marker>'
        '<marker id="arrowB" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#58a6ff"/></marker>'
        '<marker id="arrowBStart" markerWidth="9" markerHeight="7" refX="1" refY="3.5" '
        'orient="auto"><path d="M8,0 L0,3.5 L8,7 Z" fill="#58a6ff"/></marker>'
        '<marker id="arrowP" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#a371f7"/></marker>'
        '<marker id="arrowM" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#db61a2"/></marker>'
        '<marker id="arrowO" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#f0883e"/></marker>'
        '<marker id="arrowOStart" markerWidth="9" markerHeight="7" refX="1" refY="3.5" '
        'orient="auto"><path d="M8,0 L0,3.5 L8,7 Z" fill="#f0883e"/></marker>'
        '<marker id="arrowT" markerWidth="9" markerHeight="7" refX="7" refY="3.5" '
        'orient="auto"><path d="M0,0 L8,3.5 L0,7 Z" fill="#39c5cf"/></marker>'
        '</defs>'
    )


_PHASES = [
    "1  ARBITRATE   (priority, pre-empt)",
    "2  PRECONDITION (VehicleState)",
    "3  SAFETY CASE  (domain checks)",
    "4  ACTUATOR     (ActuatorPort)",
    "5  PUBLISH      (EventBus + return)",
]


def _derive(cap: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we need out of a catalog descriptor, with fallbacks."""
    d = cap.get("descriptor", {})
    ops = cap.get("operations", [])
    cmd_type = ops[0]["command_type"] if ops else "Request"
    resp_type = ops[0]["response_type"] if ops else "State"
    # The manager block renders "ASIL {tier}", so keep just the tier (e.g. "B"
    # from "ASIL_B") to avoid printing "ASIL ASIL_B".
    asil = str(d.get("asil_tier", "QM"))
    if asil.upper().startswith("ASIL_"):
        asil = asil[len("ASIL_"):]
    return {
        "name": d.get("display_name") or d.get("name", "Capability"),
        "key": (d.get("name", "cap")).lower(),
        "short": (d.get("name", "cap")).upper(),
        "domain": d.get("domain", "body"),
        "asil": asil,
        "version": d.get("api_version", "1.0.0"),
        "nb_ops": d.get("northbound_operations", []),
        "sb_deps": d.get("southbound_dependencies", []),
        "cmd_type": cmd_type,
        "resp_type": resp_type,
        "state_topic": cap.get("state_topic", "state"),
        "has_model": bool(cap.get("system_model")),
    }


# ---------------------------------------------------------------------------
# Southbound physical interface — aligned with the bond graph of each plant
# ---------------------------------------------------------------------------
#
# The ActuatorPort is the Southbound API.  Physically it injects an *effort*
# (the bond-graph SE source) into the actuator plant and reads back a *flow*.
# For the DC-motor capabilities the SE source is a supply Voltage, exactly as
# rendered by seat_motor_bond_graph / window_motor_bond_graph (SE(12 V) → 1-jct
# → GY → mechanical → TF → load).  Showing this in the boundary diagram keeps
# the southbound contract consistent with the physics model and names the
# concrete plant object that lives downstream in the Hardware Binding layer.

_PHYS: dict[str, dict[str, str]] = {
    "window": {
        "effort": "Voltage  V_supply (SE)",
        "flow": "Current  I  (A)",
        "actuator": "Window Lift Motor (DC)",
        "chain": "SE(V) → R,L → GY → J,B → TF → pane",
        "output": "Pane position 0–300 mm",
        "icon": "⚙",
    },
    "seating": {
        "effort": "Voltage  V_supply (SE)",
        "flow": "Current  I  (A)",
        "actuator": "Seat Track Motor (DC)",
        "chain": "SE(V) → R,L → GY → J,B → TF → rail",
        "output": "Seat position 250–400 mm",
        "icon": "⚙",
    },
    "lighting": {
        "effort": "Voltage  V_supply (SE)",
        "flow": "Current  I  (A)",
        "actuator": "LED Array Driver",
        "chain": "SE(V) → R → diode → optical",
        "output": "Luminous flux (lm)",
        "icon": "💡",
    },
    "climate": {
        "effort": "PWM duty / Voltage (SE)",
        "flow": "Current  I  (A)",
        "actuator": "HVAC Blower + Valves",
        "chain": "SE(V) → blower → ṁ air → ΔT",
        "output": "Cabin temperature (°C)",
        "icon": "❄",
    },
    "power_network": {
        "effort": "Bus enable (switch)",
        "flow": "Current  I  (A)",
        "actuator": "Smart Switches / eFuse",
        "chain": "cmd → smart switch → power bus",
        "output": "Energized power buses",
        "icon": "🔌",
    },
    "power_supply": {
        "effort": "Supply envelope (mA)",
        "flow": "Current  I  (A)",
        "actuator": "DC-DC / Alternator Regulator",
        "chain": "SE(V) → regulator → I limit",
        "output": "Granted envelope (mA)",
        "icon": "🔋",
    },
    "voltage_setpoint": {
        "effort": "Setpoint  V_target (SE)",
        "flow": "Current  I  (A)",
        "actuator": "LV Regulator (Z-curve)",
        "chain": "setpoint → regulator → LV rail",
        "output": "LV system voltage (mV)",
        "icon": "⚡",
    },
}


def _phys(key: str) -> dict[str, str]:
    return _PHYS.get(key, {
        "effort": "Voltage  V_supply (SE)",
        "flow": "Current  I  (A)",
        "actuator": "Actuator Plant",
        "chain": "SE(effort) → flow",
        "output": "physical output",
        "icon": "⚙",
    })



# ---------------------------------------------------------------------------
# 1 · Boundary & Deployment Diagrams
# ---------------------------------------------------------------------------

def capability_boundary_svg(cap: dict[str, Any]) -> str:
    """Render the capability's northbound/southbound I/O boundary as SVG.

    Data-driven from the catalog descriptor, so any capability renders
    automatically. Deployment topology is deliberately out of scope here:
    how a capability is mapped onto a particular vehicle's ECUs and buses is
    a downstream concern that belongs in the binding/extension layer, not in
    the capability's own boundary.
    """
    c = _derive(cap)
    pe = _phys(c["key"])
    W, H = 1240, 1040
    s = [_svg_header(W, H)]

    # Animation styling — each .bd-step group can be lit by the client when a
    # northbound request (e.g. moveWindow) is replayed through the pipeline.
    s.append(
        '<style>'
        '.bd-step{transition:opacity .25s ease, filter .25s ease;}'
        'svg.bd-run .bd-step{opacity:.16;}'
        'svg.bd-run .bd-step.bd-on{opacity:1;filter:drop-shadow(0 0 6px #58a6ff);}'
        'svg.bd-run .bd-step.bd-amber{opacity:1;filter:drop-shadow(0 0 6px #d29922);}'
        'svg.bd-run .bd-step.bd-purple{opacity:1;filter:drop-shadow(0 0 6px #a371f7);}'
        'svg.bd-run .bd-step.bd-ok{opacity:1;filter:drop-shadow(0 0 6px #3fb950);}'
        'svg.bd-run .bd-step.bd-err{opacity:1;filter:drop-shadow(0 0 7px #f85149);}'
        '</style>'
    )

    # Title
    s.append(_text(W / 2, 28, f"{c['name']} — Capability Boundary & Layers",
                   size=16, fill="#e6edf3", weight="bold"))

    # Manager geometry (the focus capability) — placed below the NB boundary,
    # paired inside a "Domain" envelope with the Domain Capability Orchestrator.
    mx, my, mw, mh = 430, 360, 360, 285
    cx = mx + mw / 2

    # ── TOP ROW: FOUR peer boxes (Feature · Cross-Domain Apps · Vehicle-Level Mgmt · VehicleState) ──
    # Feature / App (caller)
    fx, fy, fw, fh = 40, 82, 240, 94
    s.append('<g id="bd-feature" class="bd-step">')
    s.append(_box(fx, fy, fw, fh, fill="#21262d", stroke="#58a6ff"))
    s.append(_text(fx + fw / 2, fy + 22, "FEATURE / HMI / APP", size=11,
                   fill="#58a6ff", weight="bold"))
    s.append(_multiline(fx + fw / 2, fy + 42,
                        ["HMI · Passenger App",
                         "Driver · OEM Automation",
                         "AI Agent (MCP)"],
                        size=9, fill="#8b949e", line_h=14))
    s.append('</g>')

    # Cross-Domain Orchestrator FEATURE APPS (peer above NB — plural!)
    cdopx, cdopy, cdopw, cdoph = 290, 82, 280, 94
    s.append('<g id="bd-cdo" class="bd-step">')
    s.append(_box(cdopx, cdopy, cdopw, cdoph, fill="#161b22", stroke="#a371f7", dash="4 3"))
    s.append(_text(cdopx + cdopw / 2, cdopy + 20, "CROSS-DOMAIN ORCH. APPS", size=11,
                   fill="#a371f7", weight="bold"))
    s.append(_multiline(cdopx + cdopw / 2, cdopy + 38,
                        ["macro-mode feature apps:",
                         "Welcome · Camp · Lock Sequence",
                         "call NB APIs; saga rollback"],
                        size=9, fill="#8b949e", line_h=14))
    s.append('</g>')

    # Vehicle-Level Management (peer)
    vmx, vmy, vmw, vmh = 580, 82, 240, 94
    s.append('<g id="bd-vlm" class="bd-step">')
    s.append(_box(vmx, vmy, vmw, vmh, fill="#161b22", stroke="#58a6ff"))
    s.append(_text(vmx + vmw / 2, vmy + 20, "VEHICLE-LEVEL MGMT", size=11,
                   fill="#58a6ff", weight="bold"))
    s.append(_multiline(vmx + vmw / 2, vmy + 38,
                        ["Vehicle Orchestrator (L3) +",
                         "Sys-Opt Runtime",
                         "governance · power modes"],
                        size=9, fill="#8b949e", line_h=14))
    s.append('</g>')

    # VehicleStateDeterminator (right peer, observer)
    dx, dy, dw, dh = 830, 82, 330, 94
    s.append('<g id="bd-determinator" class="bd-step">')
    s.append(_box(dx, dy, dw, dh, fill="#161b22", stroke="#d29922", dash="5 3"))
    s.append(_text(dx + dw / 2, dy + 20, "VehicleStateDeterminator", size=11,
                   fill="#d29922", weight="bold"))
    s.append(_multiline(dx + dw / 2, dy + 38,
                        ["observer — ingests RAW sensor signals",
                         "publishes Topics.VEHICLE_STATE",
                         "on EventBus · BR-007"],
                        size=9, fill="#8b949e", line_h=14))
    s.append('</g>')

    # ── Northbound API — horizontal boundary spanning all four peers ────
    nbx, nby, nbw, nbh = 40, 238, 1120, 30
    s.append('<g id="bd-nb" class="bd-step">')
    s.append(_box(nbx, nby, nbw, nbh, fill="#21262d", stroke="#f0883e", rx=4))
    s.append(_text(nbx + nbw / 2, nby + 20,
                   f"◄──  NORTHBOUND API · Capability Contracts "
                   f"({c['cmd_type']} · frozen dataclass)  ──►",
                   size=11, fill="#f0883e", weight="bold"))
    s.append('</g>')

    # ── Domain envelope (paired module: Domain Cap Orch + Capability Mgr) ──
    envx, envy, envw, envh = 400, 280, 420, 375
    s.append('<g id="bd-domain-env">')
    s.append(_box(envx, envy, envw, envh, fill="#0d1a2b", stroke="#58a6ff",
                  dash="4 3", sw=1.2, rx=10))
    s.append(_text(envx + envw / 2, envy + 18,
                   f"{c['short']} Domain Capability",
                   size=11, fill="#58a6ff", weight="bold"))
    s.append('</g>')

    # Domain Capability Orchestrator (DCO) — sits INSIDE the domain, above Mgr.
    # Drives the manager through its public NB API only (never touches HW).
    dcox, dcoy, dcow, dcoh = 415, 300, 390, 36
    s.append('<g id="bd-dco" class="bd-step">')
    s.append(_box(dcox, dcoy, dcow, dcoh, fill="#161b22", stroke="#a371f7", rx=6))
    s.append(_text(dcox + dcow / 2, dcoy + 22,
                   f"{c['short']} DOMAIN CAPABILITY ORCHESTRATOR", size=11,
                   fill="#a371f7", weight="bold"))
    s.append('</g>')

    # Caller arrows down through the NB API boundary (four peers → NB).
    s.append(_arrow(fx + fw / 2, fy + fh, fx + fw / 2, nby,
                    colour="#58a6ff", marker="arrowB"))            # Feature → NB
    s.append(_arrow(cdopx + cdopw / 2, cdopy + cdoph, cdopx + cdopw / 2, nby,
                    colour="#a371f7", marker="arrowP"))            # CDO Apps → NB
    s.append(_arrow(vmx + vmw / 2, vmy + vmh, vmx + vmw / 2, nby,
                    colour="#58a6ff", marker="arrowB"))            # Vehicle-Level Mgmt → NB

    # Below the NB API: single-capability direct path AND orchestrated path.
    # Direct: NB → Manager (bypasses DCO). Orchestrated: NB → DCO → Manager.
    s.append(_arrow(cx - 90, nby + nbh, cx - 90, my,
                    colour="#f0883e", marker="arrowO"))
    s.append(_arrow(cx + 60, nby + nbh, dcox + dcow / 2 + 60, dcoy,
                    colour="#a371f7", marker="arrowP"))            # NB → DCO
    s.append(_arrow(dcox + dcow / 2, dcoy + dcoh, mx + mw / 2, my,
                    colour="#a371f7", dash="4 3", marker="arrowP"))  # DCO → mgr (via NB API)

    # VehicleStateDeterminator → manager PRECONDITION (subscribe via EventBus,
    # not the NB API — it is observation data, BR-007).
    s.append('<g id="bd-vs" class="bd-step">')
    s.append(_arrow(dx + 80, dy + dh, mx + mw - 30, my,
                    colour="#d29922", dash="5 3", marker="arrow"))
    s.append(_text(dx + 86, dy + dh + 70, "VEHICLE_STATE",
                   size=9, fill="#d29922", anchor="start", italic=True))
    s.append(_text(dx + 86, dy + dh + 82, "(subscribe · EventBus)",
                   size=9, fill="#d29922", anchor="start", italic=True))
    s.append('</g>')

    # ── Central manager block ─────────────────────────────────────────
    s.append('<g id="bd-mgr" class="bd-step">')
    s.append(_box(mx, my, mw, mh, fill="#161b22", stroke="#58a6ff", sw=2.2))
    s.append(_text(cx, my + 24, f"{c['short']} CAPABILITY MANAGER",
                   size=13, fill="#58a6ff", weight="bold"))
    s.append(_text(cx, my + 42, f"ASIL {c['asil']} · v{c['version']}",
                   size=10, fill="#8b949e"))
    s.append('</g>')

    # Five-phase pipeline inside (each phase is its own animatable step)
    py = my + 62
    s.append(_box(mx + 22, py, mw - 44, 162, fill="#0d1117", stroke="#30363d", rx=6))
    for i, ph in enumerate(_PHASES):
        s.append(f'<g id="bd-phase-{i + 1}" class="bd-step">')
        s.append(_text(mx + 34, py + 24 + i * 30, ph, size=11,
                       fill="#e6edf3", anchor="start"))
        s.append('</g>')
    s.append(_text(cx, my + mh - 8,
                   "mandatory order — BR-006", size=9, fill="#8b949e", italic=True))

    # Provisioning-time System Optimisation (greyed, dashed, BR-017) — left.
    sox, soy, sow, soh = 40, 470, 250, 84
    s.append('<g id="bd-sysopt" opacity="0.5">')
    s.append(_box(sox, soy, sow, soh, fill="#0d1117", stroke="#6e7681", dash="5 3"))
    s.append(_text(sox + sow / 2, soy + 20, "SYS-OPT · CONFIG-TIME", size=10,
                   fill="#8b949e", weight="bold"))
    s.append(_multiline(sox + sow / 2, soy + 38,
                        ["runs once at OTA / factory;",
                         "writes parameter stores —",
                         "not in command flow (BR-017)"],
                        size=8, fill="#6e7681", line_h=13))
    s.append(_arrow(sox + sow, soy + 20, mx, my + 200,
                    colour="#6e7681", dash="4 3", marker="arrow"))
    s.append('</g>')

    # ── RIGHT outputs: State response + EventBus publish ──────────────
    rsx, rsy, rsw, rsh = 850, 360, 310, 80
    s.append('<g id="bd-resp" class="bd-step">')
    s.append(_box(rsx, rsy, rsw, rsh, fill="#21262d", stroke="#3fb950"))
    s.append(_text(rsx + rsw / 2, rsy + 22, "STATE RESPONSE (sync reply)", size=11,
                   fill="#3fb950", weight="bold"))
    s.append(_multiline(rsx + rsw / 2, rsy + 42,
                        [f"{c['resp_type']} (frozen) — returned to the caller",
                         "status · request_id · api_version"],
                        size=10, fill="#e6edf3"))
    s.append(_arrow(mx + mw, my + 70, rsx, rsy + rsh / 2,
                    colour="#3fb950", marker="arrowG"))
    s.append('</g>')

    ebx, eby, ebw, ebh = 850, 470, 310, 70
    s.append('<g id="bd-eb" class="bd-step">')
    s.append(_box(ebx, eby, ebw, ebh, fill="#21262d", stroke="#db61a2"))
    s.append(_text(ebx + ebw / 2, eby + 22, "EVENTBUS PUBLISH", size=11,
                   fill="#db61a2", weight="bold"))
    s.append(_multiline(ebx + ebw / 2, eby + 42,
                        [f"Topics.{c['state_topic'].upper()}",
                         "async broadcast · one publisher (BR-011)"],
                        size=10, fill="#e6edf3"))
    s.append(_arrow(mx + mw, my + 200, ebx, eby + ebh / 2,
                    colour="#db61a2", marker="arrowM"))
    s.append('</g>')

    # ── BOTTOM output: Southbound ActuatorPort → physical plant ───────
    sbx, sby, sbw, sbh = 460, 685, 300, 85
    s.append('<g id="bd-sb" class="bd-step">')
    s.append(_box(sbx, sby, sbw, sbh, fill="#21262d", stroke="#f0883e"))
    s.append(_text(sbx + sbw / 2, sby + 20, "◄── SOUTHBOUND API · ActuatorPort ──►",
                   size=11, fill="#f0883e", weight="bold"))
    s.append(_multiline(sbx + sbw / 2, sby + 38,
                        ["calls: " + (", ".join(c["sb_deps"][:2]) or "—"),
                         f"effort out ▸ {pe['effort']}",
                         f"flow back ◂ {pe['flow']}"],
                        size=10, fill="#e6edf3", line_h=15))
    s.append(_arrow(cx, my + mh, sbx + sbw / 2, sby,
                    colour="#f0883e", sw=2.4, marker="arrowO", marker_start="arrowOStart"))
    s.append('</g>')

    # ── Downstream physical plant object (from the bond graph) ────────
    pmx, pmy, pmw, pmh = 430, 860, 360, 96
    s.append('<g id="bd-plant" class="bd-step">')
    s.append(_box(pmx, pmy, pmw, pmh, fill="#161b22", stroke="#f0883e", sw=2.2))
    s.append(_text(pmx + pmw / 2, pmy + 24, f"{pe['icon']}  {pe['actuator']}",
                   size=12, fill="#f0883e", weight="bold"))
    s.append(_multiline(pmx + pmw / 2, pmy + 44,
                        [f"bond graph: {pe['chain']}",
                         f"output ▸ {pe['output']}"],
                        size=10, fill="#8b949e", line_h=15))
    s.append(_text(pmx + pmw / 2, pmy + pmh - 6,
                   "Hardware Binding plant — see Transfer Function / BOND graph",
                   size=9, fill="#6e7681", italic=True))
    s.append(_arrow(sbx + sbw / 2, sby + sbh, pmx + pmw / 2, pmy,
                    colour="#f0883e", sw=2.4, marker="arrowO", marker_start="arrowOStart"))
    s.append(_text(sbx + sbw / 2 + 10, (sby + sbh + pmy) / 2, "effort out ▼ / ▲ flow back (Hall pulses)",
                   size=9, fill="#f0883e", anchor="start"))
    s.append('</g>')

    s.append("</svg>")
    return "\n".join(s)



# ---------------------------------------------------------------------------
# 2 · Architecture context (upstream / downstream) diagram
# ---------------------------------------------------------------------------

def capability_architecture_svg(cap: dict[str, Any]) -> str:
    """Render the capability in its layer-topology context as SVG."""
    c = _derive(cap)
    W, H = 1080, 720
    s = [_svg_header(W, H)]

    cx = W / 2

    s.append(_text(cx, 28, f"{c['name']} — Architecture Context",
                   size=16, fill="#e6edf3", weight="bold"))
    s.append(_text(cx, 47, "upstream callers · this manager · downstream actuation  (per architecture-guardrails.yaml)",
                   size=10, fill="#8b949e", italic=True))

    # ── UPSTREAM tier: four peers ABOVE the NB boundary ──────────────
    # Feature / HMI / App
    fx1, fy1, fw1, fh1 = 40, 70, 280, 60
    s.append(_box(fx1, fy1, fw1, fh1, fill="#161b22", stroke="#8b949e"))
    s.append(_text(fx1 + fw1 / 2, fy1 + 24, "Feature / HMI / App", size=12,
                   fill="#e6edf3", weight="bold"))
    s.append(_text(fx1 + fw1 / 2, fy1 + 44, "business intent — never bypasses the NB API",
                   size=10, fill="#8b949e"))

    # Cross-Domain Orchestrator Feature Apps (peer above NB — multiple)
    cdox, cdoy, cdow, cdoh = 340, 70, 380, 60
    s.append(_box(cdox, cdoy, cdow, cdoh, fill="#161b22", stroke="#a371f7", dash="5 3"))
    s.append(_text(cdox + cdow / 2, cdoy + 22, "Cross-Domain Orchestrator Apps", size=12,
                   fill="#a371f7", weight="bold"))
    s.append(_text(cdox + cdow / 2, cdoy + 42,
                   "macro feature apps (Welcome / Camp / Lock) — saga rollback",
                   size=10, fill="#8b949e"))

    # Vehicle-Level Management
    vlx, vly, vlw, vlh = 740, 70, 300, 60
    s.append(_box(vlx, vly, vlw, vlh, fill="#161b22", stroke="#8b949e"))
    s.append(_text(vlx + vlw / 2, vly + 24, "Vehicle-Level Mgmt", size=12,
                   fill="#e6edf3", weight="bold"))
    s.append(_text(vlx + vlw / 2, vly + 44,
                   "platform power policy · vehicle lifecycle governance",
                   size=10, fill="#8b949e"))

    # Arrows from all three peers down to the NB boundary
    # NB boundary line
    nby = 160
    s.append(f'<line x1="60" y1="{nby}" x2="{W-60}" y2="{nby}" '
             f'stroke="#58a6ff" stroke-width="1.5" stroke-dasharray="8 4"/>')
    s.append(_text(W - 70, nby - 6, "NORTHBOUND API BOUNDARY  (Capability Contracts)",
                   size=10, fill="#58a6ff", anchor="end", italic=True))
    s.append(_arrow(fx1 + fw1 / 2, fy1 + fh1, fx1 + fw1 / 2, nby,
                    colour="#58a6ff", marker="arrowB"))
    s.append(_arrow(cdox + cdow / 2, cdoy + cdoh, cdox + cdow / 2, nby,
                    colour="#a371f7", marker="arrowP"))
    s.append(_arrow(vlx + vlw / 2, vly + vlh, vlx + vlw / 2, nby,
                    colour="#58a6ff", marker="arrowB"))
    s.append(_text(cdox + cdow / 2 + 8, nby + 26, c["cmd_type"],
                   size=10, fill="#58a6ff", anchor="start"))

    # ── Domain envelope (paired module below NB) ─────────────────────
    envx, envy, envw, envh = 240, 200, 600, 320
    s.append(_box(envx, envy, envw, envh, fill="#0d1a2b", stroke="#58a6ff",
                  dash="4 3", sw=1.2, rx=10))
    s.append(_text(envx + envw / 2, envy + 18,
                   f"{c['short']} Domain Capability",
                   size=11, fill="#58a6ff", weight="bold"))

    # Domain Capability Orchestrator (paired, sits inside envelope above Mgr)
    dcox, dcoy, dcow, dcoh = 280, 222, 520, 38
    s.append(_box(dcox, dcoy, dcow, dcoh, fill="#161b22", stroke="#a371f7", rx=6))
    s.append(_text(dcox + dcow / 2, dcoy + 24,
                   f"{c['short']} Domain Capability Orchestrator", size=12,
                   fill="#a371f7", weight="bold"))
    s.append(_arrow(dcox + dcow / 2, dcoy + dcoh, cx, 290,
                    colour="#a371f7", dash="4 3", marker="arrowP"))

    # ── THIS capability manager (highlighted, inside the domain envelope) ──
    mgx, mgy, mgw, mgh = 330, 300, 420, 200
    s.append(_box(mgx, mgy, mgw, mgh, fill="#1c2333", stroke="#58a6ff", sw=2.6))
    s.append(_text(cx, mgy + 26, f"{c['short']} CAPABILITY MANAGER", size=13,
                   fill="#58a6ff", weight="bold"))
    s.append(_text(cx, mgy + 44, f"domain={c['domain']} · ASIL {c['asil']} · v{c['version']}",
                   size=10, fill="#8b949e"))
    s.append(_multiline(cx, mgy + 74,
                        ["ARBITRATE → PRECONDITION → SAFETY",
                         "→ ACTUATOR → PUBLISH",
                         "can_execute() · API_VERSION constant"],
                        size=10, fill="#e6edf3", line_h=16))

    # ── PEER: VehicleStateDeterminator ────────────────────────────────
    vsx, vsy, vsw, vsh = 800, 285, 250, 90
    s.append(_box(vsx, vsy, vsw, vsh, fill="#161b22", stroke="#d29922"))
    s.append(_text(vsx + vsw / 2, vsy + 22, "VehicleStateDeterminator", size=11,
                   fill="#d29922", weight="bold"))
    s.append(_multiline(vsx + vsw / 2, vsy + 42,
                        ["publishes VEHICLE_STATE",
                         "observation-only (BR-007)",
                         "never calls capabilities"],
                        size=9, fill="#8b949e", line_h=14))
    s.append(_arrow(vsx, vsy + vsh / 2, mgx + mgw, mgy + 70,
                    colour="#d29922", marker="arrow"))
    s.append(_text((vsx + mgx + mgw) / 2, mgy + 60, "subscribe",
                   size=9, fill="#d29922", italic=True))

    # ── PEER: EventBus state topic (owned) ────────────────────────────
    ebx, eby, ebw, ebh = 30, 285, 250, 90
    s.append(_box(ebx, eby, ebw, ebh, fill="#161b22", stroke="#bc8cff"))
    s.append(_text(ebx + ebw / 2, eby + 22, "EventBus", size=11,
                   fill="#bc8cff", weight="bold"))
    s.append(_multiline(ebx + ebw / 2, eby + 42,
                        [f"Topics.{c['state_topic'].upper()}",
                         "owned by this manager",
                         "BR-008 / BR-011"],
                        size=9, fill="#8b949e", line_h=14))
    s.append(_arrow(mgx, mgy + 100, ebx + ebw, eby + ebh / 2,
                    colour="#bc8cff", marker="arrowP"))
    s.append(_text((ebx + ebw + mgx) / 2, mgy + 90, "publish",
                   size=9, fill="#bc8cff", italic=True))

    # SB boundary line
    sby = 470
    s.append(f'<line x1="60" y1="{sby}" x2="{W-60}" y2="{sby}" '
             f'stroke="#f0883e" stroke-width="1.5" stroke-dasharray="8 4"/>')
    s.append(_text(W - 70, sby - 6, "SOUTHBOUND API BOUNDARY  (ActuatorPort only)",
                   size=10, fill="#f0883e", anchor="end", italic=True))
    s.append(_arrow(cx, mgy + mgh, cx, sby + 40, colour="#f0883e", marker="arrowO"))

    # ── ActuatorPort ──────────────────────────────────────────────────
    apx, apy, apw, aph = 330, 510, 420, 56
    s.append(_box(apx, apy, apw, aph, fill="#161b22", stroke="#f0883e"))
    s.append(_text(cx, apy + 22, "ActuatorPort (abstract interface)", size=12,
                   fill="#f0883e", weight="bold"))
    s.append(_text(cx, apy + 40, ", ".join(c["sb_deps"][:3]) or "actuator methods",
                   size=10, fill="#8b949e"))
    s.append(_arrow(cx, apy + aph, cx, 600, colour="#f0883e", marker="arrowO"))

    # ── Hardware Binding ──────────────────────────────────────────────
    hbx, hby, hbw, hbh = 300, 600, 480, 70
    s.append(_box(hbx, hby, hbw, hbh, fill="#161b22", stroke="#8b949e"))
    s.append(_text(cx, hby + 24, "Hardware Binding", size=12,
                   fill="#e6edf3", weight="bold"))
    s.append(_multiline(cx, hby + 44,
                        ["SimulatorActuatorPort / SOME-IP / CAN adapter",
                         "no domain concepts here — BR-010"],
                        size=10, fill="#8b949e", line_h=15))

    s.append("</svg>")
    return "\n".join(s)


# ---------------------------------------------------------------------------
# 3 · Animated architecture topology (client-side rendered from JSON)
# ---------------------------------------------------------------------------

def build_capability_arch_model(cap: dict[str, Any]) -> dict[str, Any]:
    """
    Build the layered architecture topology for one capability, derived
    entirely from its catalog descriptor (data-driven — all four capabilities
    render with no per-capability code).

    The client renders these `layers` and animates a request flow by pulsing
    nodes addressed via stable ids:

        feature             Feature / App           (left caller)
        sysopt_config       System Optimisation cfg (provisioning, dashed/greyed)
        vehicle_mgmt        Vehicle-Level Management (optimiser + vehicle orch)
        nb_api              Northbound API boundary  (orange)
        cdo                 Cross-Domain Orchestrator
        capability_manager  this capability (5-phase pipeline)
        sb_api              Southbound API boundary  (purple)
        actuator_port       ActuatorPort interface (physical effort/flow port)
        hardware_binding    Hardware Binding / physical plant (bond-graph plant)
        state_determinator  VehicleStateDeterminator (dashed observer, right)

    Tracks: caller | platform | boundary | capability | observer
    The center stack (boundary + capability) animates top→bottom on a command
    and bottom→top on the response. vehicle_mgmt and cdo sit in the command
    chain (Feature → Vehicle Management → NB API → CDO → Capability Manager),
    matching the SDV-Capability-Architecture layer diagram.

    Guardrails honoured:
      • Hardware details (CAN/SOME-IP/ECU) appear only in hardware_binding.
      • Northbound layer uses typed Request/State language only.
      • state_determinator is observation-only (BR-007): publishes VEHICLE_STATE,
        has no arrows into capabilities, never called by a capability.
    """
    c = _derive(cap)
    ph = _phys(c["key"])

    name = c["name"]
    nb_ops = ", ".join(c["nb_ops"]) or c["cmd_type"]
    sb_deps = ", ".join(c["sb_deps"]) or "ActuatorPort methods"

    layers = [
        # ── Left caller ────────────────────────────────────────────────
        {"id": "feature", "name": "Feature / App", "track": "caller",
         "order": 0, "color": "#58a6ff",
         "detail": "Drives a Business Intent. Calls the Northbound API with a "
                   "typed, immutable Request; presents a verified RequestSource."},

        # ── Cross-Domain Orchestrator Feature Apps (peer above NB, plural) ─
        {"id": "cdo", "name": "Cross-Domain Orchestrator Apps", "track": "caller",
         "order": 1, "color": "#a371f7",
         "detail": "Macro-mode feature apps (Welcome / Camp / Lock Sequence) — peers "
                   "above the Northbound API alongside Apps and Vehicle-Level Mgmt. Compose 2+ "
                   "capabilities via their public NB APIs; own saga rollback."},

        # ── Provisioning-time plane (greyed, dashed, not in command flow) ─
        {"id": "sysopt_config", "name": "System Optimisation — Config", "track": "platform",
         "order": 0, "provisioning": True, "color": "#8b949e",
         "detail": "Provisioning-time optimisation (flash/OTA). Writes capability "
                   "parameter stores (e.g. SUV vs car travel limits). Not in the "
                   "runtime command flow (BR-017)."},

        # ── Vehicle-Level Management (peer above NB) ───────────────────
        {"id": "vehicle_mgmt", "name": "Vehicle-Level Management", "track": "caller",
         "order": 2, "color": "#58a6ff",
         "detail": "System Optimisation (runtime) + Vehicle Orchestrator. Sets "
                   "platform power policy and triggers Cross-Domain Orchestrator "
                   "feature apps on platform events (charging start, OTA lockout); "
                   "never bypasses the NB API to hardware (BR-017)."},

        # ── NB boundary ────────────────────────────────────────────────
        {"id": "nb_api", "name": "── Northbound API ──", "track": "boundary",
         "order": 3, "boundary": "nb", "color": "#f0883e",
         "detail": "Capability Contracts — typed Request in, typed State out. "
                   "Operations: " + nb_ops},

        # ── Domain Capability Orchestrator (paired with Manager, below NB) ──
        {"id": "dco", "name": f"{c['short']} Domain Capability Orchestrator",
         "track": "capability", "order": 4, "color": "#a371f7",
         "detail": "Intra-domain multi-instance sequencing (cascade / sync / stage). "
                   "Paired with the Capability Manager below the NB API; drives it "
                   "strictly through the Manager's public NB primitives — never "
                   "touches ActuatorPort directly."},

        {"id": "capability_manager", "name": name, "track": "capability",
         "order": 5, "color": "#a371f7",
         "detail": f"{name} ({c['asil']}). Five-phase pipeline: arbitrate → "
                   f"precondition → safety → actuator → publish {c['state_topic']}."},

        {"id": "sb_api", "name": "── Southbound API ──", "track": "boundary",
         "order": 6, "boundary": "sb", "color": "#a371f7",
         "detail": "ActuatorPort interface. Dependencies: " + sb_deps},

        {"id": "actuator_port", "name": "ActuatorPort", "track": "capability",
         "order": 7, "color": "#a371f7",
         "detail": f"Abstract actuator interface. Injects effort ▸ {ph['effort']}; "
                   f"reads back flow ◂ {ph['flow']}. No hardware details above this line."},

        {"id": "hardware_binding", "name": f"{ph['icon']} Hardware Binding · {ph['actuator']}",
         "track": "capability", "order": 8, "color": "#6e7681",
         "detail": f"{ph['actuator']} — bond graph {ph['chain']} ▸ {ph['output']}. "
                   "Simulator / SOME-IP / CAN adapter; wire-format translation only (BR-010)."},

        # ── Right observer (off the command path) ──────────────────────
        {"id": "state_determinator", "name": "VehicleStateDeterminator", "track": "observer",
         "order": 0, "color": "#f0883e",
         "detail": "Observation-only (BR-007). Ingests RAW sensor signals (ignition, gear, "
                   "OTA, voltage) and publishes VEHICLE_STATE on the EventBus; never "
                   "calls capabilities. Feature and Manager subscribe."},
    ]

    return {
        "capability": c["key"],
        "display_name": name,
        "asil_tier": c["asil"],
        "domain": c["domain"],
        "physical": ph,
        "layers": layers,
    }

