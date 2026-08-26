# ADR-0006: Deployment and integration scope

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

Training-platform success does not choose an edge device or prove flight suitability. Jetson/other hardware, export runtime, ROS 2, PX4, simulation, HIL, and physical flight create separate compatibility and safety obligations.

## Decision required

Choose and document:

- Whether edge export is in the current project phase.
- Target envelope: power, mass, volume, cooling, memory, interfaces, latency, rate, temperature, and budget.
- Exact target only after representative measurement.
- Native, ONNX, TensorRT, or another runtime path appropriate to the selected estimator.
- Whether ROS 2/PX4 integration, SITL, HIL, and physical testing are in scope.
- Required safety authority and test environment.

## Evidence required

- Target-device batch-one latency, memory, power, and thermal-soak measurements.
- Framework/export/full-trajectory equivalence results where applicable.
- Pinned OS/runtime/integration compatibility matrix.
- Frame, timing, covariance, staleness, reset, and fault-injection evidence.
- Safety review before any powered physical test.
