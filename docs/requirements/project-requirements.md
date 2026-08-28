# Project requirements

Status: Normative foundation; training-first development slice accepted
Last reviewed: 2026-08-28

`MUST` items below are current repository invariants. They do not resolve an
ADR. Fields marked `TBD` are unresolved and must not be converted into defaults
by an implementation.

## Research integrity

| ID | Requirement | Verification |
|---|---|---|
| R-RI-001 | Every claim-supporting run MUST identify an immutable Git commit, resolved configuration, environment, hardware, data manifests, seeds, outputs, and checksums. | Validate the run manifest and restore its retained bundle. |
| R-RI-002 | Candidate selection MUST use a protocol frozen before final-test evaluation. | Protocol revision predates final-test results. |
| R-RI-003 | Comparable configurations MUST receive equivalent permitted sensor inputs, causality, split membership, preprocessing, loop-closure policy, evaluation, and declared resource budget. Internal mechanism ablations MUST also hold backend state, initialization, IMU path, factor policy, robust loss, numerical settings, and output schedule fixed unless the protocol names that item as the independent variable. A native external reference MAY retain its own backend but MUST be reported separately. | Cross-configuration manifest and protocol audit. |
| R-RI-004 | Failed, partial, reset, and non-initializing runs MUST be reported; metrics MUST NOT cover only surviving prefixes without disclosure. | Coverage/failure fields and output audit. |
| R-RI-005 | The primary contribution MUST be selected before claim-supporting mechanism comparison. | Accepted ADR-0004. |

## Data and causality

| ID | Requirement | Verification |
|---|---|---|
| R-DATA-001 | A dataset MUST NOT be used until its source, version, rights, modalities, sensor suite, calibration status, size, checksum, and approved role are recorded. | Dataset registry and acquisition-manifest review. |
| R-DATA-002 | Train, validation, and final-test membership MUST be assigned by source group before windowing, rendering, corruption, or augmentation. | Split leakage audit. |
| R-DATA-003 | Normalization and learned preprocessing statistics MUST be derived from training membership only. | Configuration and fitted-artifact provenance. |
| R-DATA-004 | Evaluation replay MUST NOT expose sensor information newer than the estimator output timestamp. Ground truth MUST stay outside inference input and online reliability logic. Supervised training MAY expose labels only from training membership; validation/test ground truth remains evaluator-only. | Causality, data-flow, and split-access audit. |
| R-DATA-005 | Dataset files MUST NOT be committed to Git unless an explicit rights and repository-size exception is recorded. | Repository scan. |

## Training and model selection

| ID | Requirement | Verification |
|---|---|---|
| R-TRAIN-001 | The accepted Version 1 learned-development lane MUST use PyTorch and MUST pin its exact framework version, accelerator/runtime stack, determinism settings, and environment per run. | ADR-0004, environment lock, and run manifest. |
| R-TRAIN-002 | Classical VIO baselines MUST execute through their native implementation and common replay adapter; they MUST NOT be routed through a learned-training framework merely to make the diagram uniform. | Baseline build/run record and dependency audit. |
| R-TRAIN-003 | Every imported frozen learned component MUST record exact code and weight versions/hashes, rights, pretraining sources, preprocessing, inference policy, and known evaluation-data overlap. It MUST NOT be tuned on final-test data. | Dependency/weight provenance, rights review, and final-test access audit. |
| R-TRAIN-004 | Training MUST use training membership only; validation MAY be used only for declared tuning, and final-test records MUST NOT be used for fitting, architecture selection, early stopping, normalization, or hyperparameter choice. | Split-access and run-log audit. |
| R-TRAIN-005 | The accepted compact relative-motion prototype is Version 1 work. Additional fine-tuning, synthetic pretraining, learned reliability, modality gating, uncertainty learning, and A/B/C/D comparisons MUST be separately declared follow-up ablations and MUST NOT be silently folded into the first result. | ADR-0004, resolved configuration, and later ablation matrix when applicable. |
| R-TRAIN-006 | A tracker such as MLflow MAY mirror run metrics, but it MUST NOT be the sole model registry or evidence store; retained evidence MUST remain reconstructable from versioned configuration/manifests and externally retained hashed artifacts. | Tracker-independent bundle restoration. |
| R-TRAIN-007 | Checkpoints, optimizer state, training histories, and exported model binaries MUST stay out of normal Git history and follow the artifact-retention policy. | Repository and artifact-manifest audit. |
| R-TRAIN-008 | ONNX/export work MUST occur only for an evidence-selected learned component; TensorRT or another target-specific engine MUST remain conditional on the exact target decision and parity testing. | Selection record, export-parity report, and accepted deployment scope. |
| R-TRAIN-009 | The Version 1 model MUST consume a monocular `cam0` image pair and the causally corresponding six-axis IMU window, encode them with a compact CNN plus a declared GRU or Conv1D IMU encoder, fuse them recurrently, and predict relative translation and relative rotation under an explicit frame/unit/time convention. | Model/config inspection, tensor-shape tests, and geometry negative controls. |
| R-TRAIN-010 | Before a bounded full training run, the pipeline MUST pass sample inspection and a tiny forward/backward/overfit/checkpoint-load smoke. A smoke result MUST NOT be reported as held-out model quality. | Smoke-run record and separate held-out evaluation record. |

## Estimator contract

| ID | Requirement | Verification |
|---|---|---|
| R-EST-001 | Inputs and outputs MUST declare frames, transform direction, units, timestamps, validity, and reset semantics. | Accepted ADR-0002/0003 and contract tests. |
| R-EST-002 | A metric-scale claim MUST use a primary evaluation without Sim(3) scale correction. | Evaluation configuration and scale-negative test. |
| R-EST-003 | Algorithmic latency and processing latency MUST be reported separately. | Replay and runtime trace. |
| R-EST-004 | Covariance, if produced, MUST define its state, frame, tangent convention, propagation, and calibration procedure. | Interface specification and calibration report. |
| R-EST-005 | Estimator health MUST cover initialization, staleness, input gaps, resets, and invalid outputs independently of covariance. | Fault-injection tests. |

## Calibration and synchronization

| ID | Requirement | Verification |
|---|---|---|
| R-CAL-001 | A physical or replayed sensor profile MUST version camera intrinsics/distortion, camera–IMU transform, temporal-offset value and sign convention, axes, units, rates, and exposure/sample timestamp semantics. | Profile-schema validation and frame/time contract tests. |
| R-CAL-002 | IMU characterization MUST record gyroscope and accelerometer noise density, bias random walk, update rate, method, and diagnostic report for the chosen operating configuration. | IMU configuration and calibration-report review. |
| R-CAL-003 | Camera–IMU calibration data MUST provide sufficient declared motion excitation, controlled blur/visibility, and timestamp continuity; acceptance MUST inspect residual/timing/bias diagnostics and physical plausibility rather than solver convergence alone. | Calibration checklist and signed review. |
| R-CAL-004 | Calibration acceptance thresholds MUST be set for the selected sensor, lens, resolution, target, and operating mode; example thresholds from another device MUST NOT become defaults. | Accepted ADR-0003 and calibration protocol. |
| R-CAL-005 | A change to sensor hardware, mount, focus, resolution, exposure mode, sampling, firmware, driver timestamp behavior, or another declared validity condition MUST invalidate or explicitly revalidate the profile. | Calibration version/provenance audit. |

## Artifacts and infrastructure

The durability and spending controls in `R-INFRA-002`, `R-INFRA-003`,
`R-INFRA-005`, and `R-INFRA-007` gate important retained or extended paid GPU
work. They do not block ordinary local source development, documentation,
synthetic fixtures, unit tests, or bounded CPU experiments whose outputs are
reproducible from Git.
Short paid-worker smoke or reproduction checks may also proceed from a pushed
revision when their duration, cost, outputs, and teardown owner are bounded.
No future GPU-worker availability, configuration, access, or authorization is
assumed from a previous worker or previous approval.

| ID | Requirement | Verification |
|---|---|---|
| R-INFRA-001 | A rented worker MUST NOT be the only location holding versioned work or a retained artifact. | Teardown audit. |
| R-INFRA-002 | Reproducibility-critical and release artifacts MUST have a verified primary copy and an independent verified backup outside the worker. | Artifact index and hash verification. |
| R-INFRA-003 | Important GPU work MUST NOT begin until a representative bundle has completed export, deletion of its disposable source test copy (not worker termination), restoration into a new location, checksum validation, and representative load/open verification. | Restore-test report. |
| R-INFRA-004 | Credentials MUST NOT be recorded in source, configuration, manifests, logs, or artifacts. | Secret scan and manifest review. |
| R-INFRA-005 | Provisioning or using any future rented GPU worker MUST receive fresh, explicit project-owner confirmation for the exact bounded task; confirmation MUST NOT carry forward to another task. Before extended paid work, the worker cost ceiling, review time, and teardown authority MUST also be recorded. | Owner-confirmed bounded run plan; extended-run authorization record where applicable. |
| R-INFRA-006 | Normal Git history and GitHub Actions artifacts MUST NOT be treated as the general binary-artifact vault or independent backup. | Repository/artifact-location audit. |
| R-INFRA-007 | Capacity/path inspection alone MUST NOT satisfy R-INFRA-003 or establish storage independence. | Static-check report cross-referenced to the R-INFRA-003 restore record. |

## Evaluation and deployment

| ID | Requirement | Verification |
|---|---|---|
| R-EVAL-001 | Results MUST include per-sequence trajectory accuracy, scale behavior, initialization, coverage, failures, and resource measurements appropriate to the execution platform. | Evaluation bundle review. |
| R-EVAL-002 | Training-GPU timing MUST NOT be used as evidence of edge-device latency, power, memory, or thermal suitability. | Claim/evidence audit. |
| R-EVAL-003 | Runtime comparisons MUST report the distribution including tail latency and MUST compare candidates on the same declared platform/configuration; cross-hardware measurements MUST be separated. | Profiler configuration and result audit. |
| R-DEP-001 | Export equivalence MUST cover step outputs, complete trajectories, recurrent/reset state, validity paths, and failures—not only one tensor comparison. | Export parity report. |
| R-DEP-002 | Target-specific engines MUST be built and validated for the exact selected target stack. | Engine provenance record. |
| R-DEP-003 | Target runtime, version/hardware compatibility mode, supported operators, shapes, precision, and plugins MUST be explicit; every precision/runtime artifact MUST repeat trajectory and failure regression. | Target compatibility and parity report. |
| R-SAFE-001 | Offline evaluation MUST NOT authorize physical flight. | Safety-gate record. |
| R-SAFE-002 | Any vehicle integration MUST preserve independent stabilization, pilot override, failsafe, watchdog, and stale/invalid-odometry rejection. | SITL/HIL and safety review. |
| R-SAFE-003 | A vehicle interface MUST pin compatible PX4/message/transport versions and validate frames, sample timestamps/clock synchronization, delay, lever arm, fused fields, covariance/noise source, reset counter, unknown fields, and position-loss behavior. | Interface-control tests, logs, SITL, and HIL fault evidence. |

## Fixed boundaries and unresolved requirements

The following must be decided through ADRs before dependent implementation:

- Project purpose and lane: **public-source, research-only, and non-commercial**;
  exact source licence and any future binary/data release package: **TBD**.
- Estimator scope: **causal metric-scale local VIO with no loop closure in the
  primary comparison**; declaration and runtime-validation shape:
  **implemented**; exact state/frame/time/reset values: **TBD**.
- Development input choice: **EuRoC Vicon Room monocular `cam0` plus six-axis
  IMU**, consuming and validating official calibration. A future stereo or
  physical-sensor lane requires its own configuration/decision evidence.
- Estimated state, output rate, initialization mode, latency definitions, and
  latency ceiling: **TBD**; the interface requires explicit identifiers but
  supplies no project defaults.
- Accepted development direction: **one training-first compact PyTorch VIO
  prototype with an image-pair CNN, temporal IMU GRU/Conv1D encoder,
  zero-initialized gated frame-pair fusion, and relative translation/rotation
  outputs**. A/B/C/D-monitor/D and a
  native classical reference are later research ablations, not prerequisites.
- Version 1 project-side training: **accepted through ADR-0004**. Exact EuRoC
  source-sequence membership, URLs/hashes, preprocessing, layer dimensions,
  objective terms, optimizer, hyperparameters, and schedule are versioned
  development configuration/manifest values and remain unset until their
  implementation slice.
- Development-scope freeze: **accepted through ADR-0004**. Exact confirmatory run set
  from already sealed final-test membership, numerical endpoints/thresholds,
  trials, compute budget, aggregation, and stopping rule: **TBD through the
  later protocol freeze before final-test access**.
- Dataset family and modalities for the development slice: **EuRoC Vicon Room,
  `cam0` + IMU + ground truth**. Exact source-sequence roles and splits remain
  **TBD in the acquisition/split manifests before window construction**.
- Raw exact-pair translation RMSE kernel: **implemented without interpolation,
  alignment, or scale correction**; final ATE/RPE association/alignment
  protocols and numerical accuracy, failure, latency, memory, power, and
  thermal thresholds: **TBD**.
- Raw exact-pair signed translation-residual series: **implemented as
  estimated-minus-reference Cartesian components under the same explicit no
  interpolation, alignment, or scale-correction policy**; it is in-memory only
  and is not ATE/RPE, coverage/completion evidence, or frame-correctness proof.
- Explicit output-coverage kernel: **implemented for a caller-declared nonempty
  opportunity ledger**, retaining missing/invalid/valid state, reference
  availability, usability, and non-usable reason codes; exact schedule,
  timestamp association, run completion, initialization/reset, tracking-loss,
  and estimator-failure policies: **TBD**.
- Exact replay/output coverage binding: **implemented**, requiring one-to-one
  expected-opportunity and observed-envelope accounting by trigger-event
  identity and tuple ordinal.
- Terminal recorder-plan coverage binding: **implemented**, retaining the exact
  complete terminal snapshot, requiring every successful output envelope once,
  and permitting caller-declared missing slots for the failed event and
  unattempted suffix without inventing reasons or success semantics.
- Direct causal execution recording: **implemented for one internally
  constructed, fresh, clock-matched replay/session pair**, with one-event
  release, no retained partially validated batch, first-failure retention,
  later-suffix preservation, and structurally frozen in-memory plan/watermark/
  count snapshots with delivery/reset progress. A required immutable declaration
  now retains caller-supplied IDs for the recorder's existing lifecycle
  behavior. Persistent full-run traces, accepted meanings for those policy IDs,
  expected-opportunity creation, complete failure classification,
  adapter-internal proof, and scientific success criteria: **TBD**.
- Terminal recorder-envelope representation: **implemented as a deterministic,
  one-way, payload-omitted JSON projection** with a strict structural schema. It
  preserves structural execution metadata only. Schema validity does not
  authenticate recorder origin or all cross-array relationships; trusted
  envelopes originate from the encoder's validated terminal snapshot input.
  Payload identity, reconstruction,
  replayability, data provenance, complete run-manifest integration, coverage,
  lifecycle success, and scientific acceptance: **TBD**.
- Artifact vault, independent backup, retention capacity, and spending ceiling: **TBD**.
- Control boundary: **PX4 retains stabilization, failsafes, and motor control**;
  edge hardware, runtime, precision, ROS 2 transport, simulator, and physical
  test scope: **TBD**.
