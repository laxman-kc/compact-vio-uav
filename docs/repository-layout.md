# Repository layout

CompactVIO-UAV separates runnable code from executable configuration, dated
results, and records that control what those results may claim.

```text
compact-vio-uav/
├── src/compact_vio/    Python package and command implementations
├── tests/              Unit, contract, and repository-policy tests
├── configs/            Versioned inputs consumed by data/training/evaluation code
├── docs/               Active guides, architecture, protocols, and decisions
├── reports/            Dated human-readable experiment results
├── governance/         Rights, policies, authorizations, claims, and receipts
├── experiments/        Run and artifact evidence schemas
├── environments/       Reproducible execution-environment inventories
└── scripts/            Repository validation utilities
```

## Where a change belongs

| Change | Location |
|---|---|
| Runtime, parser, model, evaluator, or command behavior | `src/compact_vio/` |
| Verification of code or repository contracts | `tests/` |
| Input that changes a run | [`configs/`](../configs/README.md) |
| Current user or contributor guidance | `docs/` |
| Architectural decision and its rationale | [`docs/adr/`](adr/README.md) |
| Dated measured result | [`reports/`](../reports/README.md) |
| Dataset rights, artifact policy, or operational authority | [`governance/`](../governance/README.md) |
| Run/bundle evidence structure | [`experiments/`](../experiments/README.md) |
| Runtime package inventory | [`environments/`](../environments/README.md) |

Configuration is not evidence that a run happened. A report is not permission
to access data or spend compute. A governance record is not a model-quality
result. Keeping these roles separate prevents implementation state from being
mistaken for scientific acceptance.

## Runnable model versus historical model

The Python package is organized by responsibility:

| Package | Responsibility |
|---|---|
| `compact_vio.learning` | Current recording runtime plus retained model training/export code |
| `compact_vio.data` | Dataset acquisition, parsing, slicing, and archive boundaries |
| `compact_vio.evaluation` | Trajectory and SE(3) metrics |
| `compact_vio.geometry` | Coordinate and motion primitives |
| `compact_vio.artifacts` | Deterministic artifact inventories |
| `compact_vio.contracts` | Strict project and estimator contracts |
| Package-root audit/replay modules | Historical evidence, replay, and repository checks |

`compact_vio.learning` currently contains both the active RAFT-hybrid runtime and the older learned
training lane. That is a known migration boundary, not evidence that both use the same model.
Moving those modules into new import paths is deliberately deferred until compatibility wrappers
and import tests can preserve every installed command.

The active offline runtime is implemented by these learning modules:

- `demo_bundle.py` and `local_demo.py` provide the one-bundle web workflow;
- `recording_inference.py` owns recording ingestion, trajectory integration,
  and result artifacts;
- `raft_hybrid.py` loads the checked RAFT + gyro + translation-head package;
- `raft_head_onnx.py` exports and verifies the compact translation head.

The tracked `model.py`, `training.py`, checkpoint, dataset, and legacy ONNX
modules preserve the earlier learned CNN/IMU-recurrent experiment lane. That
lane remains reproducible, but it is not the architecture used by the current
web demo. See [ADR-0007](adr/0007-raft-gyro-hybrid-runtime.md) for the boundary
change and [Training](training.md) for the two workflows.

## Current documentation versus history

Active guides live directly under `docs/`. The long
[implementation plan](plan.md), [append-only progress ledger](progress.md), and
[completed model sprint](model-completion-sprint.md) retain their original
paths because tests and evidence links depend on them. They are indexed through
[Historical records](history/README.md), not used as first-run instructions.

## Ignored and generated paths

The following local paths are intentionally outside normal Git history:

- `outputs/` — checkpoints, model packages, predictions, and generated reports;
- `data/` — downloaded or extracted datasets and quarantine areas;
- `.venv/`, `build/`, caches, and `*.egg-info` — local tooling output.

A local `outputs/` directory may contain the experimental RAFT-hybrid package,
but a fresh clone does not. Do not commit model weights, datasets, credentials,
or private recordings to make a local command work.

## Public entry points

- [Project overview](../README.md)
- [Documentation home](README.md)
- [CLI reference](cli-reference.md)
- [Contributing](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)
