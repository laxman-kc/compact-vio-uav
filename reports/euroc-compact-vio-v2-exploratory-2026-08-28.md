# EuRoC compact VIO v2 exploratory result

Review date: 2026-08-28

## Result identity

- Code revision: `92aa3294002a9da5861961a314fe74e2bb1ada05`
- Experiment: `euroc-compact-vio-v2-stride-augmented`
- Execution mode: full, 30 epochs, deterministic AMP on one NVIDIA A10
- Dataset: EuRoC MAV, DOI `10.3929/ethz-b-000690084`
- Split-manifest SHA-256:
  `96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`
- Test sequence: `V2_03_difficult`, native stride-1 pairs
- Evaluation policy: `se3/raw-no-alignment/exact-sequence-pairs/v1`
- Selected checkpoint SHA-256:
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`
- Artifact-manifest SHA-256:
  `fb0e04398af590e3ca2d708bc7bcae74ed8afc7834a6b9b329677fe869d998c8`
- GitHub Actions for the experiment revision:
  [run 33144134958](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33144134958)

The artifact bundle contains the checkpoint, run summary, training history,
test metrics, and one prediction/reference row for every evaluated pair. The
worker and ignored local copies independently produced the same manifest hash.

## Measured execution

- Training examples: 12,431 causal pairs from frame strides 1 and 2
- Validation examples: 4,185 causal pairs from frame strides 1 and 2
- Test coverage: 1,889 eligible, 1,889 selected, 1,889 produced
- Selected epoch: 28
- Run duration: 422.112 seconds

| Test measure | v1 | v2 | Change, lower is better |
|---|---:|---:|---:|
| Pair translation RMSE | 0.0537358 m | 0.0499361 m | 7.071% lower |
| Pair rotation-vector RMSE | 0.0201182 rad | 0.00516903 rad | 74.307% lower |
| Raw translation ATE RMSE | 6.62533 m | 6.33804 m | 4.336% lower |
| Final translation drift | 6.82426 m | 6.23185 m | 8.681% lower |
| Predicted/reference path ratio | 0.489554 | 0.638679 | closer to 1.0 |

The exact frame-gap diagnostic used the two native approximately 0.05-second
timestamp intervals as one group and the exact 0.10-second interval as the
other. At 0.05 seconds, v2 translation RMSE was 1.442% higher and rotation RMSE
was 45.313% lower. At 0.10 seconds, translation RMSE was 13.517% lower and
rotation RMSE was 80.834% lower. This supports the stated development diagnosis
that v1 lacked long-gap examples; it does not establish an independent
generalization result.

The measured inference scope was
`predict-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
It included no dedicated warm-up and reported 5,482.75 pairs/s, batch-latency
p50/p95 of 8.215/14.078 ms, and CUDA peak allocated/reserved memory of
267,884,544/322,961,408 bytes. This is an A10 worker measurement, not an
embedded-target benchmark.

## Controls and interpretation

For the same 1,889 references, the zero-motion control produced 0.0564645 m
pair translation RMSE, 0.0482672 rad pair rotation RMSE, 2.05572 m raw ATE, and
2.22649 m final drift. V2 therefore improves local pair prediction over zero
motion, but its integrated raw ATE and final drift remain substantially worse.
The v2 predicted path is 54.9196 m versus the 85.9893 m reference path.

This report is exploratory development evidence. The earlier v1 result on
`V2_03_difficult` directly motivated stride augmentation, so v2 is not a fresh
held-out or confirmatory test. It supports no publishable superiority,
deployment, onboard-resource, uncertainty, safety, or flight-readiness claim.
The next technical issue is recurrent translation direction and path-scale
retention, not another post-hoc test-set scale correction.
