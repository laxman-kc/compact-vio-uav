# ADR-0002: Estimator scope

- Status: Accepted
- Decision owner: Project owner
- Decision date: 2026-08-26

## Context

“VIO” can mean local odometry or a larger mapping/relocalization system. Mixing
those scopes would make baseline comparisons and latency claims unclear.

## Decision

- The primary task is causal, metric-scale local visual-inertial odometry.
- Mapping, relocalization, global optimization, and loop closure are excluded
  from the primary comparison.
- The estimator produces odometry only; it does not command motors or replace
  PX4 stabilization, pilot override, or failsafes.
- The scientific comparison includes straightforward classical references and a
  physically anchored compact hybrid candidate. Direct learned fusion,
  visual-only, and IMU-only implementations are controls where needed.
- Every estimator receives sensor events through the same causal replay boundary
  and is evaluated without Sim(3) scale correction for the primary metric-scale
  result.

The exact state vector, transform direction, frames, initialization, reset,
health, output-rate, and latency interface remain M3 contract work. They are not
needed to implement the modality-neutral event replay primitive, but must be
frozen before a dataset adapter or estimator claims compliance.

## Evidence

- The project feedback consistently identifies local UAV odometry as the first
  deliverable and keeps PX4 responsible for flight control.
- The reviewed research direction recommends a physically anchored hybrid while
  retaining classical comparisons instead of selecting a winner from published
  cross-platform results.

## Rejected alternatives

- VI-SLAM, mapping, and loop closure in the primary comparison are rejected.
- Direct motor control or replacement of PX4 stabilization is rejected.
- A pure end-to-end learned estimator as the only research path is rejected
  because it would remove the physical and classical controls needed to test the
  contribution.

## Consequences

Generic sensor records, causal replay, evaluator geometry, and baseline adapters
may proceed. VI-SLAM results, if explored later, must be reported separately and
cannot be mixed into the local-odometry comparison.

## Follow-up

- Freeze the detailed estimator interface and failure semantics in M3 before
  real-data adapter acceptance or estimator integration.
- Record causal replay results in M7 and baseline feasibility/failure evidence in
  M8. Reopen this ADR only if those results invalidate the local-VIO scope.
