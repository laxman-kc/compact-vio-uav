# ADR-0005: Artifact storage and retention

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

The GPU worker is disposable and the local workstation is not yet approved as the sole artifact store. Critical training evidence requires durable storage and a verified independent copy before the worker can be destroyed.

## Decision required

Choose and document:

- Primary artifact-vault provider and location.
- Independent backup destination and failure-domain separation.
- Encryption and access-control requirements.
- Capacity and cost budget.
- Retention duration by artifact class.
- Transfer tool and resumability.
- Restore-test frequency.
- Worker spending ceiling, review time, and teardown authority.

## Evidence required

- Capacity estimate for expected runs.
- Representative export/delete/restore test with SHA-256 verification.
- Measured transfer throughput and teardown time allowance.
- Credential and access audit.
- Recovery-owner assignment.

## Blocking condition

Important GPU experiments remain blocked until two verified copies of a representative critical bundle exist outside the worker and one has been restored successfully.
