# Project requirements

Status: Draft foundation
Last reviewed: 2026-08-26

`MUST` items below are implementation invariants approved by the project plan. Fields marked `TBD` are unresolved and must not be converted into defaults by an implementation.

## Research integrity

| ID | Requirement | Verification |
|---|---|---|
| R-RI-001 | Every claim-supporting run MUST identify an immutable Git commit, resolved configuration, environment, hardware, data manifests, seeds, outputs, and checksums. | Validate the run manifest and restore its retained bundle. |
| R-RI-002 | Candidate selection MUST use a protocol frozen before final-test evaluation. | Protocol revision predates final-test results. |
| R-RI-003 | Classical, hybrid, and learned candidates MUST receive equivalent permitted sensor inputs, causality, split membership, loop-closure policy, and evaluation. | Cross-candidate manifest audit. |
| R-RI-004 | Failed, partial, reset, and non-initializing runs MUST be reported; metrics MUST NOT cover only surviving prefixes without disclosure. | Coverage/failure fields and output audit. |
| R-RI-005 | The primary contribution MUST be selected before novel-candidate comparison. | Accepted ADR-0004. |

## Data and causality

| ID | Requirement | Verification |
|---|---|---|
| R-DATA-001 | A dataset MUST NOT be used until its source, version, rights, modalities, sensor suite, calibration status, size, checksum, and approved role are recorded. | Dataset registry and acquisition-manifest review. |
| R-DATA-002 | Train, validation, and final-test membership MUST be assigned by source group before windowing, rendering, corruption, or augmentation. | Split leakage audit. |
| R-DATA-003 | Normalization and learned preprocessing statistics MUST be derived from training membership only. | Configuration and fitted-artifact provenance. |
| R-DATA-004 | Evaluation replay MUST NOT expose sensor information newer than the estimator output timestamp. | Causality tests and replay trace. |
| R-DATA-005 | Dataset files MUST NOT be committed to Git unless an explicit rights and repository-size exception is recorded. | Repository scan. |

## Estimator contract

| ID | Requirement | Verification |
|---|---|---|
| R-EST-001 | Inputs and outputs MUST declare frames, transform direction, units, timestamps, validity, and reset semantics. | Accepted ADR-0002/0003 and contract tests. |
| R-EST-002 | A metric-scale claim MUST use a primary evaluation without Sim(3) scale correction. | Evaluation configuration and scale-negative test. |
| R-EST-003 | Algorithmic latency and processing latency MUST be reported separately. | Replay and runtime trace. |
| R-EST-004 | Covariance, if produced, MUST define its state, frame, tangent convention, propagation, and calibration procedure. | Interface specification and calibration report. |
| R-EST-005 | Estimator health MUST cover initialization, staleness, input gaps, resets, and invalid outputs independently of covariance. | Fault-injection tests. |

## Artifacts and infrastructure

| ID | Requirement | Verification |
|---|---|---|
| R-INFRA-001 | A rented worker MUST NOT be the only location holding versioned work or a retained artifact. | Teardown audit. |
| R-INFRA-002 | Reproducibility-critical and release artifacts MUST have a verified primary copy and an independent verified backup outside the worker. | Artifact index and hash verification. |
| R-INFRA-003 | Important GPU work MUST NOT begin until a representative bundle has completed export, deletion, restoration, and checksum validation. | Restore-test report. |
| R-INFRA-004 | Credentials MUST NOT be recorded in source, configuration, manifests, logs, or artifacts. | Secret scan and manifest review. |
| R-INFRA-005 | Worker cost ceiling, review time, and teardown authority MUST be recorded before extended paid work. | Run authorization record. |

## Evaluation and deployment

| ID | Requirement | Verification |
|---|---|---|
| R-EVAL-001 | Results MUST include per-sequence trajectory accuracy, scale behavior, initialization, coverage, failures, and resource measurements appropriate to the execution platform. | Evaluation bundle review. |
| R-EVAL-002 | Training-GPU timing MUST NOT be used as evidence of edge-device latency, power, memory, or thermal suitability. | Claim/evidence audit. |
| R-DEP-001 | Export equivalence MUST cover step outputs, complete trajectories, recurrent/reset state, validity paths, and failures—not only one tensor comparison. | Export parity report. |
| R-DEP-002 | Target-specific engines MUST be built and validated for the exact selected target stack. | Engine provenance record. |
| R-SAFE-001 | Offline evaluation MUST NOT authorize physical flight. | Safety-gate record. |
| R-SAFE-002 | Any vehicle integration MUST preserve independent stabilization, pilot override, failsafe, watchdog, and stale/invalid-odometry rejection. | SITL/HIL and safety review. |

## Unresolved requirements

The following must be decided through ADRs before dependent implementation:

- Project purpose, release lane, and project license: **TBD**.
- Local VIO versus VI-SLAM and loop-closure policy: **TBD**.
- Monocular versus stereo and complete camera/IMU timing/calibration envelope: **TBD**.
- Estimated state, output rate, initialization mode, and latency ceiling: **TBD**.
- Primary research contribution and primary hypothesis: **TBD**.
- Dataset roles and exact source-group splits: **TBD**.
- Numerical accuracy, failure, latency, memory, power, and thermal thresholds: **TBD**.
- Artifact vault, independent backup, retention capacity, and spending ceiling: **TBD**.
- Edge hardware, runtime, precision, ROS 2/PX4, simulator, and physical-flight scope: **TBD**.
