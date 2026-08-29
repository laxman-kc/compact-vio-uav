# System architecture

Status: Training-first EuRoC development slice accepted; implementation in progress
Last reviewed: 2026-08-29

## Purpose

The architecture separates durable project state from disposable computation
and the common scientific substrate from estimator-specific implementations.
The accepted scope is causal metric-scale local VIO. ADR-0004 selected a compact
PyTorch training-first vertical slice over EuRoC Vicon Room `cam0`, IMU, and
ground truth; that adapter-to-checkpoint-to-evaluation path is implemented and
has executed. A separately frozen `MH_01_easy` position-only endpoint has also
evaluated the retained v2, v3, and v4 checkpoints without retraining and selected
v2 only for that narrow endpoint. A/B/C/D reliability experiments are later
research ablations, not the implementation critical path. Mapping, loop
closure, flight control, and target deployment are outside the current core.
The single controlled v5 loss ablation against the retained v2 checkpoint has
completed and failed both frozen validation guardrails. It was rejected before
fresh position evaluation. The retained TUM VI `room4` archive now has a
completed, receipt-backed header-only structural audit. The immediate
operational extension is a separately authorized regular-file allowlist
extraction of only the required `mav0` members. That operation cannot select the
dataset. Independent unit selection and protocol freeze remain mandatory before
any new model work.

## Planes

### Versioned control plane

GitHub stores source, tests, environment definitions, requirements, ADRs,
schemas, policies, versioned data/training/evaluation configurations,
dataset/split manifests, seeds, checkpoint-selection metadata, checksums, and
small reviewed reports. Future run manifests and small artifact indexes also
belong here. An optional tracking service is a view/cache, not an authority.
GitHub is not the normal store for datasets, caches, complete training
histories, large checkpoints, prediction series, or target-specific engine
files.

### Development and staging plane

The local workstation holds the development checkout and supports planning,
implementation, lightweight validation, and temporary transfer staging. It is
not assumed to have enough capacity or a configured backup for large retained
artifacts; that check is required before important paid GPU runs, not before
ordinary source development, synthetic tests, framework-neutral replay and
evaluation work, or tiny CPU training smoke tests once a trainer exists.

### Disposable execution plane

A disposable GPU worker receives an immutable Git revision and approved data
subsets, then performs only the bounded preprocessing, baseline execution,
training, evaluation, or profiling task that justified it. Worker-local
datasets, caches, tracking databases, checkpoints, and logs would be disposable
until exported and verified.

A classical implementation keeps its native dependency/runtime boundary even if
it happens to execute on a GPU-capable worker; temporary worker placement does
not give that lane a learned-framework dependency.

The previous A10 worker described in the
[2026-08-26 Brev observation](../environments/a10/inventory-2026-08-26.md) was
terminated. A new worker was observed `RUNNING`, `READY`, and `HEALTHY` on
2026-08-27; its [dated inventory](../environments/a10/inventory-2026-08-27.md)
is recorded separately. Bounded owner-authorized tasks on 2026-08-28 executed
four training runs and the frozen Machine Hall evaluation from pushed
revisions. At the end of the recorded evaluation the worker remained running by
explicit choice. These dated observations and authorizations do not authorize
another task. Every later task requires fresh state, inventory, and owner
confirmation; lifecycle capability and price must be re-observed rather than
inherited.

### Durable artifact plane

The artifact vault holds retained binary outputs. Reproducibility-critical or release artifacts require a second independently verified copy outside the worker. The vault provider and backup destination remain unresolved in [ADR-0005](adr/0005-artifact-storage.md).

## Accepted training-first development flow

```text
                       DEVELOPMENT AND CONTROL

                  local workstation -> GitHub
                                         |
                               authorized clean checkout
                                         v
                           disposable execution worker

                        DEVELOPMENT DATA PATH

EuRoC Vicon Room source units -> identity/rights/acquisition manifest
                                         |
                              official calibration
                                         |
                         calibration/clock/frame validation
                                         |
                     sequence-disjoint train/val/test split
                                         |
                   +---------------------+--------------------+
                   |                                          |
            cam0 image pair                         six-axis IMU window
                   |                                          |
             compact CNN                            GRU or Conv1D encoder
                   +---------------------+--------------------+
                                         |
                             gated frame-pair fusion
                                         |
                         relative translation + rotation
                                         |
                     PyTorch smoke -> one bounded train run
                                         |
                                 selected checkpoint.pt
                                         |
                              held-out causal inference
                                         |
                           trajectory integration/recorder
                                         |
held-out ground truth ----------------> common evaluator
                                         |
                          ATE/RPE/rotation/coverage/resources
```

Ground truth never crosses into inference input. Training code may read labels
only for training membership; validation/test ground truth belongs to the
evaluator. Official calibration is consumed and checked rather than estimated
or silently replaced. Source sequences are the split groups, so frame windows
from one physical recording cannot leak across memberships.

## Frozen Machine Hall position-only evaluation path

```text
official Machine Hall archive -> byte/hash verification -> MH_01_easy
                                                         |
                              +--------------------------+------------------+
                              |                                             |
                    cam0 + causal imu0                            Leica positions
                              |                                             |
                 sensor-only inference data               frozen <=100 ms association
                              |                                             |
                 fixed v2/v3/v4 checkpoints                eligible native pair set
                              |                                             |
                predicted relative t and R                                |
                              |                                             |
          IMU-to-Leica lever-arm projection -------------------------------+
                              |
               sensor-point displacement magnitudes
                              |
        frozen coverage/beat-zero/minimum-pair-RMSE rule
                              |
                v2 position-endpoint selection
```

This path does not expose Leica values to model inference. It derives the
Leica origin in the prediction frame from both native `imu0` and `leica0`
`T_BS` transforms and projects each prediction with
`t_I + R_relative r_IL - r_IL`. The reference has position but no orientation,
so only exact preassociated displacement magnitudes are scored. Reference-gap
filtering retains disjoint native-pair segments visibly; it does not join them
into one full trajectory. Consequently this branch cannot report direction,
heading, an independent rotation endpoint, ATE, or final pose.

## Completed controlled v2-to-v5 experiment path

```text
retained v2 checkpoint -----------------> inference-only v2 artifact
          |                                  | identity + prediction parity
          |
          +-> v2 training configuration
                    |
          add translation-magnitude loss only
                    |
       config/loss/checkpoint smoke + CI gate
                    |
             one bounded 30-epoch run
                    |
       selected epoch-29 v5 checkpoint
                    |
       frozen v2 validation guardrail
                    |
        translation FAIL + rotation FAIL
                    |
               reject v5
                    |
       do not open/infer on MH_02_easy
                    |
       retain checksum-verified evidence
                    |
 independently select + freeze new full-pose unit/protocol
                    |
      only then decide any later model work
```

The `compact-vio-export-inference` boundary retains the canonical
`TrainingConfig`, provenance, source SHA-256, inference policy, and selected
source epoch/metrics lineage, while omitting optimizer state and full training
history. It binds canonical metadata/model-state hashes, writes atomically
without replacement, and remains transparent to `load_inference_model`. The
result remains a PyTorch checkpoint, not the ONNX or target-engine work behind
M12. Its acceptance is exact state identity plus deterministic output parity
under the same declared runtime and input. The outer `.pt` SHA binds one exact
file for transport/copy integrity; it is not a cross-runtime model identity
because PyTorch container bookkeeping can vary while canonical metadata,
tensor bytes, and predictions remain identical.

V5 is a loss ablation, not a new architecture. The only intended behavioral
change is a penalty on the difference between predicted and reference
translation magnitudes. V2 topology, preprocessing, split, frame strides,
seed, optimizer, state policy, checkpoint-selection metric, and schedule remain
fixed. The versioned configuration is
`configs/training/euroc_compact_vio_v5_magnitude.json`; its only behavioral
addition is `translation_magnitude_loss_weight: 1.0`, giving unit weight to all
three Smooth-L1 terms. The loss API defaults that field to zero so v1–v4 remain
compatible. Its SHA-256 is
`7f5e50785ed1907c26f5bbea6766a4fc13fd3df591c8930ef8b15ac9f7d71af0`
and the clean execution checkout reproduced it. Any additional behavior change
would have created a different experiment.

Before `MH_02_easy`, the selected v5 checkpoint had to report validation
translation RMSE at most `0.058765891780989885` m and validation rotation RMSE
at most `0.0061899144990098035` rad—the exact retained-v2 selected values. A
missing, non-finite, or greater value stops the experiment without inspecting
the reserved position unit. These constants are enforced by the controlled
evaluation protocol parser and checkpoint-metadata preflight rather than left
as an operator-only convention.

The revision `6c46b2f8ef719a7007eef72eebe13b34575aea93` run completed in
`428.054755853` seconds and selected epoch 29, but measured validation RMSE of
`0.05985308049522323` m translation and `0.007484109588922632` rad rotation.
Both values exceeded their frozen limits, so the guardrail rejected v5.
`MH_02_easy` was not extracted, opened, or inferred; no retry, tuning, fresh
evaluation, v5 inference export, or deployment action followed.

Neither `V2_03_difficult` nor `MH_01_easy` is an untouched v5 endpoint because
both informed this hypothesis. The prior v5 position-only branch ended before
its reserved unit, so `MH_02_easy` remains unconsumed by this candidate. The
next scientific branch is not a v5 repair: a new full-pose unit and protocol
must be selected and frozen independently, including rights, provenance,
source roles, reference capabilities, controls, native backend, fairness
rules, metrics, thresholds, and tie handling. No ground truth may cross the
evaluator boundary into inference.

## Model and training boundary

The learned estimator consumes two temporally ordered `cam0` images and the
causally corresponding IMU window. A compact CNN encodes visual change, an IMU
GRU encodes the variable-length inertial window, and a recurrent fusion cell
feeds a relative translation/rotation head. The implemented v1/v2 pair path
zero-initializes fusion state for each independent pair. V3/v4 add explicit
masked causal sequence unroll for bounded training and carry state only across
contiguous evaluation chunks of one chain; v4 changes only the declared
rotation-state routing. Exact shapes, normalization, rotation representation,
loss weights, optimizer, seed, unroll, state policy, and schedule are resolved
in versioned configurations and retained in checkpoints.

The executed workflow used sample inspection and deterministic
forward-backward/save-load smoke gates before bounded 30-epoch configurations.
Training membership alone supplied fitted statistics and gradients. Validation
served its declared checkpoint-selection role. `V2_03_difficult` produced
exploratory development evidence and is closed to further architecture or
hyperparameter selection. Every retained run binds versioned configuration,
source membership and hashes, metrics, environment facts, and the exact
checkpoint. Tracking services are optional views, never the authority;
checkpoints, prediction rows, and large histories stay out of Git.

The first checkpoint and held-out report establish a development prototype, not
a publishable or flight-ready claim. A native classical reference and the
earlier A/B/C/D-monitor/D reliability design remain later research work with
their own fairness and confirmation protocols.

The rejected controlled v5 objective was
`SmoothL1(t_hat, t) + SmoothL1(||t_hat||_2, ||t||_2) + SmoothL1(r_hat, r)`.
It tested the observed distance under-recovery; it did not
directly resolve direction, rotation, long-horizon integration, or estimator
health. Because the validation guardrail failed, no fresh position pass or
provisional promotion occurred. The separately frozen full-pose gate remains
the next decision boundary.

## Current implementation boundary

Implemented now: repository/evidence tooling; a strict non-executable TUM VI
candidate loader; closed-redirect, resumable, identity-verified archive
acquisition primitives; SHA-pinned read-only TAR inventory; and atomic
allowlisted extraction with hostile-member rejection. The archive primitives
do not themselves grant transfer or scientific authority. A separate one-use
controller now consumes only a committed, time-limited operational
authorization after clean-`HEAD`, identity, capacity, destination, cost, and
expiry checks; it writes a claim before network access and a tracked receipt
only after verified transfer and safe read-only inventory. Its first execution
retained size/MD5/SHA-verified bytes but failed closed when strict inventory
encountered a DSO-tree symbolic link; no success receipt or extraction exists,
and the authorization is consumed. A separate bounded header-only structural
audit records inert special-member metadata without following links; strict
inventory and extraction remain unchanged and fail closed. Its one-use
controller applies clean-`HEAD`, source/runtime, archive, expiry, capacity,
immutable-output, and receipt-last gates. The authorized real audit completed
from revision `9709a101b28f291de23826ac8c9abec6a6eb9846`: it classified 4,485
headers as 4,472 regular files, 11 directories, and two inert symbolic links,
preserved the exact archive SHA-256, and reported
`strict_extraction_compatible: false`. The tracked receipt grants no scientific
authority. Also implemented are
the generic causal event-release,
estimator-envelope, execution-recorder, coverage, and payload-omitted trace
boundaries; typed camera/IMU and trajectory records; raw exact-pair residual,
RMSE, and SE(3) evaluation; and persisted calibration-profile/assessment
contracts. The data layer safely verifies and extracts the selected EuRoC
archives, loads strict full-state Vicon sequences, loads sensor-only sequences,
loads Leica position references without inventing orientation, constructs
causal frame-pair/IMU windows, and records source/calibration hashes.

The learned layer implements strict configuration, relative-motion geometry,
independent and causal-sequence datasets, the compact PyTorch CNN/IMU-GRU/fusion
model, deterministic training and validation, checkpoints, independent and
stateful inference, raw SE(3) result writing, and the frozen Machine Hall
position-only evaluator. Five bounded 30-epoch A10 training runs, exploratory
`V2_03_difficult` evaluations, and the fresh position-only checkpoint decision
have executed; their reviewed reports and exact external artifact identities are
recorded. M7/M9 remain in progress because the fresh endpoint has no reference
orientation or direction and the common lifecycle/full-pose exit evidence is
not complete. ONNX, TensorRT, ROS 2, PX4, and flight integration remain outside
the implemented slice.

Revision `5c54bb5fe3c67ff93ace9401beae3c06c13b81fa` added the controlled v5
loss/configuration and strict optimizer-free inference-checkpoint boundary.
GitHub Actions run 33172588729 and all 351 A10 tests passed. The retained A10
v2 export has exact-file SHA-256
`521e9813fde80f68cb0734fd474a1cf08e8d4ef767fc8cd53bd2adf08ead2202`,
canonical metadata SHA-256
`63f632912862067c471020d4cda4f2e87772eda0f2d59a29f434fba71a8be321`,
and canonical model-state SHA-256
`f70693fc2c188773ef8e78779f6e5d1a01b22e14067204cd8cc18ba4691d650d`;
its verified local artifact-manifest SHA-256 is
`17a1b73abf1223fd8a010391d768849c30830c81914e2c30e7c383d61d095723`.
Revision `6c46b2f8ef719a7007eef72eebe13b34575aea93` then passed CI and all
351 A10 tests, completed the structural smoke and one bounded v5 run, and
produced checkpoint SHA-256
`f26267f2cb55962ba236257acda0a7ac97ad87f93ae0ecdcb585026fa21f0741`.
The original five-file trainer output and its immutable manifest SHA-256
`9628a7b93da229700b07aa9bb43c07e8b31f68bd4e9ee764b4d7ad06ac63b2f9`
are preserved inside a governed wrapper. The wrapper adds the missing run
manifest, resolved configuration, environment, and execution records; its
outer artifact-manifest SHA-256 is
`548fd52ffd0d89e4a7d347c78a8e9c4ba799c84dd74f7e0a6f3a365f0ba3b91e`.
The canonical governed-v2 wrapper verifies locally. The unchanged original
trainer bundle verifies at both its worker and local paths, but the canonical
wrapper has not been copied to or verified on the worker. This is retained
failed-gate evidence, not a selected model, quality claim, or completed restore
gate.

## Technology stack by status

| Layer | Current implementation | Planned or conditional boundary |
|---|---|---|
| Repository/core | Python `>=3.10`, standard library, setuptools, unittest, Git/GitHub, JSON, JSON Schema Draft 2020-12, Ruff | Estimator-specific numeric/image packages must be pinned in the learned environment. |
| Common VIO substrate | Generic causal replay, estimator envelope with explicit declaration/init/reset validation, direct replay-to-session recording, payload-omitted terminal envelope encoding, typed camera/IMU records, translation trajectories, raw residual/RMSE and SE(3) metrics, position-magnitude evaluation, output coverage plus batch and terminal-recorder binding, and strict calibration profile/assessment contracts | Payload-complete traces and remaining common lifecycle/full-pose evaluator behavior are open; final success, failure, latency, and confirmatory metric semantics remain unresolved. |
| Development data | Strict EuRoC Vicon full-state and sensor-only/Leica-position adapters; safe verified ZIP/TAR acquisition primitives; SHA-pinned strict TAR inventory; inert header-only structural audit; versioned Vicon/Machine Hall evidence; non-executable TUM VI `room4` candidate identity; one-use operational transfer and structural-audit controllers; retained TUM VI archive with verified size/MD5/SHA; recorded failed strict inventory; and completed receipt-backed 4,485-member header classification | The TUM VI header layout is recorded, including two inert DSO symlinks, so strict extraction compatibility is false. No extraction, payload decoding, adapter validation, scientific selection, membership, or protocol is approved. The next operational boundary is a separately authorized exact allowlist of required regular files under `mav0` only. Other sources require separate rights, calibration, provenance, and role records. |
| Learned estimator | PyTorch 2.7.0 execution evidence; compact image-pair CNN, variable-window IMU GRU, recurrent fusion, relative translation/rotation head, pair and sequence training/inference, strict checkpoints, five completed A10 runs, and a rejected controlled v5 loss ablation | No v5 retry or direct model work is authorized. A new full-pose unit/protocol must be selected and frozen independently before later model work. |
| Native reference and A/B/C/D | Not on the Version 1 critical path | Later rights-reviewed research ablations retain their native/fairness boundaries and cannot be inferred from prototype results. |
| Tracking | Tracker-independent schemas/files only | MLflow is optional and currently absent. |
| GPU execution | Dated A10 smoke, five bounded training runs, and one frozen checkpoint evaluation are recorded; worker lifecycle state is not inferred from past evidence | Present state and every later task require fresh inventory and owner confirmation. |
| Export/deployment | Optimizer-free PyTorch inference-checkpoint export/load is implemented; the immutable A10 v2 file, canonical identity, prediction parity, local copy, and artifact manifest are verified | V5 failed its prerequisite and is rejected from inference export or deployment. ONNX is conditional; TensorRT, Jetson/other edge hardware, ROS 2, and PX4 scope are unresolved. |

## Repository structure: current and planned

`[current]` means the path exists with substantive implementation. `[planned]`
means current accepted scope permits incremental implementation but the path or
behavior does not exist yet. `[conditional]` remains behind an unresolved
decision.

```text
compact-vio-uav/
├── README.md                              [current]
├── docs/                                  [current: requirements/ADRs/plan/protocols]
├── governance/                            [current: policies/schemas/draft templates; zero authoritative records]
├── environments/                          [current: dated A10 inventories]
├── experiments/
│   └── schemas/                           [current: run/artifact/evidence/recorder-envelope schemas]
├── configs/                               [current: calibration schemas plus data/training/evaluation records]
├── src/compact_vio/
│   ├── replay.py                          [current]
│   ├── estimator.py                       [current: estimator envelope/interface declaration]
│   ├── execution.py                       [current: causal replay-to-estimator recorder]
│   ├── execution_trace.py                 [current: terminal payload-omitted envelope encoder]
│   ├── artifacts/                         [current]
│   ├── copy_audit.py                      [current]
│   ├── preflight.py                       [current]
│   ├── repository_policy.py               [current]
│   ├── contracts/                         [current: sensor payload/calibration-identity runtime records]
│   ├── data/                              [current: verified ZIP/TAR acquisition, inventory, full-state/sensor-only/Leica adapters]
│   ├── geometry/                          [current: translation trajectory records]
│   ├── evaluation/                        [current: residual/RMSE, SE(3), position magnitude, coverage/binding]
│   ├── learning/                          [current: config/data/model/train/checkpoint/inference/evaluation CLIs]
│   ├── backend/                           [later: classical/shared-backend research]
│   ├── baselines/                         [later: native classical reference]
│   ├── inertial/                          [later: modular ablation substrate]
│   ├── vision/                            [later: A/B visual channels]
│   ├── fusion/                            [later: C fusion policy]
│   ├── health/                            [later: D-monitor/D]
│   ├── estimators/                        [later tested compositions; estimator.py remains the contract]
├── tests/                                 [current; expands one slice at a time]
├── reports/                               [current: policy/index and reviewed v2/v3/v4/MH_01 results]
└── deployment/                            [conditional: export/target/ROS 2/PX4]
```

The names above define capability ownership, not empty scaffolding or a request
to move current files. `estimator.py` remains the framework-neutral contract;
a future `estimators/` path owns tested compositions only. Existing replay,
estimator, execution, contracts,
geometry, evaluation, and evidence code stays in place. Each planned path is
created only with its first focused, tested behavior.

## Shared contracts

All comparable configurations must share:

- A canonical sensor record with image exposure time, individual IMU timestamps,
  calibration, frames, units, validity, reset markers, and provenance. Ground
  truth is a separate label/reference: training code may access it only for
  training membership, while inference never receives it.
- A replay contract that exposes no future samples and reproduces streaming state, warm-up, reset, dropout, and stale-data behavior.
- A framework-neutral estimator boundary. Every selected profile must provide
  the declaration identifiers required by the shared contract; native
  classical adapters consume the project contract directly, while learned
  adapters perform tensor conversion inside their own boundary.
- A frozen evaluator that reports trajectory error, metric scale,
  initialization, coverage, failures, and end-to-end timing.
- A learned-run contract that records source-sequence membership, causal sample
  construction, normalization provenance, resolved model/loss/optimizer values,
  seed, environment, checkpoint identity, and the declared validation-selection
  rule.
- For internal A/B/C/D comparisons, one backend/state/init/IMU/factor/numerical/
  output contract and explicit visual-observation provenance. Native external
  references remain separate rather than being mislabeled same-backend controls.
- An experiment manifest conforming to `experiments/schemas/run-manifest.schema.json`.
- Dataset and artifact governance independent of the chosen estimator.

The first implemented replay primitive distinguishes
`measurement_time_ns`—when a measurement applies—from
`available_time_ns`—when an online estimator may observe it. All events use one
declared clock per replay; same-time ordering is explicit; and reset or invalid
events are delivered rather than filtered. The EuRoC adapters now map native
camera/IMU timestamps and payloads into the learned data path; adapters for any
other source must preserve the same explicit semantics.

The estimator declaration currently freezes only which decisions a profile
must name: state schema/variables, metric-scale mechanism, initialization,
reset, recurrence and warm-up, output timestamp/schedule, causality,
algorithmic/processing latency, staleness, and input-gap policies. It supplies
no default values for those decisions. A declared runtime session checks exact
interface identity and explicit initialization state. Its startup state,
post-reset state, and valid/initialized relationship are required profile
values rather than global defaults. The wrapper applies the declared reset
state before delivering reset but cannot prove adapter-internal state was reset.
The concrete profile and estimator remain M3 work.

The first geometry/evaluation kernels store Cartesian translations under an
explicit reference frame, tracked frame, transform direction, unit, clock, and
timestamp-semantics convention plus a shared sequence/segment scope. Its only
pairing mode requires exact ordered sample identity and time and an explicit
policy whose supported modes are exact association with no interpolation,
trajectory alignment, or scale correction.

One kernel retains the raw signed Cartesian difference, estimated translation
minus reference translation, for every exact pair; the other reduces exact-pair
translation error to RMSE. Constant offsets, rotations, and scale errors
therefore remain visible. The residual series is in-memory only. Neither kernel
is labelled ATE or RPE, establishes coverage or completion, proves declared
frame metadata is scientifically correct, or defines a final evaluation
protocol.

The first coverage kernel consumes a nonempty ordered ledger whose expected
opportunities, classification policy, and reason schema are named explicitly.
It preserves missing, invalid, valid, reference availability, usability, and
multi-label non-usable reasons as separate evidence. It does not inspect
positions, infer an output schedule or timestamp pairing, or classify a
non-usable item as an estimator failure. Run lifecycle, initialization, reset,
tracking-loss, and completion semantics remain unresolved evaluator work.

The coverage binding layer retains replay events and each event's exact ordered
estimator-output tuple. Each expected opportunity binds to an explicit trigger
event and either one zero-based output ordinal or no ordinal for a declared
missing outcome. Event identity/order, clock, causal availability, output
validity, exhaustive opportunity binding, and unbound extra outputs are checked
without timestamp association or an assumed output rate.

The causal execution recorder closes the caller-supplied batch gap for its own
runtime path. It constructs and privately retains a fresh replay/session pair
with the same clock, releases at most one event before each adapter call, and
retains no partially validated output batch. An ordinary processing exception
creates one terminal failure record for the consumed event and leaves later
events unconsumed; process-control exceptions also terminalize the recorder
before being re-raised. Structurally frozen in-memory snapshots retain the full
event plan, causal watermark, delivery/reset progress, and execution counts,
plus an immutable lifecycle-policy declaration. That declaration contains only
required opaque IDs for the recorder's existing replay-exhaustion, processing-
exception, process-control-exception, and unattempted-suffix behavior; it does
not select a taxonomy, threshold, schedule, or success rule. Generic payloads
are not deep-copied, and no payload-complete trace format exists yet. This proves
only the recorder-observed envelope path: it does not prove adapter-internal sample use
or reset behavior, define output opportunities, classify missing/failure causes,
or establish scientific run success.

The terminal execution-coverage bridge binds a caller-declared coverage ledger
to that full recorder snapshot. Produced outcomes must identify every output in
every successful batch exactly once. Missing outcomes may identify the failed
event or the unattempted planned suffix, so a surviving prefix cannot silently
be presented as the whole execution. The bridge still does not invent expected
opportunities, reason codes, failure taxonomy, thresholds, completion, or run
success.

The one-way execution-envelope projection converts a structurally valid terminal
recorder snapshot into deterministic JSON metadata. It retains the complete
planned-event envelope order, successful output-envelope order, lifecycle-policy
IDs, progress counts, and first-failure metadata, but manually excludes all
event/output payloads and exposes no deserializer. It is intentionally not a
payload-complete execution trace: equal envelopes can come from different input
or output payloads, and the encoder adds no dedicated representation, type,
hash, or cryptographic commitment for those omitted payloads. The envelope alone
therefore cannot prove their identity. It also does not establish replayability,
provenance, adapter-internal lineage,
coverage semantics, lifecycle success, or scientific acceptance.
The JSON Schema enforces structure and local terminal/exhaustion conditionals,
but cannot authenticate recorder origin or prove every cross-array count and
reference. A schema-valid external document is not recorder evidence by itself;
the trusted path is the one-way encoder applied to a validated snapshot.

## Deployment boundary

Training-platform throughput does not establish onboard fitness. Target-device selection requires a declared power, mass, thermal, memory, sensor-interface, and latency envelope. ONNX/TensorRT, Jetson, ROS 2, PX4, and physical sensor integration remain conditional decisions; no target-specific interface is part of the foundation.

If vehicle integration is later approved, PX4 retains stabilization, pilot
override, failsafes, and motor control. VIO begins only as an externally
health-gated odometry measurement source. Physical tests cannot begin directly
from an offline benchmark result.

## Failure containment

- Missing or stale sensor input produces an explicit health state, never a silently reused pose.
- Frame, unit, timestamp, and scale errors must be detected by negative-control tests.
- Failed and partial trajectories remain visible in evaluation; surviving prefixes cannot be reported as complete runs.
- A learned confidence score is not treated as estimator covariance without a defined state, frame, propagation rule, and calibration evidence.
- Destruction of a worker must not destroy versioned state or retained evidence.
