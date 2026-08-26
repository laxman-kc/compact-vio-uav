# compact-vio-uav

`compact-vio-uav` is being established as a reproducible research project for evaluating compact visual-inertial odometry (VIO) for UAV use. The estimator design, sensor configuration, data splits, deployment hardware, integration scope, and release license are deliberately **not selected yet**. Those choices will be made through recorded decision gates and evidence.

## Current status

This repository currently contains the governance and experiment-contract foundation only. It does not yet contain an implemented estimator, trained model, approved dataset split, deployable runtime, or flight-ready system.

The project follows these invariants:

- Git is the source of truth for versioned code, configuration, decisions, manifests, and small reviewed results.
- Rented GPU machines are disposable execution workers, never the sole copy of important state.
- Critical binary artifacts require verified storage outside the worker and an independent backup.
- All estimator comparisons use one causal data/replay contract and one frozen evaluation protocol.
- Dataset rights, provenance, grouping, and split membership are recorded before use.
- Offline results do not authorize ROS/PX4 integration or physical flight.

## Documentation map

- [Architecture](docs/architecture.md)
- [Project requirements](docs/requirements/project-requirements.md)
- [Architecture decision records](docs/adr/README.md)
- [Research protocol](docs/protocols/research-protocol.md)
- [Experiment lifecycle](docs/protocols/experiment-lifecycle.md)
- [Dataset governance policy](governance/datasets/policy.md)
- [Candidate dataset registry](governance/datasets/registry.yaml)
- [Artifact policy](governance/artifacts/policy.md)
- [Run-manifest JSON Schema](experiments/schemas/run-manifest.schema.json)
- [Bundle-inventory JSON Schema](experiments/schemas/artifact-manifest.schema.json)

## Foundation checks

The current executable component is a standard-library-only bundle inventory.
It records every regular file by canonical relative path, byte size, and SHA-256,
and rejects symbolic links and unsupported filesystem entries.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compact_vio.repository_policy .
PYTHONPATH=src python -m compact_vio.artifacts create /path/to/frozen-run-bundle
PYTHONPATH=src python -m compact_vio.artifacts verify /path/to/restored-run-bundle
```

The repository-policy command checks cached and non-ignored files for oversized
or forbidden artifacts, unsupported file types, invalid governed text, and a
small set of high-confidence secret formats without printing matched values.
`create` writes a new `artifact-manifest.json` inside the bundle and refuses to
replace any existing entry at that path. `verify` exits `0` for an exact match,
`1` for content differences, and `2` for invalid or unsafe input. These checks
establish file identity; they do not by themselves approve the run, its dataset
rights, or its scientific claims.

## State ownership

| State | Authoritative location | Brev/A10 treatment |
|---|---|---|
| Source, configuration, decisions, manifests | GitHub repository | Clean checkout of an immutable revision |
| Raw/processed datasets and caches | Location recorded by dataset manifest | Disposable working copy |
| Critical checkpoints, trajectories, and reports | Artifact vault plus independent verified backup | Temporary until exported and verified |
| Credentials | Approved secret store or local credential mechanism | Never committed; minimum access only |

The artifact-vault provider, backup destination, retention budget, and cost ceiling are unresolved. Important GPU experiments must not begin until the storage restore gate in the [artifact policy](governance/artifacts/policy.md) passes.

## Decision status

No project license has been selected. No permission to reuse or redistribute project content should be inferred until that decision is recorded and a license file is intentionally added.

Open project decisions are listed in the [ADR index](docs/adr/README.md). An ADR marked `Proposed` or `Unresolved` is not an implementation choice.

## Safety boundary

This is research software. It is not flight-certified and must not command motors or authorize free flight. Any later vehicle integration must proceed through interface review, replay, software-in-the-loop, hardware-in-the-loop, bench, and contained-flight gates with independent flight-control and failsafe mechanisms.
