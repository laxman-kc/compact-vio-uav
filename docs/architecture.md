# System architecture

Status: Local-VIO and training flow defined; detailed estimator, sensor, and deployment choices unresolved
Last reviewed: 2026-08-27

## Purpose

The architecture separates durable project state from disposable computation
and the common scientific substrate from estimator-specific implementations.
The main research direction is causal metric-scale local VIO, with classical
references and a physically anchored compact hybrid candidate. Mapping, loop
closure, flight control, and target deployment are outside the current core.

## Planes

### Versioned control plane

GitHub currently stores source, tests, environment definitions, requirements,
ADRs, schemas, policies, and small reviewed evidence. When created, versioned
experiment/training configurations, dataset/split manifests, seeds,
checkpoint-selection metadata, run manifests, artifact indexes, checksums, and
small reviewed reports also belong here. An optional tracking service is a
view/cache, not an authority. GitHub is not the normal store for datasets,
caches, complete training histories, large checkpoints, or target-specific
engine files.

### Development and staging plane

The local workstation holds the development checkout and supports planning,
implementation, lightweight validation, and temporary transfer staging. It is
not assumed to have enough capacity or a configured backup for large retained
artifacts; that check is required before important paid GPU runs, not before
ordinary source development, synthetic tests, framework-neutral replay and
evaluation work, or tiny CPU training smoke tests once a trainer exists.

### Disposable execution plane

A future GPU worker would receive an immutable Git revision and approved data
subsets, then perform only the bounded preprocessing, baseline execution,
training, evaluation, or profiling task that justified it. Worker-local
datasets, caches, tracking databases, checkpoints, and logs would be disposable
until exported and verified.

A classical implementation keeps its native dependency/runtime boundary even if
it happens to execute on a GPU-capable worker; temporary worker placement does
not give that lane a PyTorch dependency.

The previous A10 worker described in the
[2026-08-26 Brev observation](../environments/a10/inventory-2026-08-26.md) was
terminated. A new worker was observed `RUNNING`, `READY`, and `HEALTHY` on
2026-08-27; its [fresh inventory](../environments/a10/inventory-2026-08-27.md)
is recorded separately. It is approved only for the current bounded
implementation smoke, not for dataset acquisition or model training. Every later
task requires fresh confirmation, and lifecycle capability and price must be
re-observed rather than inherited from either worker.

### Durable artifact plane

The artifact vault holds retained binary outputs. Reproducibility-critical or release artifacts require a second independently verified copy outside the worker. The vault provider and backup destination remain unresolved in [ADR-0005](adr/0005-artifact-storage.md).

## Full research and model-training flow

```text
                       DEVELOPMENT AND CONTROL

                  local workstation -> GitHub
                                         |
                                         | clean clone after owner approval
                                         v
                           future temporary GPU worker

                       DATA AND EXPERIMENT SUBSTRATE

approved dataset sources -> canonical timestamps/frames/calibration/validity
                                         |
                              frozen source-group splits
                         |
                         +-- train
                         |     -> causal training samples
                         |     -> direct learned / anchored hybrid trainers
                         |        (proposed framework)
                         |     -> candidate checkpoints
                         |
                         +-- validation
                         |     -> causal replay
                         |     -> native classical + checkpoint inference
                         |     -> common evaluator
                         |     -> freeze candidates under the protocol
                         |
                         +-- final test (sealed until protocol/candidates freeze)
                               -> causal replay
                               -> frozen classical/learned/hybrid candidates
                               -> common evaluator
                               -> accuracy / scale / failures / latency / memory
                               -> scientific claim decision
                                             |
                 +-----------------------+-----------------------+
                 |                                               |
         classical winner                              learned/hybrid winner
         native packaging                       checkpoint + conditional ONNX
                 |                                               |
                 +---------------- exact-target validation ------+
                                         |
                          conditional TensorRT / ROS 2 / PX4
```

The validation branch applies the frozen checkpoint-selection rule. The
final-test branch stays sealed until the protocol and candidates are frozen and
is never a training or checkpoint-selection input. Classical systems do not
pass through a neural training/export pipeline. If a hybrid candidate wins,
only its neural component may require model export. If a classical system wins,
deployment uses its native build and packaging path.

## Model-training design

PyTorch is the proposed research-training framework for learned components,
subject to ADR-0004 acceptance. The proposed training order is deliberately
small:

1. Reproduce one classical local-VIO reference through the common replay. This
   establishes a non-neural accuracy, failure, and resource reference and has no
   neural training step.
2. Implement and run visual-only and IMU-only diagnostics only where they are
   needed to verify modality contribution. Use PyTorch only when a particular
   diagnostic is explicitly defined as learned.
3. Train an always-on direct learned visual-inertial control under the frozen
   data and compute budget.
4. Train the primary working candidate: physical IMU propagation or
   preintegration anchors metric time/scale, and a compact learned visual branch
   predicts a correction or measurement.
5. Compare all candidates through the same streaming inference adapter and
   frozen evaluator. Only evidence selects the scientific candidate.

The exact encoder, recurrent state, parameter count, loss, optimizer, image
resolution, sequence length, batch size, and training schedule remain
experiment decisions. No CNN/GRU layout or parameter band is silently inherited
from the reference proposal. Synthetic pretraining such as TartanAir, compute
gating, robustness training, and learned uncertainty are later ablations, not
required steps in the first working model.

MLflow is an optional temporary observer for curves and comparisons. It is not
the model registry or source of truth. Every retained run is reconstructable
from versioned configuration and manifests plus trajectories, metrics,
environment records, and either the learned checkpoint or the classical
source/build provenance. Checkpoints and large histories stay out of Git.

## Current implementation boundary

Implemented now: repository/evidence tooling, the generic causal event-release
primitive, a framework-neutral estimator envelope with a required declaration
shape and initialization/reset validation, typed camera/IMU payload records,
and strict persisted calibration-profile plus
separate assessment contracts. The committed fixture is synthetic and rejected;
there is no accepted real sensor or dataset profile. Planned next: the
geometry/evaluation core, one rights-approved dataset adapter with its actual
profile, and one classical baseline. No estimator algorithm, numerical backend,
model, training loop, dataset files, approved split, dataset adapter,
checkpoint, ONNX graph, TensorRT engine, ROS 2 node, or PX4 bridge exists yet. A
candidate-only dataset registry exists, but it is not data-use approval.

## Technology stack by status

| Layer | Current implementation | Planned or conditional boundary |
|---|---|---|
| Repository/core | Python `>=3.10`, standard library, setuptools, unittest, Git/GitHub, JSON, JSON Schema Draft 2020-12, Ruff | Numerical array/vision library for estimator work is unresolved. |
| Common VIO substrate | Generic causal replay, estimator envelope with an explicit interface-declaration shape and initialization/reset validation, typed camera/IMU records, and strict persisted calibration profile/assessment contracts | Geometry, evaluator, actual dataset profiles, and adapters are planned; exact state and policy identifiers, sensor configuration, concrete conventions, thresholds, and numerical backend remain unresolved. |
| Classical lane | Not implemented | Later rights-reviewed baseline uses its native build/runtime with no PyTorch or MLflow dependency. |
| Learned/hybrid lane | Not implemented; no training framework is installed as a project dependency | A learned training/inference adapter is conditional on ADR-0004; PyTorch is proposed, while exact framework/version, topology, losses, optimizer, and schedule remain unresolved. |
| Tracking | Tracker-independent schemas/files only | MLflow is optional and currently absent. |
| GPU execution | One live A10 approved only for the current bounded implementation smoke | Every later task requires fresh owner confirmation and inventory. |
| Export/deployment | Not implemented | ONNX is conditional; TensorRT, Jetson/other edge hardware, ROS 2, and PX4 scope are unresolved. |

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
├── environments/                          [current: historical and active-task A10 inventories]
├── experiments/
│   ├── schemas/                           [current: run/artifact/evidence schemas]
│   └── configs/                           [planned: frozen experiment configs]
├── configs/                               [current: calibration schemas/rejected synthetic fixtures; other configs planned]
├── src/compact_vio/
│   ├── replay.py                          [current]
│   ├── estimator.py                       [current: estimator envelope/interface declaration]
│   ├── artifacts/                         [current]
│   ├── copy_audit.py                      [current]
│   ├── preflight.py                       [current]
│   ├── repository_policy.py               [current]
│   ├── contracts/                         [current: sensor payload/calibration-identity runtime records]
│   ├── data/                              [planned: approved dataset adapters]
│   ├── geometry/                          [planned: transforms/trajectory operations]
│   ├── evaluation/                        [planned: metrics/failure/resource scorecard]
│   ├── baselines/                         [planned: native classical adapters]
│   ├── learning/                          [conditional on ADR-0004]
│   │   ├── models/                        [conditional: direct and hybrid learned parts]
│   │   ├── training/                      [conditional: selected-framework train/checkpoint path]
│   │   └── inference/                     [conditional: frozen-checkpoint adapter]
├── tests/                                 [current; expands one slice at a time]
├── reports/                               [planned: small reviewed results only]
└── deployment/                            [conditional: export/target/ROS 2/PX4]
```

The names above define ownership boundaries, not empty scaffolding that must be
created immediately. Each planned path appears only when its first focused,
tested behavior is implemented.

## Shared contracts

All candidates must share:

- A canonical sensor record with image exposure time, individual IMU timestamps, calibration, frames, units, validity, reset markers, provenance, and optional ground truth.
- A replay contract that exposes no future samples and reproduces streaming state, warm-up, reset, dropout, and stale-data behavior.
- A framework-neutral estimator boundary. Every selected profile must provide
  the declaration identifiers required by the shared contract; native
  classical adapters consume the project contract directly, while learned
  adapters perform tensor conversion inside their own boundary.
- A frozen evaluator that reports trajectory error, metric scale, initialization, coverage, failures, and end-to-end timing.
- An experiment manifest conforming to `experiments/schemas/run-manifest.schema.json`.
- Dataset and artifact governance independent of the chosen estimator.

The first implemented replay primitive distinguishes
`measurement_time_ns`—when a measurement applies—from
`available_time_ns`—when an online estimator may observe it. All events use one
declared clock per replay; same-time ordering is explicit; and reset or invalid
events are delivered rather than filtered. Dataset adapters will later map
source timestamps and payloads into this contract.

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
