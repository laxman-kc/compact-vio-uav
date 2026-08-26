# ADR-0004: Primary research contribution

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

Compactness, compute gating, physically anchored learned correction, uncertainty calibration, and robustness are distinct research claims requiring different controls. Treating all as co-primary would make the evaluation underpowered and movable.

## Decision required

Select exactly one primary contribution and define a falsifiable hypothesis. Candidate topics are:

- Early visual-compute execution gating.
- Physically anchored learned correction/residual estimation.
- Calibrated estimator uncertainty and health.
- Robustness to declared visual/inertial degradation.
- Model/runtime compression within a fixed target envelope.

All non-selected topics become secondary analysis or future work.

## Evidence required

- Primary comparator and controlled ablations.
- Primary metrics and predeclared acceptance thresholds.
- Target population of sequences/sensors/environments.
- Minimum repeated seeds or trials.
- Failure and negative-control protocol.
- Resource budget if the claim concerns efficiency.
