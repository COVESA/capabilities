# Baselined Capability Definition — `moveWindow`

> **Status:** BASELINED example.
> **Owning package:** window capability.
> **Contract:** [`../../contracts/window-api.yaml`](../../contracts/window-api.yaml).

This is a distilled, generic capability definition. It is the worked example for
how one capability is described: its metadata, its interfaces, and the
requirements that prove it behaves.

---

## 1. Capability metadata

| Attribute | Value | Convention |
|---|---|---|
| **Identity (`id`)** | `urn:capability:body:moveWindow` | Stable URI format |
| **Name** | `moveWindow` (slug: `move_window`) | `verbNoun` standard |
| **Display name** | "Window Movement Control" | Catalog display |
| **Owning system** | `urn:system:body:windows` (*Windows System*) | System of interest |
| **Domain** | `body` | Layer taxonomy |
| **API version** | `2.0.0` | Independent versioning per capability |
| **ASIL tier** | `ASIL_B` (pinch protection interlock) | Safety classification |
| **State topic** | `WINDOW_STATE` (`window_state`) | Single publisher per topic |

---

## 2. Interface contracts

### 2.1 Provided interface: `WindowControl` (northbound)

- **Operations:**
  1. `moveWindow(cmd: MoveWindowCommand) -> WindowState` (async, arbitrated)
  2. `releaseWindow(request_id: UUID) -> None` (sync, non-arbitrated)
  3. `canExecuteWindow(cmd: MoveWindowCommand) -> WindowState` (sync, zero side effects)
  4. `getWindowState(zone: WindowZone) -> WindowState` (sync query)
  5. `getWindowSystemModel() -> WindowSystemModel` (introspection query)
- **Data types:**
  - `WindowZone`: `DRIVER_FRONT`, `PASSENGER_FRONT`, `DRIVER_REAR`, `PASSENGER_REAR`, `ALL`
  - `WindowStatus`: `STATIONARY`, `MOVING`, `PINCHED`, `INHIBITED`, `REJECTED`
  - `WindowInhibitReason`: `POWER_OFF`, `VEHICLE_IN_MOTION_LOCK`, `OTA_IN_PROGRESS`,
    `UNDERVOLTAGE`, `OUT_OF_RANGE`, `PINCH_DETECTED`, `THERMAL_PROTECTION`,
    `CHILD_LOCK_ACTIVE`, `WINDOW_BUSY`, `ACTUATOR_FAULT`, `RELEASED`, `TIMEOUT`

### 2.2 Required interfaces (southbound and infrastructure)

1. **`WindowActuation` (hardware abstraction)** — provided by the actuator binding.
   Operations: `move_window(zone, target_pct) -> float`, `get_window_position(zone) -> float`.
2. **`PowerAuthorization` (infrastructure service)** — provided by the power system.
   Operations: `request_power(budget_w) -> PowerGrant`, `release_power()`.
3. **`VehicleStateObservation` (infrastructure service)** — provided by the
   vehicle-state source. Observations: `power_state`, `ota_state`, `supply_voltage_v`.

---

## 3. System definition (SysML v2, textual)

```sysml
package BodyWindowsDomain {
    private import ScalarValues::*;

    part def WindowManagerFE {
        port control  : WindowControlAPI;
        port actuator : ~WindowActuatorPort;
        port power    : ~PowerAuthorizationPort;

        attribute maxPinchForceN : Real = 100.0;
        attribute autoReversePositionDeltaPct : Real = 15.0;
    }

    part def WindowsSystem {
        part manager : WindowManagerFE;
        port externalControl : WindowControlAPI;

        connect externalControl to manager.control;
    }
}
```

---

## 4. Requirements and verification links

| Requirement ID | Statement | Governed element | Verification case |
|---|---|---|---|
| `REQ-WIN-001` | The window shall move to the commanded target position (0–100%) within 4 seconds. | `moveWindow` operation | `test_successful_move` |
| `REQ-WIN-002` | The window shall reverse direction if pinch resistance exceeds 100 N. | Safety gate & pinch handler | `test_pinch_detection_auto_reverses` |
| `REQ-WIN-003` | Commands shall be inhibited if vehicle power is OFF or voltage < 12.0 V. | Precondition check | `test_undervoltage_inhibits` |
| `REQ-WIN-004` | Commands shall be rejected if a higher-priority source holds the zone lock. | Arbitration phase | `test_driver_preempts_app` |

---

## 5. Pipeline phases

For every `moveWindow` call:

1. **ARBITRATE** — first-in-wins priority queue; a higher-priority source
   pre-empts immediately.
2. **PRECONDITION** — check vehicle state (power, OTA).
3. **SAFETY** — validate position range, voltage, and thermal state.
4. **ACTUATOR** — delegate to the actuator port; monitor for a pinch.
5. **PUBLISH** — emit `WindowState` on the event bus.

## See also

- [`window-system.md`](window-system.md) — the system diagram and behaviour.
- [`../../contracts/window-api.yaml`](../../contracts/window-api.yaml) — the
  northbound contract.
