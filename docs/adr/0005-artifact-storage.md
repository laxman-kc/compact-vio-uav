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
- Phase-scoped capacity and cost envelope, including its validity period and
  re-estimation triggers.
- Retention duration by artifact class.
- Transfer tool and resumability.
- Restore-test frequency.
- Worker spending ceiling, review time, and teardown authority.

## Evidence required before acceptance

- A non-template storage-plan record conforming to the
  [artifact-storage plan schema](../../governance/schemas/artifact-storage-plan.schema.json),
  scoped only to the work authorized for the declared phase.
- Owner-approved retained-byte estimate, explicit reserve, retention rules,
  recovery-point objective, spend ceiling, review time, and re-estimation
  triggers. It is not a prediction of unselected future models or datasets.
- Representative export/delete-of-disposable-test-copy/restore evidence with
  SHA-256 and load/open verification in the artifact-storage evidence sidecar.
- If that deletion occurs under paid-worker authorization, the record must pin
  the exact purpose-created `disposable` source location and artifact-manifest
  SHA-256. Worker lifecycle changes and deletion of primary, backup, or other
  retained copies remain outside that authority.
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
- For each paid-worker action, create a separate durable `owner_approved` record
  with fixed typed actions, spending ceiling, and review time, and validate that
  it is active with enough remaining duration when the action begins. Preserve
  it afterward as historical authority; later review or expiry does not erase a
  correctly covered action and cannot authorize new work.
- When paid-worker execution contributed to the M2 drill, link and hash its
  covering historical authorization from the verified sidecar. For a drill in
  a `non_paid_environment`, record that execution context and no worker
  authorization.
- Reopen or supersede this ADR when evidence falls outside the accepted phase
  envelope or invalidates durability, recovery, independence, or cost controls.

## Blocking condition

Important GPU experiments remain blocked until two verified copies of a representative critical bundle exist outside the worker and one has been restored successfully.
