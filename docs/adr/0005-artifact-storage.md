# ADR-0005: Artifact storage and retention

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

Any future rented GPU worker is disposable; no worker is assumed to exist or
retain project state between tasks. The local workstation is not yet approved
as the sole artifact store. Critical training evidence requires durable storage
and a verified independent copy before the worker can be destroyed.

## Decision required

Choose and document:

- Primary artifact-vault provider and location.
- Independent backup destination and failure-domain separation.
- Encryption and access-control requirements.
- Phase-scoped capacity and cost envelope, including its validity period and
  re-estimation triggers.
- Retention duration by artifact class.
- Transfer tool and resumability.
- Restore-test frequency.
- Worker spending ceiling, review time, and teardown authority.

## Evidence required before acceptance

- A reviewed storage plan scoped only to the authorized phase. The optional
  [artifact-storage plan schema](../../governance/schemas/artifact-storage-plan.schema.json)
  may be used to structure it but is not the only valid representation.
- Owner-approved retained-byte estimate, explicit reserve, retention rules,
  recovery-point objective, spend ceiling, review time, and re-estimation
  triggers. It is not a prediction of unselected future models or datasets.
- Representative export/delete-of-disposable-test-copy/restore evidence with
  SHA-256 and load/open verification in the artifact-storage evidence sidecar.
- If the optional structured authorization is used for that deletion, it must
  pin the exact purpose-created `disposable` source location and
  artifact-manifest SHA-256. Worker lifecycle changes and deletion of primary,
  backup, or other retained copies remain outside that authority.
- Human-reviewed evidence that the primary and backup are outside the worker
  and in independent failure domains. Path names, filesystem identifiers, or a
  successful copy audit alone do not establish independence.
- Measured transfer throughput and teardown time allowance.
- Semantic validation that primary and backup candidate IDs and locations are
  distinct; required bytes equal retained bytes plus reserve; both candidates
  meet that capacity; expected teardown-transfer time is no shorter than the
  throughput-derived minimum and fits before review; and phase validity,
  retention, and cost review times follow preparation.
- Credential and access audit.
- Recovery-owner, teardown-authority, and deletion-authority assignments. A
  named authority is not approval for a destructive action.

## Follow-up evidence

- Repeat restore tests at the accepted cadence and after material backend,
  credential, encryption, access, transfer-tool, or failure-domain changes.
- Re-estimate retained bytes, reserve, cost, and transfer time before a new
  phase or when data, run count, checkpoint, retention, or release scope changes.
- Before provisioning or using a future GPU worker, obtain fresh project-owner
  confirmation for one bounded plan covering purpose, Git revision and command,
  approved data subset when applicable, expected duration/cost, outputs/export,
  review time, and teardown responsibility. Earlier confirmation does not carry
  forward.
- For extended paid work, preserve the owner-confirmed bounded plan with its
  spending ceiling and review time. An optional `owner_approved` structured
  record may support its audit but does not replace the approval or execution
  evidence.
- The lean M2 path runs the drill in a non-paid environment and records that
  execution context in the sidecar. If paid-worker execution is deliberately
  chosen for the drill, the sidecar's structured historical-authorization link
  becomes required for that drill in addition to the bounded plan.
- Reopen or supersede this ADR when evidence falls outside the accepted phase
  envelope or invalidates durability, recovery, independence, or cost controls.

## Blocking condition

Important GPU experiments remain blocked until two verified copies of a representative critical bundle exist outside the worker and one has been restored successfully.
