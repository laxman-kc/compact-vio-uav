# Architecture decision records

An ADR is authoritative only when its status is `Accepted`. `Proposed` and `Unresolved` records document a decision that still blocks dependent work. Rejected options remain in the record so later readers can understand the evidence.

## Status values

- `Unresolved`: question is known but options/evidence are incomplete.
- `Proposed`: a decision is ready for explicit review but is not approved.
- `Accepted`: approved decision with date and consequences.
- `Superseded`: replaced by another ADR.
- `Rejected`: evaluated and deliberately not selected.

## Index

| ADR | Topic | Status | Blocks |
|---|---|---|---|
| [0001](0001-project-and-release-scope.md) | Non-commercial research scope | Accepted | Exact licence still gates external reuse/distribution |
| [0002](0002-estimator-scope.md) | Local-VIO estimator scope | Accepted | Detailed M3 interface still gates estimator compliance |
| [0003](0003-sensor-contract.md) | Camera/IMU configuration and timing envelope | Unresolved | Dataset roles, preprocessing, calibration, target selection |
| [0004](0004-primary-research-contribution.md) | Training-first compact learned VIO development slice | Superseded | Preserved historical learned-model experiment boundary |
| [0005](0005-artifact-storage.md) | Artifact vault, backup, retention, and spend | Unresolved | Important GPU experiments and worker teardown |
| [0006](0006-deployment-scope.md) | PX4 boundary, edge, and flight scope | Unresolved | Export, target runtime, integration and physical testing |
| [0007](0007-raft-gyro-hybrid-runtime.md) | Runnable RAFT + gyro + compact translation-head model | Accepted | Better untouched-sequence distance/drift evidence |

ADR-0004 was accepted from the project owner's explicit 2026-08-28 direction to
execute a real dataset/calibration/model-training workflow, and ADR-0007 now supersedes its model
boundary for the runnable offline candidate. Its earlier
[owner-review decision brief](evidence/0004-decision-brief.md) remains historical
analysis of the superseded reliability-first proposal; it does not report a
training result.

## ADR completion rule

An accepted ADR must name the decision owner, approval date, evidence, selected option, rejected alternatives, consequences, and follow-up verification. Silence, an implementation default, an available dependency, or a value copied from feedback is not a decision.
