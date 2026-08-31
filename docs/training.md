# Training

CompactVIO-UAV retains two model lanes. They share data and evaluation
infrastructure but do not share the same architecture or training command.

## Current RAFT-hybrid candidate

The runnable web and recording workflow uses the model accepted in
[ADR-0007](adr/0007-raft-gyro-hybrid-runtime.md):

- frozen TorchVision RAFT-small optical flow;
- causal gyro-derived rotation and flow derotation;
- fixed residual-flow and IMU features;
- a stateless 123,395-parameter translation MLP.

The repository can load, verify, export, and package this candidate. It does
not currently expose a general, tracked command that regenerates RAFT feature
caches and retrains this translation head from arbitrary raw recordings. The
local package and its training artifacts are Git-ignored, and a fresh clone
does not contain them.

`compact-vio-train` therefore must not be described as the trainer for the
current web-demo model. The hybrid development history and stopped follow-ups
are recorded in the [completion report](../reports/offline-model-completion-sprint-2026-08-30.md).

## Historical learned CNN/GRU lane

`compact-vio-train` trains the original compact image-pair CNN, temporal IMU
encoder, and fusion model described by the superseded
[ADR-0004](adr/0004-primary-research-contribution.md). Its configurations and
results remain useful reproducibility evidence, but its checkpoints are not the
default RAFT-hybrid runtime.

Install the training dependencies:

```bash
python -m pip install -e '.[train]'
```

Acquire only the EuRoC units named by the versioned plan. For example:

```bash
compact-vio-euroc \
  --plan configs/data/euroc_vicon_v1.json \
  --archive vicon_room1 \
  --raw-dir /data/euroc/raw \
  --data-dir /data/euroc/sequences \
  --sequence V1_01_easy \
  --sequence V1_02_medium \
  --sequence V1_03_difficult
```

Run the bounded smoke before a full experiment:

```bash
compact-vio-train \
  --config configs/training/euroc_compact_vio_v1.json \
  --data-root /data/euroc/sequences \
  --output-dir /runs/euroc-compact-vio-v1-smoke \
  --device cuda \
  --smoke
```

Then run the declared configuration into a new or empty output directory:

```bash
compact-vio-train \
  --config configs/training/euroc_compact_vio_v1.json \
  --data-root /data/euroc/sequences \
  --output-dir /runs/euroc-compact-vio-v1 \
  --device cuda
```

Later configurations under [`configs/training/`](../configs/README.md) include
stride, recurrent-state, magnitude-loss, trajectory-loss, and fine-tuning
experiments. Some require an exact `--initial-checkpoint` and matching
`--initial-checkpoint-sha256`; do not substitute an unrelated checkpoint.

## Run artifacts

A training run writes resolved configuration, history, selected checkpoint,
predictions, metrics, and an artifact inventory. The output directory is not a
model release and should stay outside normal Git history.

Before presenting a result:

1. preserve the exact configuration, source revision, environment, data
   identity, and seed;
2. verify the artifact manifest;
3. evaluate the full declared sequence with failures and coverage visible;
4. retain a dated result under [`reports/`](../reports/README.md);
5. keep validation/development results separate from an untouched final test.

The governing rules are the [research protocol](protocols/research-protocol.md)
and [experiment lifecycle](protocols/experiment-lifecycle.md). The
[configuration registry](../configs/README.md) explains which files are
executable inputs rather than observed evidence.
