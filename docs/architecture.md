# System architecture

Status: Local-VIO research direction fixed; detailed estimator and deployment choices unresolved
Last reviewed: 2026-08-26

## Purpose

The architecture separates durable project state from disposable computation
and the common scientific substrate from estimator-specific implementations.
The main research direction is causal metric-scale local VIO, with classical
references and a physically anchored compact hybrid candidate. Mapping, loop
closure, flight control, and target deployment are outside the current core.

## Planes

### Versioned control plane

GitHub stores source, tests, environment definitions, requirements, ADRs, experiment definitions, dataset/split manifests, artifact indexes, checksums, and small reviewed reports. It is not the normal store for datasets, caches, complete training histories, large checkpoints, or target-specific engine files.

### Development and staging plane

The local workstation holds the development checkout and supports planning,
implementation, lightweight validation, and temporary transfer staging. It is
not assumed to have enough capacity or a configured backup for large retained
artifacts; that check is required before important paid GPU runs, not before
ordinary source development or synthetic tests.

### Disposable execution plane

GPU workers receive an immutable Git revision and approved data subsets, then perform preprocessing, baseline execution, training, evaluation, and profiling. Worker-local datasets, caches, tracking databases, checkpoints, and logs are disposable until exported and verified.

The [2026-08-26 Brev observation](../environments/a10/inventory-2026-08-26.md)
identified the A10 type as non-stoppable. That volatile capability must be
rechecked before action. Disconnecting or ending a shell session is not cost
control; destructive termination requires the applicable preservation checklist
and explicit approval, but may be authorized between runs rather than deferred
until final release.

### Durable artifact plane

The artifact vault holds retained binary outputs. Reproducibility-critical or release artifacts require a second independently verified copy outside the worker. The vault provider and backup destination remain unresolved in [ADR-0005](adr/0005-artifact-storage.md).

## Research data flow

```text
governed dataset sources
          |
          v
canonical timestamps, frames, calibration and validity contract
          |
          v
causal streaming replay + frozen evaluator
          |
          +--------------------+-----------------------+
          |                    |                       |
          v                    v                       v
   classical VIO       compact hybrid VIO       learned diagnostics
          |                    |                       |
          +--------------------+-----------------------+
                               |
                               v
       frozen accuracy / reliability / uncertainty / resource scorecard
                               |
                               v
            scientific selection and deployment selection
                               |
                               v
             conditional export and target-device validation
                               |
                               v
          conditional ROS/PX4 integration and staged safety gates
```

Classical systems do not pass through a neural training/export pipeline. If a hybrid candidate wins, only its neural component may require model export. If a classical system wins, deployment uses its native build and packaging path.

## Shared contracts

All candidates must share:

- A canonical sensor record with image exposure time, individual IMU timestamps, calibration, frames, units, validity, reset markers, provenance, and optional ground truth.
- A replay contract that exposes no future samples and reproduces streaming state, warm-up, reset, dropout, and stale-data behavior.
- A frozen evaluator that reports trajectory error, metric scale, initialization, coverage, failures, and end-to-end timing.
- An experiment manifest conforming to `experiments/schemas/run-manifest.schema.json`.
- Dataset and artifact governance independent of the chosen estimator.

The first implemented replay primitive distinguishes
`measurement_time_ns`—when a measurement applies—from
`available_time_ns`—when an online estimator may observe it. All events use one
declared clock per replay; same-time ordering is explicit; and reset or invalid
events are delivered rather than filtered. Dataset adapters will later map
source timestamps and payloads into this contract.

## Deployment boundary

Training-platform throughput does not establish onboard fitness. Target-device selection requires a declared power, mass, thermal, memory, sensor-interface, and latency envelope. ONNX/TensorRT, Jetson, ROS 2, PX4, and physical sensor integration remain conditional decisions; no target-specific interface is part of the foundation.

If vehicle integration is later approved, PX4 retains stabilization, pilot
override, failsafes, and motor control. VIO begins only as an externally
health-gated odometry measurement source. Physical tests cannot begin directly
from an offline benchmark result.

## Failure containment

- Missing or stale sensor input produces an explicit health state, never a silently reused pose.
- Frame, unit, timestamp, and scale errors must be detected by negative-control tests.
- Failed and partial trajectories remain visible in evaluation; surviving prefixes cannot be reported as complete runs.
- A learned confidence score is not treated as estimator covariance without a defined state, frame, propagation rule, and calibration evidence.
- Destruction of a worker must not destroy versioned state or retained evidence.
