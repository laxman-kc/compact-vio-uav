# ADR-0002: Estimator scope and state contract

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

“VIO” does not uniquely specify local odometry versus mapping/relocalization, loop closure, estimated state, initialization, or output semantics. These choices determine labels, baselines, metrics, and integration interfaces.

## Decision required

Choose and document:

- Local causal VIO or VI-SLAM/mapping.
- Loop-closure policy for each comparison table.
- Incremental or absolute output and transform direction.
- World, body/IMU, and camera frame conventions.
- State contents: pose, velocity, biases, gravity, scale, covariance, and health.
- Initialization and reset rules.
- Measurement timestamp, publication timestamp, output rate, and maximum age.
- Missing-image, missing-IMU, discontinuity, and reinitialization behavior.

## Options to evaluate

- Compact classical estimator.
- Physically anchored hybrid estimator with learned component.
- End-to-end learned estimator.

These are experiment families, not a selection. A scientific winner and deployable winner may differ.

## Evidence required

- Mission/use-case requirements.
- Observability and initialization analysis.
- A frame/timestamp interface specification.
- Baseline feasibility and failure analysis.
- Causal replay tests.
