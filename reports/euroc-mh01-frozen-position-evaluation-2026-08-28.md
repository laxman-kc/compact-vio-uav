# EuRoC MH_01 frozen position-only evaluation

Review date: 2026-08-28

## Outcome

The frozen position-only rule selected **v2** from v2, v3, and v4 on
`MH_01_easy`. All three candidates produced all 3,681 native sensor pairs and
scored every one of the 2,926 reference-eligible pairs. All beat the zero-motion
pair-displacement RMSE of `0.02649378180034436` m; v2 had the lowest eligible
value, `0.017339865612729627` m, so the no-tie-break rule selected v2.

This is a narrow position-displacement endpoint decision. It is not a full-pose
or rotation evaluation, ATE, an estimator-wide superiority result, deployment
approval, or publication-grade confirmation.

## Evidence identity

- Evaluation revision:
  `deea10f767dd207c181d09521d47667cc15c8d6d`
- Evaluation ID: `euroc-mh01-frozen-checkpoints-position-v1`
- Result schema version: `1.0.0`
- Frozen protocol:
  `configs/evaluation/euroc_mh01_frozen_checkpoints_position_v1.json`
- Frozen-protocol SHA-256:
  `2610644fdcffaf2d44f327f3135de3795cfcaa91f7d9a8491d850035a7073425`
- Result-summary SHA-256:
  `65d37221572c458ca86281ef01c3ae41345fb35b66c99ef632ddfe0f894de5b4`
- Artifact-manifest SHA-256:
  `184d9427ebec373edb4da222bba5ea382146369a61b471b92b30b0e328ce8e76`
- GitHub Actions:
  [run 33152517547](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33152517547)
- A10 test gate: all 329 tests passed, including the dependency-gated PyTorch
  end-to-end evaluation smoke
- Execution: NVIDIA A10, CUDA, PyTorch `2.7.0`
- Started: `2026-08-28T07:45:34.870708Z`
- Completed: `2026-08-28T07:47:00.566678Z`
- Evaluation duration: `85.6959709560033` seconds
- A10 artifact path:
  `/home/ubuntu/compact-vio-runs/euroc-mh01-frozen-position-deea10f`
- Ignored local copy: `outputs/euroc-mh01-frozen-position-deea10f`

The deterministic artifact manifest inventories all seven result files. It
verified successfully and had the same raw SHA-256 at the A10 and local paths.
That content match does not by itself establish an independent recovery copy or
satisfy the restore gate.

## Exact execution command

The worker checkout was clean at the evaluation revision, the output directory
did not exist, and `compact_vio.__file__` resolved below the checked-out `src`
tree before this command ran:

```bash
cd /home/ubuntu/compact-vio-uav
PYTHONPATH=/home/ubuntu/compact-vio-uav/src python3 -m compact_vio.learning.position_evaluate_cli \
  --protocol configs/evaluation/euroc_mh01_frozen_checkpoints_position_v1.json \
  --archive /home/ubuntu/datasets/euroc-machine-hall/downloads/machine_hall.zip \
  --data-root /home/ubuntu/datasets/euroc-machine-hall/sequences \
  --checkpoint v2=/home/ubuntu/compact-vio-runs/euroc-compact-vio-v2-stride-full-92aa329/checkpoint.pt \
  --checkpoint v3=/home/ubuntu/compact-vio-runs/euroc-compact-vio-v3-stateful-full-336e88c/checkpoint.pt \
  --checkpoint v4=/home/ubuntu/compact-vio-runs/euroc-compact-vio-v4-translation-state-full-94d834a/checkpoint.pt \
  --output-dir /home/ubuntu/compact-vio-runs/euroc-mh01-frozen-position-deea10f \
  --device cuda
```

The command performs inference and evaluation only; it does not construct an
optimizer, restore or apply optimizer state, train, or update a checkpoint.

## Dataset identity

- Dataset: EuRoC MAV, DOI `10.3929/ethz-b-000690084`
- Rights statement: `In Copyright - Non-Commercial Use Permitted`
- Sequence: `MH_01_easy`
- Archive: `machine_hall.zip`, 12,683,729,426 bytes
- Archive MD5: `363f5c2502b469cdd97ef85997714806`
- Archive SHA-256:
  `5ed7d07903f8d19b6c8808e2ae8a0872b281f6e34ef5497023b8ac58c3de0f6f`
- Sensor-source SHA-256:
  `10dd5e711a8c063c16b65d2fe69baa979e8b39299bcaaf5643c5683f27a6977f`
- Sensor-calibration SHA-256:
  `966b51d7ecd4086f0c7f8ccb6644d8d66447f5eb703c4398c3bf0bde10f16085`
- Position-reference SHA-256:
  `5ff4628faea7594c21668f6e31b9e92718ce844902da225b2727acc880742ee0`
- Inputs: 3,682 camera frames, 36,820 IMU measurements, and 3,099 Leica
  position-reference samples

## Frozen protocol

- Frame stride: `1`
- Metric policy:
  `sensor-point-displacement-magnitude/exact-preassociated-position-pairs/predicted-rotation-and-declared-lever-arm/no-reference-orientation/preassociated-input/no-internal-interpolation/no-alignment/no-scale-fitting/v1`
- Reference-association policy:
  `linear-within-leica-coverage/max-bracket-100ms/all-native-pairs-both-endpoints-valid/no-extrapolation/v1`
- Sensor-origin projection policy:
  `imu-to-leica-origin/from-native-t-bs/r-il-equals-r-bi-transpose-times-p-bl-minus-p-bi/delta-l-equals-t-i-plus-r-rel-r-il-minus-r-il/v1`
- Decision rule:
  `full-sensor-and-reference-coverage/beat-zero-pair-rmse/minimum-pair-displacement-magnitude-rmse/no-tie-break/v1`
- Protocol evaluation unroll: 128 pairs; v2 retained its separately frozen
  independent-zero-state-per-pair inference policy and therefore evaluated one
  pair per inference unroll.

The evaluator used exact already-associated pair identities and performed no
internal interpolation, alignment, or scale fitting. Reference positions were
associated beforehand only by the frozen linear interpolation rule: within
Leica coverage, no extrapolation, a maximum 100,000,000 ns bracket, and both
endpoints valid for a native pair.

The declared Leica origin in the IMU/prediction frame was
`[0.0748903, -0.0184772, -0.120209]` m. Predicted rotation therefore affected
the projected Leica-point displacement through this lever arm, but no
independent reference orientation was available or scored.

No candidate, checkpoint, association, alignment, threshold, metric, or
decision-rule tuning occurred during this frozen evaluation.

## Association and coverage

| Association item | Exact value |
|---|---:|
| Camera frames | 3,682 |
| Associated camera frames | 3,139 |
| Linearly interpolated camera frames | 3,139 |
| Native exact-reference camera frames | 0 |
| Frames rejected over a reference gap | 543 |
| Frames rejected outside reference coverage | 0 |
| Maximum selected interpolation bracket | 100,000,000 ns |
| Maximum observed interpolation bracket | 647,000,064 ns |
| Retained contiguous reference segments | 207 |
| Eligible native reference pairs | 2,926 |
| Rejected native pairs | 755 |

Each candidate had identical coverage: 3,681 sensor pairs, 3,681 produced
pairs, 2,926 reference pairs, 2,926 scored pairs, and 755 produced sensor pairs
excluded from scoring by the frozen reference rule. Consequently, “full
reference coverage” in the decision means all 2,926 eligible reference pairs
were scored; it does not erase the 755 pairs excluded across reference gaps.

## Candidate identity

All three checkpoints name training split-manifest SHA-256
`96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`.

| Candidate | Training run ID | Training revision | Training-config SHA-256 | Epoch | Checkpoint SHA-256 | Frozen inference policy |
|---|---|---|---|---:|---|---|
| v2 | `euroc-compact-vio-v2-stride-full-92aa329` | `92aa3294002a9da5861961a314fe74e2bb1ada05` | `88792b038687442f5707dfa72fde12c5a05473aa0236dc4281543df85565cba4` | 28 | `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605` | `independent-zero-state-per-pair/v1` |
| v3 | `euroc-compact-vio-v3-stateful-full-336e88c` | `336e88c7e80f6841c7d25b7da311172b40f5a3ba` | `5f95e1a6b9e2958d81b15ecd0d063712f1497d63273ac5e22aa59b1a742ea431` | 26 | `40d18a9a3a04131d04e06a4ab313279613d1dc2339d1758f99777ecb70de8c37` | `stateful-contiguous-native-pairs/v1` |
| v4 | `euroc-compact-vio-v4-translation-state-full-94d834a` | `94d834a82bddb2e6185fb70ec289fd45017c325c` | `ca8d95e9502383897e78b81274dc375b219a7b29cad0e42c71ac8c5bdc0ce85a` | 30 | `e775adb16aa4f9522aa577a32704a54db5c82c53685b0e97fb8d149402bf159d` | `stateful-contiguous-native-pairs/v1` |

## Position-only results

All distance values are metres. These are the exact values in the result
summary, without rounding or post-result selection.

| Candidate | Pair displacement-magnitude RMSE | Cumulative scored-distance RMSE | Predicted scored distance | Reference scored distance | Distance ratio | Total scored-distance error |
|---|---:|---:|---:|---:|---:|---:|
| Zero motion | 0.02649378180034436 | 35.44859693185987 | 0.0 | 63.4297877162257 | 0.0 | 63.4297877162257 |
| v2 | 0.017339865612729627 | 13.507518956747258 | 38.7786801480933 | 63.4297877162257 | 0.6113638645865039 | 24.651107568132396 |
| v3 | 0.017810416665698072 | 9.18286459081829 | 46.772033634109 | 63.4297877162257 | 0.7373827868281585 | 16.657754082116696 |
| v4 | 0.018905045864944767 | 19.676000848537885 | 28.49295141000196 | 63.4297877162257 | 0.44920458409028075 | 34.93683630622374 |

V3 had the lowest cumulative scored-distance RMSE, but that was not the frozen
selection field. The rule first required full eligible coverage and improvement
over zero motion, then selected the minimum pair displacement-magnitude RMSE;
that field selected v2 without a tie.

## A10 inference measurements

These measurements cover model placement/evaluation, host-to-device transfer,
forward execution, device-to-host transfer, and no dedicated warm-up. They are
A10 worker measurements, not target-device benchmarks.

| Candidate | Unroll | State initializations | Batches | Pairs/s | Batch p50 ms | Batch p95 ms | Peak allocated bytes | Peak reserved bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v2 | 1 | 3,681 | 58 | 3777.3506392135723 | 8.256720000645146 | 9.610861998226028 | 234,314,752 | 343,932,928 |
| v3 | 128 | 1 | 29 | 1829.4058090261592 | 68.10269600100582 | 73.56013500248082 | 423,115,776 | 511,705,088 |
| v4 | 128 | 1 | 29 | 1103.4782528726796 | 115.0568419980118 | 122.80197500513168 | 423,115,776 | 511,705,088 |

## Indexed artifact hashes

| File | SHA-256 |
|---|---|
| `artifact-manifest.json` | `184d9427ebec373edb4da222bba5ea382146369a61b471b92b30b0e328ce8e76` |
| `evaluation-summary.json` | `65d37221572c458ca86281ef01c3ae41345fb35b66c99ef632ddfe0f894de5b4` |
| `v2-metrics.json` | `3860a222ba5efe2576050fd01d65723c75567bdfc9c17585914a5254586a3726` |
| `v2-predictions.jsonl` | `e0416e5af3f5fbbefbde148046d7e636213302adf5c24f4db60a435faa87f4d4` |
| `v3-metrics.json` | `82db78b164ffdec6acb44540f7f7ba3b57aba4e8b9c785fc51712a5bb05213a3` |
| `v3-predictions.jsonl` | `77447263b74079f7b257f4d2a2c23c66c7e0e306e7d0799e1910a78f3cfc7c6a` |
| `v4-metrics.json` | `c0223dac0e17f9a9d36fd7ba5b6d8847684ea2713c14662d291abbbe2739ce65` |
| `v4-predictions.jsonl` | `7ce297f9cdd50509fd5da22eee0ef221b8219e74f46d3f16a4d1fdb37cb0fded` |

## Interpretation limits

Machine Hall's Leica endpoint supplies position only. Displacement magnitudes
do not score direction, heading, orientation, complete pose, or ATE. Predicted
rotation is used only to project the declared IMU-to-Leica lever arm and has no
independent rotation endpoint here. The result does not supersede the earlier
`V2_03_difficult` exploratory history, prove generalization or estimator-wide
superiority, or approve publication, deployment, onboard performance, safety,
or flight. Further scientific selection still requires a separately frozen
full evaluation with the missing endpoints and applicable baselines.
