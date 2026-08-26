# Experiment lifecycle

Status: Foundation procedure
Last reviewed: 2026-08-26

## 1. Authorize

Before each important or extended paid execution, create a fresh authorization
record with the run owner, purpose, Git revision, intended data, closed action
IDs, expected duration, spending ceiling, review time, and teardown authority.
Confirm that the artifact restore gate has passed.

The only pre-gate paid-worker exception is bounded M2 evidence gathering under
an explicit project-owner authorization. It must name the immutable Git
revision, worker, exact action-to-location-access scopes, fixed time and spending
limits, review time, recovery owner, and teardown authority. It permits only
the typed static-check, purpose-created source, primary-copy, independent-copy,
content-audit, disposable-source deletion, representative-restore, and
load/open actions needed to evaluate M2. It permits no dataset download,
training, or important experiment. A
`worker-authorization.template.json` file or a record marked
`record_status: draft` or `record_status: ready_for_owner_review` is a request,
not authorization. A durable record marked `record_status: owner_approved`
with `authorizes_work: true` and named approval evidence is required but not
sufficient: authenticate the approver, prove the record is unused, reserve its
single consumption entry, and satisfy applicable pre-action evidence first.
Semantic validation must establish
`prepared_at <= approved_at < review_at <= expires_at`; the duration must fit
before review both when approved and at use time. Active use also requires the
current time to be at or after approval and before review, and the worker, Git
revision, one action, and that action's complete typed location-access set to
match exactly. The set distinguishes read, write, and delete access so a restore
source cannot be confused with its destination. Schema validity alone is not an
active-use check.

The schema fixes `general_destructive_action_authorized: false`. Its sole
narrowly represented deletion scope is `disposable_source_copy_delete` for the exact copy named,
pinned by artifact-manifest SHA-256, purpose-created for this restore test, and
classified `disposable`. The record must also include separate typed scopes for
the preceding two copy writes and content audit plus the subsequent restore and
load/open checks. Worker stop/reboot/termination and deletion of a primary,
backup, or any other
retained copy are hard false and require separate authority outside this record.
An informal chat acknowledgement is not a durable authorization record.

Version 1 live validation permits only `static_checks`. It cannot resolve an
exact reviewed storage plan to bind primary, backup, restore-source, and
restore-destination roles, consume the required pre-action evidence, or reserve
the append-only authorization-consumption entry. Records can express proposed
non-static scopes for owner review and validate historical sidecar linkage, but
no non-static paid M2 action—including the disposable-copy deletion—may be
executed through the version 1 gate. The restore drill and M2 remain blocked
until that dedicated interface is implemented.

After an authorized action, preserve the record as historical evidence. Passing
its review or expiry time does not invalidate the completed M2 drill, but the
record cannot authorize another action. Every later paid action requires a
fresh, single-execution record plus an append-only consumption entry; the
stateless validator cannot prove non-reuse or cumulative spend. Version 1 does
not authorize `post_m2_paid_work`; an acceptance-aware contract must first link
the exact accepted M2/ADR-0005 evidence and intended data. A drill performed entirely in a
`non_paid_environment` records that execution context and does not invent a
worker authorization.

## 2. Prepare locally

- Work from versioned configuration and manifests.
- Validate the run manifest against the repository schema.
- Ensure no secret is embedded in source, configuration, URI, command, or environment capture.
- Push the exact clean Git revision before a claim-supporting remote run.

## 3. Materialize the worker

- Retrieve the immutable revision.
- Instantiate the pinned execution environment.
- Record OS, architecture, hardware, driver, runtime, dependency, and container fingerprints.
- Download only approved dataset subsets and validate them against acquisition manifests.
- Run data, geometry, causality, evaluator, and small GPU smoke checks.

## 4. Execute and observe

- Assign a unique run ID.
- Preserve the resolved configuration and seed before execution.
- Capture metrics, failures, resource use, and protocol deviations.
- Keep temporary tracking services private and disposable.
- Do not make worker-local dashboards or databases the authoritative record.

## 5. Freeze the run

- Stop mutation of selected outputs.
- Write the outcome, including failed/aborted status and exit information.
- Classify artifacts by retention class.
- Produce byte counts and SHA-256 values.
- Complete and validate `run-manifest.json`, then create
  `artifact-manifest.json` over the complete frozen bundle. These two manifests
  remain inside the bundle and are immutable after export begins.

## 6. Export and verify

- Copy retained artifacts to the approved vault.
- Verify the destination checksums against the immutable artifact manifest.
- Create the independent backup for critical/release artifacts.
- Verify that copy independently.
- Restore at least the selected checkpoint/report bundle according to policy.
- Record later locations, copy observations, deletion of the disposable source
  test copy, restoration, and load/open results in the post-export
  artifact-storage evidence sidecar. Do not rewrite either bundle manifest.
- For paid-worker execution, link and hash the historical authorization in the
  sidecar and verify that its active window and typed action scope covered the
  recorded drill events. Delete only the exact purpose-created source copy it
  names; never infer permission to change worker lifecycle or delete retained
  copies.
- A successful `compact-vio-copy-audit` is supporting checksum evidence only;
  it does not prove chronology, deletion, restoration, loadability, storage
  independence, or completion of the restore gate.
- Commit only manifests and approved small results; do not commit large artifacts or restricted data.

## 7. Review

- Confirm data/split and protocol revisions.
- Check coverage, failures, negative controls, and per-sequence results.
- Separate confirmatory from exploratory conclusions.
- Record deviations and decide retain/repeat/reject.

## 8. Teardown

Before destructive worker termination:

1. Check for uncommitted source or configuration changes.
2. Confirm required Git commits are reachable from the approved remote.
3. Confirm primary and backup artifact copies and their hashes.
4. Restore/load the selected retained artifact.
5. Record which worker-local data will be destroyed.
6. Obtain explicit destructive-action approval.
7. Terminate the worker using its actual lifecycle mechanism.
8. Confirm billing/runtime state no longer shows it as active.

For a non-stoppable Brev instance, shell disconnect and reboot do not satisfy teardown. Do not issue a destructive termination merely because a run has ended.
