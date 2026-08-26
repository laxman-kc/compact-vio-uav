# ADR-0001: Project and release scope

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

The repository is public, but public visibility does not decide whether the work is research-only, commercially usable, or intended for redistributed model/runtime releases. No project license has been selected. Dataset and dependency rights differ and may require separate artifact lanes.

## Decision required

Choose and document:

1. Research-only, commercially eligible, or parallel separated lanes.
2. Project source-code license.
3. Whether model weights, calibration, containers, and reports are released.
4. The dependency-license policy, including treatment of reciprocal licenses.
5. Attribution, NOTICE, data-statement, and model-card requirements.

## Evidence required

- Dependency and dataset rights matrix based on authoritative terms.
- Intended users and distribution surfaces.
- Legal review where commercial eligibility is claimed.
- Confirmation that selected assets can be separated by lane.

## Consequences not yet accepted

Until this ADR is accepted, the project must not claim commercial eligibility, publish model weights, or infer reuse permission from the public repository.
