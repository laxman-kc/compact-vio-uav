# Artifact governance policy

Status: Foundation policy; storage destinations unresolved
Last reviewed: 2026-08-26

## Storage invariant

A GPU worker is disposable scratch. An artifact is not retained merely because it exists on the worker or appears in a tracking UI.

Reproducibility-critical and release artifacts require:

1. A checksum-verified copy in the approved artifact vault.
2. A checksum-verified independent backup outside the worker.
3. An immutable frozen bundle containing its run and artifact manifests.
4. A separate, versioned post-export storage-evidence sidecar containing
   locations, copy observations, failure-domain review, deletion/restore
   chronology, and verification times.

The vault provider, backup provider, capacity, cost, encryption, and retention durations remain unresolved in ADR-0005.

A review-ready storage plan must also pass semantic validation: primary and
backup candidate IDs and location references differ; total required bytes equal
worst-case retained bytes plus reserve; each destination has that capacity; the
expected teardown-transfer time is at least the total-bytes/throughput lower
bound and fits before cost review; and phase validity and retention/cost review
times follow record preparation. These checks do not prove independence or
durability.

## Retention classes

| Class | Examples | Minimum treatment |
|---|---|---|
| `reproducibility_critical` | Selected checkpoint, resolved config, metrics, trajectories, environment record | Vault + independent verified backup; restore test |
| `resume_only` | Optimizer/scheduler/RNG state for an authorized continuation | Retain only until continuation or expiry |
| `diagnostic` | Detailed logs, intermediate plots, profiler traces | Retain when needed to explain a result; otherwise expire |
| `disposable` | Caches, downloads, temporary checkpoints | Recreate from manifests; no backup requirement |
| `release` | Approved model/report/calibration/release package | Vault + independent backup + rights/security/release review |

A final model may require both an inference checkpoint and a resume-capable checkpoint; neither should be assumed until the training/release protocol justifies it.

## Required bundle metadata

- Artifact ID, run ID, kind, retention class, rights lane, and status.
- Canonical relative bundle path; storage locations are not embedded in the
  frozen bundle manifests.
- Byte size and SHA-256.
- Producing Git SHA, resolved configuration, environment, data/split manifests, and seed.
- Expiry or review date when applicable.

The run-manifest schema defines the immutable scientific/provenance minimum.
The artifact-manifest schema defines the immutable file inventory.

## Two immutable manifests and one evidence sidecar

The project uses three records with different responsibilities:

- `run-manifest.json` conforms to
  `experiments/schemas/run-manifest.schema.json` and records scientific intent,
  provenance, data/split references, evaluation settings, outcome, retention,
  rights, and immutable artifact identities. It does not record mutable
  post-export locations or later verification observations.
- `artifact-manifest.json` conforms to
  `experiments/schemas/artifact-manifest.schema.json` and is the final portable
  inventory of regular files in the frozen bundle.
- The artifact-storage evidence sidecar conforms to
  `experiments/schemas/artifact-storage-evidence.schema.json` and records
  post-export copy locations, checksum observations, human-reviewed
  failure-domain evidence, deletion of the disposable source test copy,
  restoration into a new location, load/open results, and whether execution was
  paid-worker or `non_paid_environment`. Paid-worker evidence links the exact
  historical worker authorization by record ID, path, and SHA-256; non-paid
  execution carries no fabricated worker authorization. The sidecar remains
  outside the frozen bundle so recording later events does not mutate bundle
  identity.

The bundle inventory includes `run-manifest.json` and all retained bundle files,
but excludes itself to avoid a circular hash. On restoration, verify the bundle
inventory first, then validate the run manifest and confirm that duplicated
artifact byte counts and hashes agree. The evidence sidecar must identify the
raw SHA-256 of the exact artifact-manifest bytes it audits. None of the three
records substitutes for another or accepts ADR-0005.

`compact-vio-copy-audit` may read two accessible copies and compare both against
the frozen artifact manifest while pinning that manifest's raw SHA-256. A
successful audit is a supporting checksum fragment only. It cannot prove event
chronology, deletion of the disposable source test copy, restoration into a new
location, representative load/open success, access from a recovery environment,
or independent failure domains, and it always leaves the restore gate false.

## Run freeze and export

1. Stop mutation of selected files.
2. Mark run outcome, including failure or abortion.
3. Classify artifacts and complete `run-manifest.json`.
4. Create `artifact-manifest.json` over the complete bundle, then freeze both
   manifests and all bundle contents.
5. Transfer with a resumable, authenticated mechanism.
6. Verify hashes at the vault against the frozen artifact manifest.
7. Copy critical/release artifacts to the independent backup.
8. Verify that copy separately against the same frozen manifest.
9. Record copy observations in the post-export evidence sidecar.
10. Delete only the declared, purpose-created `disposable` source test copy used
    by the restore drill; this is not worker termination. Under paid-worker
    execution, the active authorization must pin its exact
    `(action_id, location_ref, delete)` scope and artifact-manifest SHA-256 and
    include the typed deletion action.
    Version 1 still blocks execution because its standalone validator permits
    only static checks and cannot resolve storage roles, consume the required
    pre-delete two-copy evidence, or prove single use; add and validate that
    dedicated interface before performing this step.
11. Restore into a new location and verify the manifest, hashes, and
    representative load/open behavior.
12. Complete human failure-domain review and mark worker copies disposable only
    after every applicable verification passes.

## Tracking systems

MLflow or another tracker may be used as a disposable local convenience. Its database, UI, or directory layout is not the portable source of truth. A tracker-independent run bundle and manifest must remain understandable without the service.

## Security and rights

- Do not place secrets in artifact URIs, evidence sidecars, logs,
  configurations, checkpoints, or manifests.
- Treat checkpoints and serialized runtime files as untrusted inputs when loading.
- Scan release bundles for credentials, private paths, restricted data, and license obligations.
- Separate research-only and commercially eligible artifacts.
- A dataset license does not automatically answer the rights status of derived model weights; review before release.

## Deletion

The bounded worker authorization grants no general destructive authority. Its
sole narrowly represented deletion scope is the exact purpose-created
disposable restore-test source copy after the required two-copy verification.
Version 1 can represent that proposed scope but permits no non-static live
action without a reviewed storage-role linkage, dedicated pre-action evidence,
and consumption check. Worker lifecycle changes
and deletion from the primary vault, independent backup, or any other retained
copy are structurally outside that authorization. Deleting a retained copy
requires the applicable retention decision and a record of what was removed;
destructive worker termination requires separate explicit approval and the
lifecycle checklist.
