# EuRoC compact VIO v5 controlled magnitude-loss experiment plan

Status: Prospective control record — pending execution

Plan date: 2026-08-28

## Decision to be made

Determine whether adding one explicit translation-magnitude loss to the retained
v2 training configuration improves travelled-distance recovery without giving
up its local displacement advantage. This record authorizes one implementation,
one smoke, one bounded 30-epoch training run, and one predeclared fresh
evaluation. It does not authorize a hyperparameter sweep or a result claim.

The retained v2 checkpoint remains the control. The completed `MH_01_easy`
position-only rule selected v2 from v2, v3, and v4 using pair
displacement-magnitude RMSE. That selection is narrow: it does not cover
direction, independent rotation, full pose, or ATE.

## Fixed control identity

- Control candidate: v2
- Training configuration:
  `configs/training/euroc_compact_vio_v2_stride_augmented.json`
- Training-configuration SHA-256:
  `88792b038687442f5707dfa72fde12c5a05473aa0236dc4281543df85565cba4`
- Training revision:
  `92aa3294002a9da5861961a314fe74e2bb1ada05`
- Training run ID: `euroc-compact-vio-v2-stride-full-92aa329`
- Selected epoch: 28
- Checkpoint SHA-256:
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`
- Split-manifest SHA-256:
  `96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`
- Frozen narrow-endpoint evidence:
  [EuRoC MH_01 position-only evaluation](euroc-mh01-frozen-position-evaluation-2026-08-28.md)

An inference-only v2 checkpoint is an operational copy of this exact selected
model state. `compact-vio-export-inference` retains the canonical
`TrainingConfig`, provenance, source-checkpoint SHA-256, inference policy, and
selected source epoch/metrics lineage, while omitting optimizer state and the
full training history. It records canonical metadata and model-state hashes,
writes atomically without replacing an existing path, and remains loadable by
the normal `load_inference_model` boundary. It is not ONNX, a target-specific
engine, or deployment approval. Export acceptance requires exact retained
parameter identity and deterministic prediction parity with the source
checkpoint under the same declared framework, device, runtime, and test input.
The outer artifact SHA identifies one exact file for transport/copy integrity;
it is not a cross-runtime model identity.

Local verification on the uncommitted implementation worktree exported the
real selected v2 checkpoint and passed bitwise prediction parity. The temporary
artifact recorded:

- artifact SHA-256:
  `4e2281a97a071cd20c16b2e5329a750b681fa74aea53002f110662ebc7fba29e`;
- canonical metadata SHA-256:
  `63f632912862067c471020d4cda4f2e87772eda0f2d59a29f434fba71a8be321`;
- canonical model-state SHA-256:
  `f70693fc2c188773ef8e78779f6e5d1a01b22e14067204cd8cc18ba4691d650d`;
  and
- selected source epoch: 28.

This is local implementation evidence, not the retained execution artifact.

Immutable revision `5c54bb5fe3c67ff93ace9401beae3c06c13b81fa` then passed
GitHub Actions run 33172588729 and all 351 Torch-enabled A10 tests. Its retained
A10 export has exact-file SHA-256
`521e9813fde80f68cb0734fd474a1cf08e8d4ef767fc8cd53bd2adf08ead2202`,
the same canonical metadata/model-state hashes above, and bitwise prediction
parity. A repeated A10 export produced the same exact file SHA. The local and
A10 containers have identical model payloads; only PyTorch's internal
`archive/.data/serialization_id` differs across their runtimes. The A10 file is
retained under `outputs/inference-exports-5c54bb5/` with verified
artifact-manifest SHA-256
`17a1b73abf1223fd8a010391d768849c30830c81914e2c30e7c383d61d095723`.

## Single-change hypothesis

The completed evidence shows path-length under-recovery: v2 recovered
`0.6113638645865039` of the scored `MH_01_easy` distance and
`0.6386789251739308` of the earlier `V2_03_difficult` reference path. The
controlled hypothesis is that directly penalizing error between predicted and
reference translation magnitudes can reduce that scale bias while the existing
translation-vector and rotation losses preserve their current responsibilities.

The intended objective is:

```text
L = SmoothL1(t_hat, t)
  + SmoothL1(||t_hat||_2, ||t||_2)
  + SmoothL1(r_hat, r)
```

The v5 configuration is
`configs/training/euroc_compact_vio_v5_magnitude.json`. Its new field is
`translation_magnitude_loss_weight`, set to `1.0`; the translation-vector and
rotation weights are also `1.0`. The loss API is
`motion_loss(..., translation_magnitude_weight=0.0)`: zero preserves v1–v4
behavior, while v5 passes `1.0` and records a separate
`translation_magnitude_loss` metric. The prospective configuration SHA-256 is
`7f5e50785ed1907c26f5bbea6766a4fc13fd3df591c8930ef8b15ac9f7d71af0`;
the clean execution checkout must reproduce it. No outcome is implied by
adding the term.

Except for that declared loss term and the metadata needed to identify it, v5
must retain v2's model topology, input normalization, split, frame strides
`[1, 2]`, seed `20260828`, optimizer settings, checkpoint-selection metric,
independent-pair state policy, and 30-epoch schedule. Any additional behavioral
change invalidates this controlled comparison and requires a new plan.

## Execution gates

Before the bounded training run:

1. Unit tests must cover configuration validation, finite magnitude loss,
   zero-motion and exact-motion cases, gradients, metric accumulation,
   checkpoint round-trip, and rejection of incompatible checkpoints.
2. The inference-only v2 export must pass its identity and deterministic parity
   gate.
3. A smoke run must complete forward, backward, optimizer update, save, and
   inference reload without a non-finite value.
4. The execution revision must be pushed, CI must pass, the checkout must be
   clean, and the worker inventory and bounded authorization must be current.
5. The output directory must be new and the run must retain the resolved
   configuration, environment, history, checkpoint, evaluation outputs, and
   artifact manifest.

The exact execution revision, CI run, worker record, run ID, command, and output
path are all **pending execution**.

### Post-training validation guardrail

The selected v5 checkpoint may proceed to `MH_02_easy` only when both of these
predeclared limits hold:

- validation translation RMSE is at most
  `0.058765891780989885` m; and
- validation rotation RMSE is at most
  `0.0061899144990098035` rad.

These are the exact selected-v2 validation values in the retained v2 run
summary, not values chosen from v5. A missing, non-finite, or greater value
fails the guardrail. Failure rejects v5 before `MH_02_easy` is inspected, so
the reserved unit remains unused by this candidate.

## Fresh-evaluation rule

`V2_03_difficult` and `MH_01_easy` have already informed development and cannot
serve as untouched confirmation for v5. `MH_02_easy` is reserved as the one
next position-only decision unit. It comes from the already verified EuRoC
Machine Hall archive (DOI `10.3929/ethz-b-000690084`) under the recorded
`In Copyright - Non-Commercial Use Permitted` statement. The archive is
12,683,729,426 bytes with MD5 `363f5c2502b469cdd97ef85997714806` and SHA-256
`5ed7d07903f8d19b6c8808e2ae8a0872b281f6e34ef5497023b8ac58c3de0f6f`.
The prospective acquisition/role record is
`configs/data/euroc_machine_hall_mh02_position_v1.json`, SHA-256
`3546ed0ed0721224c156e8b929ba5cf3aba517da381cc0f832162380599ca137`.

Before candidate results are inspected, the repository must freeze the exact
`MH_02_easy` sensor, calibration, and position-reference identities; reference
capabilities; eligible-pair construction; v2/v5/zero-motion baselines; metric
semantics; complete-coverage rule; no-tie decision rule; and the exact
selected-v2 validation limits above as a pre-inference guardrail. The evaluator
must verify each checkpoint hash, embedded policy when available, dataset/split
provenance, and selected validation metrics before loading the reserved
sequence or producing any candidate prediction. Those extracted
source identities and the protocol path/SHA-256 are **pending protocol
freeze**; they must not be borrowed from `MH_01_easy`.

For the position/distance endpoint, v5 is accepted only if all of these frozen
conditions hold on the same eligible pairs for v5, v2, and zero motion:

- identical complete eligible-pair coverage;
- pair displacement-magnitude RMSE strictly below both v2 and zero motion;
- cumulative scored-distance RMSE strictly below v2; and
- absolute distance-ratio error `abs(ratio - 1)` strictly below v2.

A tie or failure of any gate rejects v5. There is no tie-break and no retry. No
preprocessing, checkpoint, association, alignment, scale fitting, metric,
threshold, or loss change may be made after the fresh results are inspected. A
rejected v5 is not promoted; v2 remains the retained candidate for its already
established narrow endpoint.
Once any v2/v5 decision result from `MH_02_easy` is inspected, the unit is
consumed and cannot support another model-selection decision.

## Required full-pose gate

Passing the position/distance endpoint would not establish VIO quality. A
separate rights-compatible evaluation unit with reference position and
orientation must be frozen and must compare the retained learned candidate,
v2, zero motion, and a native classical baseline under one fairness contract.
It must report ATE, translational and rotational RPE, rotation error, drift,
coverage/failures, latency, and memory. The dataset, classical backend, primary
metric, thresholds, and tie rule are **pending protocol freeze** and are not
selected here.

No learned candidate may be promoted for navigation or deployment before this
full-pose gate. If the retained direct learned candidate fails the frozen
full-pose rule against the required controls, direct-model tuning stops and the
next architecture investigation is the planned IMU-anchored hybrid. ONNX,
TensorRT, target hardware, ROS 2, PX4, HIL, and flight testing remain outside
this experiment.

## Pending evidence fields

The outcome update must replace none of the control history above. It must add:

- execution revision and CI URL;
- confirmation that the execution checkout reproduced the frozen v5
  configuration SHA-256;
- exact loss field/API identity and coefficient;
- worker/environment identity and exact command;
- run start/end time, duration, selected epoch, and failure status;
- checkpoint and artifact-manifest SHA-256 values;
- smoke, test, repository-policy, and artifact-verification evidence;
- fresh protocol and source identities;
- complete v2/v5/zero-motion metric and coverage tables; and
- the mechanical accept/reject outcome with every interpretation limit.

Until those fields exist, v5 has no measured result and this document is not a
training, quality, generalization, deployment, safety, or flight-readiness
report.
