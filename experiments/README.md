# Experiment evidence schemas

`experiments/schemas/` defines the machine-readable envelopes used to retain
run and artifact evidence. These schemas describe structure; they do not make a
model accurate, authorize data access, or approve a scientific claim.

## Schemas

| Schema | Purpose |
|---|---|
| [`run-manifest.schema.json`](schemas/run-manifest.schema.json) | Code, configuration, environment, data, execution, and result identity for a run |
| [`artifact-manifest.schema.json`](schemas/artifact-manifest.schema.json) | Canonical relative path, byte size, and SHA-256 inventory for a bundle |
| [`artifact-storage-evidence.schema.json`](schemas/artifact-storage-evidence.schema.json) | Post-export copy, restore, and storage evidence |
| [`recorder-snapshot-envelope.schema.json`](schemas/recorder-snapshot-envelope.schema.json) | Payload-omitted terminal recorder metadata |

## What belongs here

Add a schema here when it describes retained experiment or artifact evidence
across implementations. Keep domain-specific input schemas with their owners:

- calibration input/review schemas stay under [`configs/schemas/`](../configs/README.md);
- rights, storage-plan, and worker-authority schemas stay under
  [`governance/schemas/`](../governance/README.md);
- measured human-readable outcomes stay under [`reports/`](../reports/README.md).

Generated run bundles and checkpoints belong under ignored output or retained
artifact storage, not in this schema directory.

## Validate the contracts

Install the validation dependency and run the repository harness:

```bash
python -m pip install -e '.[governance]'
python scripts/validate_schemas.py
```

Validate a retained governed bundle:

```bash
compact-vio-validate-governed-bundle /path/to/governed-bundle
```

Create or verify a deterministic artifact inventory:

```bash
compact-vio-artifacts create /path/to/frozen-run-bundle
compact-vio-artifacts verify /path/to/frozen-run-bundle
```

## Interpretation limits

- A valid run manifest is not proof that every referenced external fact is true.
- A matching artifact manifest proves byte identity, not scientific quality.
- A payload-omitted recorder envelope cannot reconstruct or authenticate omitted
  sensor/model payloads.
- Storage evidence must satisfy the separate artifact policy and restore rules.
- Model acceptance still requires the frozen evaluation protocol and reviewed
  result.

See [Repository layout](../docs/repository-layout.md), the
[experiment lifecycle](../docs/protocols/experiment-lifecycle.md), and the
[artifact policy](../governance/artifacts/policy.md).
