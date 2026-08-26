# Experiment lifecycle

Status: Foundation procedure
Last reviewed: 2026-08-26

## 1. Authorize

Before paid execution, record the run owner, purpose, Git revision, intended data, expected duration, spending ceiling, review time, and teardown authority. Confirm that the artifact restore gate has passed.

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
- Complete and validate the run manifest.

## 6. Export and verify

- Copy retained artifacts to the approved vault.
- Verify the destination checksums against the worker manifest.
- Create the independent backup for critical/release artifacts.
- Verify that copy independently.
- Restore at least the selected checkpoint/report bundle according to policy.
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
