# EuRoC compact VIO v4 translation-state exploratory result

Review date: 2026-08-28

## Result identity

- Code revision: `94d834a82bddb2e6185fb70ec289fd45017c325c`
- Experiment: `euroc-compact-vio-v4-translation-state`
- Execution mode: full, 30 epochs, deterministic AMP on one NVIDIA A10
- Training-config SHA-256:
  `ca8d95e9502383897e78b81274dc375b219a7b29cad0e42c71ac8c5bdc0ce85a`
- Dataset: EuRoC MAV, DOI `10.3929/ethz-b-000690084`
- Split-manifest SHA-256:
  `96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`
- Test sequence: `V2_03_difficult`, native stride-1 pairs
- Evaluation policy: `se3/raw-no-alignment/exact-sequence-pairs/v1`
- Training state policy:
  `zero-per-training-chunk-carry-contiguous-evaluation-chain/v1`
- Rotation state source:
  `current-pair-zero-initialized-fusion-state/v1`
- Selected checkpoint SHA-256:
  `e775adb16aa4f9522aa577a32704a54db5c82c53685b0e97fb8d149402bf159d`
- Artifact-manifest SHA-256:
  `d28aca790a5c70b6e2763583f9098427e09c967a0774dd49fe07bbca4858489f`
- GitHub Actions for the experiment revision:
  [run 33147863994](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33147863994)

All 282 tests passed on the A10 with PyTorch installed. The artifact bundle
contains the checkpoint, run summary, training history, test metrics, and one
prediction/reference row for every evaluated pair. The worker bundle at
`/home/ubuntu/compact-vio-runs/euroc-compact-vio-v4-translation-state-full-94d834a`
and ignored local bundle at
`outputs/euroc-compact-vio-v4-translation-state-full-94d834a` independently
produced the same artifact-manifest hash. The worker remains running.

## Controlled change

V4 retained v3's dataset and split, parameter shapes, optimizer, seed, loss,
frame strides, eight-pair training unroll, evaluation state-carry policy, and
30-epoch schedule. Translation continued to use the carried recurrent fusion
state. Rotation instead used a fusion state computed from the current pair
with zero initial state. This was one controlled routing change; it added no
model parameters.

Before inspecting v4's result, replacement required all three gates: lower
pair translation RMSE and lower raw ATE than v3, plus pair rotation RMSE no
worse than v2. The result passed the translation and ATE gates but failed the
rotation gate, so v4 was rejected as a replacement candidate.

## Measured execution

- Training examples: 12,431 causal pairs from frame strides 1 and 2
- Validation examples: 4,185 causal pairs from frame strides 1 and 2
- Training unroll: 8 causal pairs, with state zeroed for each training chunk
- Test coverage: 1,889 eligible, 1,889 selected, 1,889 produced
- Test state handling: 128-pair evaluation chunks, state carried only across
  contiguous chunks of the same chain, with one reset for the full sequence
- Selected epoch: 30
- Selected validation translation RMSE: 0.0517684224 m
- Selected validation rotation RMSE: 0.00731593395 rad
- Selected validation total loss: 0.000455582084
- Run duration: 489.976980 seconds

| Test measure | v3 stateful | v4 translation-state | Change, lower is better |
|---|---:|---:|---:|
| Pair translation RMSE | 0.0490458 m | 0.0475086 m | 3.134% lower |
| Pair rotation-vector RMSE | 0.00951883 rad | 0.00604096 rad | 36.537% lower |
| Raw translation ATE RMSE | 5.03625 m | 4.00862 m | 20.405% lower |
| Final translation drift | 5.99849 m | 4.49908 m | 24.996% lower |
| Predicted/reference path ratio | 0.553645 | 0.510652 | farther from 1.0 |

The exact frame-gap diagnostic retained 1,482 approximately 0.05-second pairs
and 407 exact 0.10-second pairs. At 0.05 seconds, v4 translation RMSE was
4.618060% lower and rotation RMSE was 37.118336% lower than v3. At 0.10
seconds, translation RMSE was 1.841451% lower and rotation RMSE was 35.977304%
lower. The improvement therefore appeared in both pair-interval groups, but
does not establish generalization because the same development-test sequence
informed the change.

The measured inference scope was
`predict-sequence-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
Across 15 batches it reported 1,058.729410 pairs/s, 1.784214 seconds total,
batch-latency p50/p95 of 114.579536/200.278403 ms, and CUDA peak
allocated/reserved memory of 456,700,928/543,162,368 bytes. It included no
dedicated warm-up. This is an A10 worker measurement, not an embedded-target
benchmark.

## Controls and interpretation

V4's pair rotation RMSE of 0.00604096 rad was 16.868309% worse than v2's
0.00516903 rad, which is why the frozen rotation gate failed. Its predicted
path was 43.9107 m versus the 85.9893 m reference path. The same-sequence
zero-motion control produced 0.0564645 m pair translation RMSE, 0.0482672 rad
pair rotation RMSE, 2.05572 m raw ATE, and 2.22649 m final drift. V4 beat zero
motion on local pair errors, but zero motion remained substantially better on
raw ATE and final drift.

This is exploratory development evidence. Earlier results on
`V2_03_difficult` motivated the routing change, so this is not a fresh held-out
or confirmatory result. It supports no superiority, generalization,
deployment, onboard-resource, uncertainty, safety, or flight-readiness claim.

`V2_03_difficult` is closed to further model and hyperparameter selection. A
future quality decision requires a fresh evaluation unit and acceptance rule
declared before reading its predictions.
