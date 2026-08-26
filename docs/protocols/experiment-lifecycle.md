# Experiment lifecycle

Status: Foundation procedure
Last reviewed: 2026-08-26

## 1. Authorize

Before each paid A10 task, record a short bounded run plan containing:

- owner and purpose;
- immutable Git revision and exact configuration/command;
- approved dataset subset, when data is used;
- expected duration, spending limit, and review time;
- output/export destination and artifacts to retain; and
- teardown responsibility.

Obtain explicit project-owner approval for that bounded plan, then preserve the
plan with the run record. A new paid task requires a new plan; previous approval
does not carry forward. The optional worker-authorization schema can support
more structured auditing, but its version 1 live validator is static-only and is
not the execution path for research runs.

Before M2 passes, paid work is limited to short smoke or reproduction checks
whose outputs are disposable and exactly reproducible from the pushed Git
revision. Long training, large sweeps, and work expected to create irreplaceable
retained results require the M2 export-and-restore gate first. The M2
representative restore drill may run in a non-paid environment.

Worker stop, reboot, termination, and deletion of any copy remain separate
actions. Destructive deletion or termination always requires explicit approval
after checking that no unique source or retained result would be lost.

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
