# COVESA All Member Meeting: Presenter Guide

20 minutes total, including a 3-minute demo. Extended Q&A is additional.
Draft for technical and publication review. Add approved presenter/date in PowerPoint.
No proprietary status, safety certification, or COVESA endorsement is asserted.

## 1. Vehicle Capabilities (00:00-00:45)

Introduce the talk as a reference example and a discussion proposal, not an adopted COVESA standard. We will follow one window command from an application to a simulated motor. The goal is to make interfaces and behavior concrete enough for members to challenge and improve. Add the approved presenter name and meeting date before presenting.

## 2. Applications Need Intent, Not Wiring (00:45-02:00)

A window is deliberately ordinary. An application should not need a bus identifier, supplier pinout, or ECU address to request a position. A transport API alone does not settle ownership, inhibition, completion, or failure semantics. A capability is the place to give that request a domain meaning. This complements signal-level interoperability rather than replacing it.

## 3. A Small, Deliberate Reference Scope (02:00-03:30)

The runnable scope is windows only. Other domains in the architectural picture are context, not released capability implementations. The composition root wires the bus, vehicle-state stub, simulator, manager, and window orchestrator. A power stub is present but the manager does not request power authorization. Do not imply that this example implements the full vehicle architecture.

## 4. Two Boundaries, One Capability (03:30-05:30)

Read the diagram top to bottom. The northbound API accepts semantic commands and returns typed state. The manager owns domain gates and dispatch. The southbound port exposes abstract actuation and position read-back. The simulator is the implemented binding; a hardware binding is a future integration point. Deployment addressing remains below the port. State events provide feedback to callers. These boundaries are architectural contracts, not necessarily process or network boundaries.

## 5. The Northbound Contract (05:30-07:00)

Describe MoveWindowCommand and WindowState. The adapter derives the request source from its configured role and rejects a source field in the payload. That is a demonstration configuration, not a credential verification system. Runtime endpoints are under /vehicle/window. The checked-in OpenAPI paths and response codes currently differ from the adapter and need alignment before consumers generate clients. Avoid presenting that drift as a standardized contract.

## 6. A Request Has Five Phases (07:00-08:30)

The manager executes arbitration, preconditions, safety checks, actuator dispatch, and state publication. Current gates check power OFF, OTA activity, undervoltage, and target range. Timeout and explicit release use cancellation and position read-back support. The term safety checks is not an ISO 26262 safety case or certification claim. Priority logic exists, but the manager holds one lock throughout a move, so immediate priority preemption and independent zone concurrency should not be claimed as proven. The explorer's phase replay is an explanatory animation, not live execution tracing.

## 7. The Southbound Contract (08:30-10:00)

The WindowActuatorPort is an abstract interface. The simulator maps API percentages to model millimeters and reports the resulting position. A deployment profile describes electrical, travel, load, and geometry quantities without hardware addresses. A real binding would implement transport and feedback. The simulator runs physics synchronously inside its async method, so it is not evidence of interruptible hardware timing. No real ECU integration is demonstrated here.

## 8. An Executable Plant Model (10:00-11:30)

Explain the four-stage bond-graph representation: electrical drive and motor, rotary-to-linear actuation, linkage, and window load. The model can generate a trajectory, compute KPIs, and respond to an imposed obstruction in model-level tests. Model position is the opposite of API openness: 0 mm is open and 300 mm is closed for the default model. Parameters and outputs are illustrative simulation data, not measured supplier specifications or vehicle validation evidence. No production anti-pinch timing guarantee is established.

## 9. Capabilities Complement VSS (11:30-13:00)

VSS supplies a shared signal vocabulary. The example attaches VSS paths to capability metadata and relevant operations, while defining command and result semantics separately. This is VSS-referenced metadata, not a demonstrated VSS server integration or a conformance certification. Agreeing units, ranges, and direction conventions is essential; review the exact mapping against the chosen VSS release. The catalog can help discover interfaces and model parameters without embedding transport addresses.

## 10. Demo: Follow One Window Command (13:00-16:00)

0:00-0:30: Open http://127.0.0.1:8770/vehicle/catalog/?cap=window&tab=overview and show the descriptor and ports. 0:30-1:15: Open ?cap=window&tab=boundary, choose a move operation, and step through the explanatory replay. State explicitly that replay is not live instrumentation. 1:15-2:00: Open ?main_tab=explorer, choose DRIVER_FRONT and 75%, execute, then show the response and event log. The configured adapter role controls source; do not rely on a selector to switch identity. 2:00-3:00: Open /vehicle/api-explorer/ and show the physics playground trajectory and KPIs. Explain that playground simulation is a separate model run, not motor telemetry. If the demo is unavailable, use the deck's architecture and pipeline diagrams and the following HTTP fallback: POST /vehicle/window/move with {"zone":"DRIVER_FRONT","target_pct":75}; GET /vehicle/window/state?zone=DRIVER_FRONT. Rehearse on the actual machine first. Start using python -m capability_framework.app --no-browser.

## 11. What The Example Demonstrates (16:00-17:30)

The repository has tests for target movement, model KPIs, obstruction detection, power-off inhibition, HTTP operations, catalog rendering, diagrams, and playground simulation. These establish behavior within a reference example, not production readiness. Do not cite a test count without running the checked-out revision. The window orchestrator issues manager commands sequentially even for its SYNC convenience mode. The runtime returns MOVING after its simulated call completes; completion and status semantics remain a collaboration question. Calibration profile types exist, but automatic outcome reporting is not wired in the current main revision.

## 12. Candidate Topics For Collaboration (17:30-18:30)

Present these as candidate topics for member discussion. No adopted standard or workgroup commitment is implied. Which elements should be portable across deployments? How should asynchronous completion and state observation work? What must a binding guarantee on cancellation? What verification examples should accompany a contract? Keep transport choices and hardware topology as extension concerns unless members identify a compelling interoperability need.

## 13. From Reference To Shared Artifact (18:30-19:30)

Propose a practical sequence. First align the OpenAPI paths, statuses, and schemas with runtime behavior. Then exercise arbitration, interruptibility, cancellation, fault reporting, and model limits. Validate a second binding before claiming hardware portability. Publication requires the owner's review of code and parameter provenance, copyright permissions, and licensing. The repository LICENSE is currently a placeholder while package metadata declares Apache-2.0; this must be reconciled. A keyword scan cannot establish absence of proprietary information. The deck avoids employee names, internal repositories, and internal rule identifiers, but remains subject to release review.

## 14. Which Boundary Should We Agree First? (19:30-20:00)

Close with the central invitation: use this small runnable example to decide which boundary semantics deserve shared agreement. Ask members to nominate one missing guarantee, one binding scenario, or one verification case. The planned talk is 20 minutes including the demo; any extended questions need additional agenda time. Do not announce a public repository link until publication is approved.
