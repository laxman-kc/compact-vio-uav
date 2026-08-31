# Command-line reference

Install an optional dependency group before using commands in that group:

```bash
python -m pip install -e '.[demo,train,onnx,governance]'
```

Use `COMMAND --help` as the exact option reference. This page explains which
command owns each workflow and which model family it operates on.

## Run a recording

| Command | Purpose |
|---|---|
| `compact-vio-demo` | Launch the local Gradio application |
| `compact-vio-run` | Run one recording from scriptable file or directory inputs |

The default public workflow uses `--model-package` with the current RAFT-hybrid
manifest. A fresh clone does not include that Git-ignored package.

```bash
compact-vio-demo \
  --model-package /path/to/model-package/manifest.json \
  --device cuda
```

```bash
compact-vio-run \
  --recording /path/to/timestamped-frames \
  --imu /path/to/imu.csv \
  --calibration /path/to/calibration.json \
  --model-package /path/to/model-package/manifest.json \
  --output outputs/my-recording \
  --device cuda
```

`compact-vio-run --checkpoint` selects the historical learned CNN/GRU lane.
`--state-policy` applies only to that legacy checkpoint path and is ignored by
the stateless RAFT-hybrid package. See [Input formats](input-formats.md) for
recording contracts.

## Data and training

| Command | Purpose |
|---|---|
| `compact-vio-euroc` | Verify and safely extract selected EuRoC archives |
| `compact-vio-train` | Train/evaluate the historical compact CNN/IMU model family |

The repository has no general tracked CLI that retrains the current
RAFT-hybrid translation head from raw recordings. See [Training](training.md)
before interpreting `compact-vio-train` as the current model trainer.

## Evaluation

| Command | Purpose |
|---|---|
| `compact-vio-evaluate-trajectory` | Evaluate one legacy checkpoint on one EuRoC full-pose sequence |
| `compact-vio-evaluate-position` | Execute a frozen position-only checkpoint protocol |

The hybrid package benchmark is retained in its manifest and the dated model
completion report; these legacy evaluators do not accept a hybrid package
manifest. See [Evaluation](evaluation.md).

## Export and packaging

| Command | Purpose |
|---|---|
| `compact-vio-export-inference` | Remove optimizer/training state from a selected legacy checkpoint |
| `compact-vio-export-onnx` | Export a checked stateful ONNX graph for the legacy learned model |
| `compact-vio-export-raft-head-onnx` | Export and parity-check the current 831-feature translation head |
| `compact-vio-package-raft-hybrid` | Bind RAFT weights, head, clamp, ONNX, contracts, and evaluation summary |

The RAFT-head ONNX graph is not a complete camera-and-IMU VIO graph. See
[Export and packaging](export.md) for exact boundaries.

## Artifact and repository checks

| Command | Purpose |
|---|---|
| `compact-vio-artifacts create` | Create a deterministic bundle inventory |
| `compact-vio-artifacts verify` | Verify a bundle against its inventory |
| `compact-vio-validate-governed-bundle` | Validate a governed training bundle and nested trainer output |
| `compact-vio-copy-audit` | Compare two retained bundle copies against one frozen manifest identity |
| `compact-vio-preflight` | Inspect static storage prerequisites without passing the restore gate |
| `compact-vio-repo-check` | Check repository size, file, text, and secret policies |

These commands establish structure or byte identity. They do not approve a
dataset, model claim, deployment, or flight test.

## Specialized dataset-boundary commands

| Command | Purpose |
|---|---|
| `compact-vio-acquire-archive` | Execute a bounded archive acquisition contract |
| `compact-vio-audit-archive-structure` | Inspect archive headers without extraction |
| `compact-vio-extract-regular-slice` | Extract an exact authorized regular-file slice |
| `compact-vio-inspect-tumvi-format` | Run the bounded TUM-VI format inspection |

These are research-evidence tools, not normal demo prerequisites. Their
authority and results live under [Governance](../governance/README.md) and
[Technical reports](../reports/README.md).
