# Artifact governance policy

Status: Foundation policy; storage destinations unresolved
Last reviewed: 2026-08-26

## Storage invariant

A GPU worker is disposable scratch. An artifact is not retained merely because it exists on the worker or appears in a tracking UI.

Reproducibility-critical and release artifacts require:

1. A checksum-verified copy in the approved artifact vault.
2. A checksum-verified independent backup outside the worker.
3. A versioned artifact record containing locations, byte counts, hashes, provenance, rights lane, and verification times.

The vault provider, backup provider, capacity, cost, encryption, and retention durations remain unresolved in ADR-0005.

## Retention classes

| Class | Examples | Minimum treatment |
|---|---|---|
| `reproducibility_critical` | Selected checkpoint, resolved config, metrics, trajectories, environment record | Vault + independent verified backup; restore test |
| `resume_only` | Optimizer/scheduler/RNG state for an authorized continuation | Retain only until continuation or expiry |
| `diagnostic` | Detailed logs, intermediate plots, profiler traces | Retain when needed to explain a result; otherwise expire |
| `disposable` | Caches, downloads, temporary checkpoints | Recreate from manifests; no backup requirement |
| `release` | Approved model/report/calibration/release package | Vault + independent backup + rights/security/release review |

A final model may require both an inference checkpoint and a resume-capable checkpoint; neither should be assumed until the training/release protocol justifies it.

## Required artifact metadata

- Artifact ID, run ID, kind, retention class, rights lane, and status.
- Relative name or approved URI without embedded credentials.
- Byte size and SHA-256.
- Producing Git SHA, resolved configuration, environment, data/split manifests, and seed.
- Primary and backup storage locations.
- Copy-verification timestamps and method.
- Restore/load verification status.
- Expiry or review date when applicable.

The run-manifest schema defines the machine-readable minimum.

## Two complementary manifests

The project uses two records with different responsibilities:

- `run-manifest.json` conforms to
  `experiments/schemas/run-manifest.schema.json` and records scientific intent,
  provenance, data/split references, evaluation settings, outcome, retention,
  rights, and storage verification.
- `artifact-manifest.json` conforms to
  `experiments/schemas/artifact-manifest.schema.json` and is the final portable
  inventory of regular files in the frozen bundle.

The bundle inventory includes `run-manifest.json` and all retained bundle files,
but excludes itself to avoid a circular hash. On restoration, verify the bundle
inventory first, then validate the run manifest and confirm that duplicated byte
counts and hashes agree. Neither record substitutes for the other.

## Run freeze and export

1. Stop mutation of selected files.
2. Mark run outcome, including failure or abortion.
3. Classify artifacts.
4. Compute byte counts and hashes on the worker.
5. Transfer with a resumable, authenticated mechanism.
6. Verify hashes at the vault.
7. Copy critical/release artifacts to the independent backup.
8. Verify that copy separately.
9. Restore/load representative retained outputs.
10. Mark worker copies disposable only after verification.

## Tracking systems

MLflow or another tracker may be used as a disposable local convenience. Its database, UI, or directory layout is not the portable source of truth. A tracker-independent run bundle and manifest must remain understandable without the service.

## Security and rights

- Do not place secrets in artifact URIs, logs, configurations, checkpoints, or manifests.
- Treat checkpoints and serialized runtime files as untrusted inputs when loading.
- Scan release bundles for credentials, private paths, restricted data, and license obligations.
- Separate research-only and commercially eligible artifacts.
- A dataset license does not automatically answer the rights status of derived model weights; review before release.

## Deletion

Deletion from the worker may occur after required export verification. Deleting a vault or backup copy requires the applicable retention decision and a record of what was removed. Destructive worker termination requires explicit approval and the lifecycle checklist.
