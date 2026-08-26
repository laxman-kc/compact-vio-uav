# ADR-0006: Deployment and integration scope

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

Training-platform success does not choose an edge device or prove flight suitability. Jetson/other hardware, export runtime, ROS 2, PX4, simulation, HIL, and physical flight create separate compatibility and safety obligations.

## Retained safety boundary

- PX4 retains stabilization, pilot override, failsafes, and motor authority.
- VIO may later provide only a health-gated external odometry measurement.
- Offline replay or A10 performance never authorizes vehicle integration or
  physical flight.
- These boundaries follow the normative safety requirements. This unresolved ADR
  blocks deployment and integration choices only; it does not block offline VIO
  implementation, replay, evaluation, or baseline research.

## Decision required

Choose and document:

- Whether edge export is in the current project phase.
- Target envelope: power, mass, volume, cooling, memory, interfaces, latency, rate, temperature, and budget.
- Exact target only after representative measurement.
- Native, ONNX, TensorRT, or another runtime path appropriate to the selected estimator.
- Whether ROS 2/PX4 integration, SITL, HIL, and physical testing are in scope.
- Required safety authority and test environment.

## Evidence required before acceptance

- Target-device batch-one latency, memory, power, and thermal-soak measurements.
- Framework/export/full-trajectory equivalence results where applicable.
- Pinned OS/runtime/integration compatibility matrix.
- Interface-control and fault-injection test plan when integration is in scope.
- Named safety authority, test environment, and preconditions when physical
  testing is in scope.

## Follow-up evidence

- Frame, timing, covariance, staleness, reset, and fault-injection results from
  M13 when integration is in scope.
- Safety review before any powered physical test; accepting this ADR is not
  physical-test authority.
- Reopen or supersede this ADR if follow-up integration or safety evidence
  invalidates an accepted target, runtime, interface, or scope assumption.
