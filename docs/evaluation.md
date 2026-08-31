# Evaluation

Evaluation answers a different question from inference. A recording run can
prove that files were parsed and a trajectory was produced; accuracy requires a
reference trajectory and a frozen comparison policy.

## Current RAFT-hybrid benchmark

The current package carries its own frozen evaluation summary. The public
[model card](model-card.md) is the canonical readable metric table, and the
[completion report](../reports/offline-model-completion-sprint-2026-08-30.md)
retains the dated evidence.

The candidate passed V1_03 and V2_03 development sequences, then failed the
separate MH_03 held-out sequence on path-length ratio and normalized endpoint
drift. Its quality status is `experimental_rejected` even though coverage was
complete and several errors beat the zero-motion control.

An ordinary uploaded recording has no reference trajectory. The demo therefore
cannot calculate its individual ATE, drift, or true distance. See
[Understanding the output](interpreting-results.md).

## Historical full-pose checkpoint evaluator

`compact-vio-evaluate-trajectory` evaluates one legacy learned checkpoint on
one complete extracted EuRoC full-pose sequence:

```bash
compact-vio-evaluate-trajectory \
  --checkpoint /path/to/checkpoint.pt \
  --checkpoint-sha256 <sha256> \
  --sequence /data/euroc/sequences/MH_03_medium \
  --state-policy independent \
  --device cuda
```

Use `stateful` only when the checkpoint and declared experiment require causal
state carry. `--unroll-pairs` and `--num-workers` are execution controls for
this legacy evaluation path. The command does not accept a RAFT-hybrid package
manifest.

## Frozen position-only evaluator

`compact-vio-evaluate-position` executes a versioned protocol over explicitly
named checkpoints:

```bash
compact-vio-evaluate-position \
  --protocol configs/evaluation/euroc_mh01_frozen_checkpoints_position_v2.json \
  --archive /data/euroc/raw/MH_01_easy.zip \
  --data-root /data/euroc/sequences \
  --checkpoint v2=/path/to/v2-checkpoint.pt \
  --output-dir /runs/mh01-position-evaluation \
  --device cuda
```

Position-only evidence must not be presented as full-pose rotation, ATE,
deployment, or flight evidence. The reviewed historical result is indexed in
[Technical reports](../reports/README.md).

## Current hybrid acceptance gate

Every evaluated sequence must have complete expected-pair coverage. The
candidate must also:

- beat same-sequence zero motion on raw translation ATE;
- beat zero motion on pair translation RMSE;
- beat zero motion on pair rotation RMSE;
- keep predicted/reference path length within `[0.8, 1.2]`;
- keep final translation drift at or below 2% of reference path length.

Metrics are raw and unaligned unless a frozen protocol explicitly says
otherwise. Do not apply post-hoc scale fitting, trajectory alignment, smoothing,
or survivor-only filtering to turn a failed gate into a pass.

## Evidence checklist

Before reporting a result, retain:

1. exact code revision and resolved configuration;
2. checkpoint or package identity and external SHA-256 when required;
3. dataset unit, split role, calibration, and source identity;
4. complete coverage and failure accounting;
5. metric definitions, controls, thresholds, and state policy;
6. output artifacts and their manifest;
7. execution environment and resource context.

The [research protocol](protocols/research-protocol.md) defines claim controls.
The [experiment schemas](../experiments/README.md) define evidence structure;
schema validity alone is not scientific acceptance.
