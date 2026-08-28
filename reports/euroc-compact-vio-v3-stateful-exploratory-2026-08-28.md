# EuRoC compact VIO v3 stateful exploratory result

Review date: 2026-08-28

## Result identity

- Code revision: `336e88c7e80f6841c7d25b7da311172b40f5a3ba`
- Experiment: `euroc-compact-vio-v3-stateful`
- Execution mode: full, 30 epochs, deterministic AMP on one NVIDIA A10
- Training-config SHA-256:
  `5f95e1a6b9e2958d81b15ecd0d063712f1497d63273ac5e22aa59b1a742ea431`
- Dataset: EuRoC MAV, DOI `10.3929/ethz-b-000690084`
- Split-manifest SHA-256:
  `96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`
- Test sequence: `V2_03_difficult`, native stride-1 pairs
- Evaluation policy: `se3/raw-no-alignment/exact-sequence-pairs/v1`
- Training state policy:
  `zero-per-training-chunk-carry-contiguous-evaluation-chain/v1`
- Selected checkpoint SHA-256:
  `40d18a9a3a04131d04e06a4ab313279613d1dc2339d1758f99777ecb70de8c37`
- Artifact-manifest SHA-256:
  `4244c8841eb3498b150628c3c8126efbf6af90d544c85c9e22e9a79f4e15801f`
- GitHub Actions for the experiment revision:
  [run 33146072746](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33146072746)

All 273 tests passed on the A10 with PyTorch installed. The artifact bundle
contains the checkpoint, run summary, training history, test metrics, and one
prediction/reference row for every evaluated pair. The worker bundle at
`/home/ubuntu/compact-vio-runs/euroc-compact-vio-v3-stateful-full-336e88c`
and ignored local bundle at
`outputs/euroc-compact-vio-v3-stateful-full-336e88c` independently produced
the same artifact-manifest hash. The worker remains running.

## Measured execution

- Training examples: 12,431 causal pairs from frame strides 1 and 2
- Validation examples: 4,185 causal pairs from frame strides 1 and 2
- Training unroll: 8 causal pairs, with state zeroed for each training chunk
- Test coverage: 1,889 eligible, 1,889 selected, 1,889 produced
- Test state handling: 128-pair evaluation chunks, state carried only across
  contiguous chunks of the same chain, with one reset for the full sequence
- Selected epoch: 26
- Selected validation translation RMSE: 0.0524893811 m
- Selected validation rotation RMSE: 0.0100984845 rad
- Selected validation total loss: 0.000476185769
- Run duration: 443.291 seconds

| Test measure | v2 | v3 stateful | Change, lower is better |
|---|---:|---:|---:|
| Pair translation RMSE | 0.0499361 m | 0.0490458 m | 1.783% lower |
| Pair rotation-vector RMSE | 0.00516903 rad | 0.00951883 rad | 84.151% higher |
| Raw translation ATE RMSE | 6.33804 m | 5.03625 m | 20.539% lower |
| Final translation drift | 6.23185 m | 5.99849 m | 3.745% lower |
| Predicted/reference path ratio | 0.638679 | 0.553645 | farther from 1.0 |

The exact frame-gap diagnostic retained the same 1,482 approximately
0.05-second pairs and 407 exact 0.10-second pairs as the v2 comparison. At
0.05 seconds, v3 translation RMSE was 3.910307% lower and rotation RMSE was
81.751270% higher. At 0.10 seconds, translation RMSE was 0.220455% higher and
rotation RMSE was 86.573980% higher. Thus the recurrent change did not improve
every local-motion group or output.

The measured inference scope was
`predict-sequence-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
Across 15 batches it reported 1,732.648988 pairs/s, 1.090238 seconds total,
batch-latency p50/p95 of 67.417437/151.718379 ms, and CUDA peak
allocated/reserved memory of 456,700,928/543,162,368 bytes. It included no
dedicated warm-up. This is an A10 worker measurement, not an embedded-target
benchmark, and the v2 and v3 inference paths have different sequence-unroll
workloads.

## Controls and interpretation

For the same 1,889 references, the zero-motion control produced 0.0564645 m
pair translation RMSE, 0.0482672 rad pair rotation RMSE, 2.05572 m raw ATE, and
2.22649 m final drift. V3 therefore beat zero motion on the two local pair
errors, but zero motion remained substantially better on integrated raw ATE and
final drift. The v3 predicted path was 47.6075 m versus the 85.9893 m reference
path.

This is mixed stateful evidence: causal recurrence improved v2's pair
translation RMSE, raw ATE, and final drift, while rotation RMSE and path-length
retention worsened. The earlier v1/v2 results on `V2_03_difficult` motivated
this change, so the sequence is not a fresh held-out or confirmatory test. This
report supports no superiority, generalization, deployment, onboard-resource,
uncertainty, safety, or flight-readiness claim.
