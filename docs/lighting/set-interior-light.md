# Capability Definition — `setInteriorLight`

> **Status:** DRAFT example, modelled on [`moveWindow`](../windows/move-window.md).
> **Owning package:** lighting capability.
> **Contract:** [`../../contracts/lighting-api.yaml`](../../contracts/lighting-api.yaml).
> **Catalog entry:** [`../../catalog/capabilities/lighting.yaml`](../../catalog/capabilities/lighting.yaml).

This is the interior lighting counterpart of the window capability. It has the same
shape: a per-zone command, the same five-phase pipeline, typed reasons, and a
VSS projection checked against the pinned standard.

---

## 1. Capability metadata

| Attribute | Value | Convention |
|---|---|---|
| **Identity (`id`)** | `urn:capability:body:setInteriorLight` | Stable URI format |
| **Name** | `setInteriorLight` (slug: `set_interior_light`) | `verbNoun` standard |
| **Display name** | "Interior Lighting Control" | Catalog display |
| **Owning system** | `urn:system:body:interiorLighting` (*Interior Lighting System*) | System of interest |
| **Domain** | `body` | Layer taxonomy |
| **API version** | `1.0.0` | Independent versioning per capability |
| **ASIL tier** | `QM` (comfort lighting, no safety interlock) | Safety classification |
| **State topic** | `LIGHTING_STATE` (`lighting_state`) | Single publisher per topic |

---

## 2. Interface contracts

### 2.1 Provided interface: `InteriorLightingControl` (northbound)

- **Operations:**
  1. `setInteriorLight(cmd: SetInteriorLightCommand) -> LightingState` (async, arbitrated)
  2. `releaseInteriorLight(request_id: UUID) -> None` (sync, non-arbitrated)
  3. `canExecuteInteriorLight(cmd: SetInteriorLightCommand) -> LightingState` (sync, zero side effects)
  4. `getInteriorLightState(zone: LightingZone) -> LightingState` (sync query)
- **Data types:**
  - `LightingZone`: `DRIVER_FRONT`, `PASSENGER_FRONT`, `DRIVER_REAR`, `PASSENGER_REAR`, `ALL`
  - `SetInteriorLightCommand`: `zone`, `intensity_pct` (0 = off … 100 = full),
    optional `color` (`"#RRGGBB"`; omitted keeps the current color), `request_id`, `timeout_s`
  - `LightingStatus`: `ON`, `OFF`, `INHIBITED`, `REJECTED`
  - `LightingInhibitReason`: `POWER_OFF`, `OTA_IN_PROGRESS`, `UNDERVOLTAGE`,
    `OUT_OF_RANGE`, `INVALID_COLOR`, `LIGHTING_BUSY`, `ACTUATOR_FAULT`, `RELEASED`, `TIMEOUT`

`moveWindow` → `setInteriorLight` at a glance:

| `moveWindow` | `setInteriorLight` |
|---|---|
| `target_pct` (0 closed … 100 open) | `intensity_pct` (0 off … 100 full) + `color` |
| `WindowStatus` `STATIONARY` / `MOVING` / `PINCHED` | `LightingStatus` `ON` / `OFF` |
| `PINCH_DETECTED`, `THERMAL_PROTECTION` | `INVALID_COLOR`, `ACTUATOR_FAULT` |
| Undervoltage below 12.0 V | Undervoltage below 11.0 V; allowed in `ACC` as well as `ON` |
| `WindowActuatorPort` | `LightingActuatorPort` |

### 2.2 HTTP routes (runnable example)

| Route | Operation |
|---|---|
| `POST /vehicle/lighting/set` | `setInteriorLight`. `200` executed or vehicle-inhibited, `409` lost arbitration, `422` bad intensity/color, `400` malformed |
| `POST /vehicle/lighting/can-execute` | `canExecuteInteriorLight` |
| `POST /vehicle/lighting/release` | `releaseInteriorLight` |
| `GET /vehicle/lighting/state?zone=…` | `getInteriorLightState` |
| `GET /vehicle/lighting/catalog` | The capability descriptor |

```bash
curl -s -X POST http://127.0.0.1:8770/vehicle/lighting/set \
  -H 'Content-Type: application/json' \
  -d '{"zone": "DRIVER_FRONT", "intensity_pct": 60, "color": "#FF8800"}'
```

As with the window, the request source comes from the caller's verified role.
A payload that carries `source` is rejected.

The stepable boundary diagram is at
[`/vehicle/catalog/?cap=lighting&tab=boundary`](http://127.0.0.1:8770/vehicle/catalog/?cap=lighting&tab=boundary).
It replays `setInteriorLight()` through the five phases. The API Explorer
playground at `/vehicle/api-explorer/` runs every lighting operation.

### 2.3 Required interfaces (southbound and infrastructure)

1. **`LightingActuation` (hardware abstraction)**: provided by the light-driver binding.
   - `set_ambient_light(zone, intensity_pct, color) -> LightOutput`
   - `get_ambient_light(zone) -> LightOutput`, where `LightOutput` is `(intensity_pct, color)`
2. **`VehicleStateObservation` (infrastructure service)**: provided by the
   vehicle-state source. Observations: `power_state`, `ota_state`, `supply_voltage_v`.

The runnable example binds `LightingSimulatorPort`. An LED driver settles in
milliseconds, so the binding has no plant model.

---

## 3. VSS and VDM grounding

The zones map to `Vehicle.Cabin.Light.AmbientLight.Row{1,2}.{DriverSide,PassengerSide}`
(VSS 6.1), projected in VDM as `AmbientLight` with `AmbientLight_InstanceTag`.

| Signal id | VSS leaf | Role | VDM field |
|---|---|---|---|
| `lighting.is_on` | `IsLightOn` (boolean) | command | `AmbientLight.isLightOn` |
| `lighting.intensity` | `Intensity` (uint8, percent, 1–100) | state | `AmbientLight.intensity` |
| `lighting.color` | `Color` (string, `#RRGGBB`) | state | `AmbientLight.color` |

**Why the API intensity is split.** VSS `Intensity` has range 1–100 and no "off"
value. The API uses one `intensity_pct` where 0 means off. The projector
(`capabilities/lighting/vss.py`) publishes 0 % as `IsLightOn = false` and leaves
`Intensity` at its last value. A positive intensity below 1 % is clamped to the
VSS minimum of 1. `ALL` fans out to all four zones. Its color is published only
when it was commanded, because the zones may hold different colors.

---

## 4. Requirements and verification links

| Requirement ID | Statement | Governed element | Verification case |
|---|---|---|---|
| `REQ-LIT-001` | The light shall be set to the commanded intensity (0–100%) and color; 0% shall switch it off. | `setInteriorLight` operation | `test_set_interior_light_via_northbound_api`, `test_zero_intensity_switches_the_light_off` |
| `REQ-LIT-002` | Commands shall be inhibited if power is OFF, an OTA update is in progress, or voltage < 11.0 V. | Precondition and safety phases | `test_lighting_precondition_inhibits_when_power_off`, `test_lighting_inhibits_on_undervoltage` |
| `REQ-LIT-003` | Intensity outside 0–100% or a color that is not `#RRGGBB` shall be refused without commanding the actuator. | Safety phase | `test_lighting_safety_case_refuses_bad_input` |
| `REQ-LIT-004` | State shall be published in VSS terms, quantized to the pinned datatypes. | VSS projection | `test_lighting_vss_endpoint_reports_the_set_zone` |

`capability-check` verifies that every test named here exists. The tests live in
[`tests/test_lighting_example.py`](../../tests/test_lighting_example.py).

---

## 5. Pipeline phases

For every `setInteriorLight` call:

1. **ARBITRATE**: first-in-wins priority queue. A higher-priority source
   pre-empts immediately.
2. **PRECONDITION**: check vehicle state. Power must not be `OFF` and no OTA update can be in progress.
3. **SAFETY**: validate supply voltage, the intensity range, and the color format.
4. **ACTUATOR**: delegate to the lighting actuator port, bounded by `timeout_s`.
   On a timeout or release the light holds its current output.
5. **PUBLISH**: emit `LightingState` on the event bus.

## See also

- [`../windows/move-window.md`](../windows/move-window.md): the window capability this one mirrors.
- [`../../contracts/lighting-api.yaml`](../../contracts/lighting-api.yaml): the
  northbound contract.
