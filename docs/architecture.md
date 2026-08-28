# System architecture

Status: Local-VIO boundary defined; proposed modular experiment and all concrete estimator choices unresolved
Last reviewed: 2026-08-27

## Purpose

The architecture separates durable project state from disposable computation
and the common scientific substrate from estimator-specific implementations.
The accepted scope is causal metric-scale local VIO. ADR-0004 now proposes one
modular complementary-visual estimator with controlled A/B/C/D configurations
and deterministic reliability handling; that proposal is not accepted.
Mapping, loop closure, flight control, and target deployment are outside the
current core.

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
not give that lane a learned-framework dependency.

The previous A10 worker described in the
[2026-08-26 Brev observation](../environments/a10/inventory-2026-08-26.md) was
terminated. A new worker was observed `RUNNING`, `READY`, and `HEALTHY` on
2026-08-27; its [dated inventory](../environments/a10/inventory-2026-08-27.md)
is recorded separately, and the owner authorized that bounded implementation
smoke only. The observation and authorization do not carry forward. Every later
task requires fresh state, inventory, and owner confirmation; lifecycle
capability and price must be re-observed rather than inherited from either
worker.

### Durable artifact plane

The artifact vault holds retained binary outputs. Reproducibility-critical or release artifacts require a second independently verified copy outside the worker. The vault provider and backup destination remain unresolved in [ADR-0005](adr/0005-artifact-storage.md).

## Proposed research and conditional-training flow

```text
                       DEVELOPMENT AND CONTROL

                  local workstation -> GitHub
                                         |
                               authorized clean checkout
                                         v
                           disposable execution worker

                      APPROVED DATA AND SENSOR TRUTH

approved source -> one dataset adapter -> camera / IMU / calibration records
                           |
                           +---------------- evaluation reference / ground truth
                           |                                  |
                           v                                  |
                     causal replay                            |
                           |                                  |
             +-------------+-------------------+              |
             |                                 |              |
      inertial propagation          visual configuration      |
                                    A: motion observations    |
                                    B: frozen landmarks       |
                                    C: A+B+deduplication      |
                                    D-monitor: C+monitor only |
                                    D: C+protocol-declared action |
             |                                 |              |
             +-------------+-------------------+              |
                           |                                  |
                     shared backend                           |
                           v                                  |
                estimator envelope / recorder                 |
                           |                                  |
                           +------------> common evaluator <---+
                                               |
                                  discovery failure atlas
                                               |
                              targeted training decision
                                /                    \
                         no training          approved later branch
                              |                       |
                              |        approved training data/framework
                              |                       |
                              |               bounded training
                              |                       |
                              +-------> frozen candidate/checkpoint
                                                 |
                                         unchanged evaluator
                                                 |
                                later confirmatory-protocol freeze
```

Ground truth never crosses into causal estimator input or online reliability
logic. A native classical reference also enters the common replay/evaluator,
but retains its native backend/runtime and is reported separately from the
same-backend A/B/C/D ablations.

The proposed internal configurations are A (fast visual motion), B (one frozen
rights-approved learned-landmark channel), C (both with explicit provenance and
correlation/duplicate handling), D-monitor (C plus diagnostics but no action),
and D (C plus one predeclared deterministic reliability action). The exact
method behind every block remains unresolved. A/B/C/D fairness includes the
same state, initialization, IMU path, factors, robust loss, numerical settings,
output schedule, permitted inputs, preprocessing, resource/measurement budget,
and evaluator.

## Conditional model-training branch

ADR-0004 proposes that Version 1 performs no project-side training. A frozen
pretrained visual component may enter B only after exact code/weight identity,
rights, provenance, preprocessing, and evaluation-overlap review. Direct
end-to-end VIO is optional external work, not a critical-path control.

After A/B/C/D discovery runs, a failure atlas may justify one targeted training
or fine-tuning branch. Opening that branch requires a separate decision naming
the isolated learnable deficit, component, approved training data, framework,
objective, selection rule, trials, and budget. No framework is selected now;
PyTorch, MLflow, synthetic pretraining, learned reliability, and learned
uncertainty remain conditional candidates rather than dependencies.

If training is opened, training membership alone supplies fitting data,
validation follows its declared selection role, and final test remains sealed.
Every retained run remains reconstructable from versioned configuration,
manifests, trajectories, metrics, environment records, and the exact checkpoint.
Tracking services are optional views, never the authority. Checkpoints and large
histories stay out of Git.

## Current implementation boundary

Implemented now: repository/evidence tooling, the generic causal event-release
primitive, a framework-neutral estimator envelope with a required declaration
shape and initialization/reset validation, a direct causal execution recorder,
typed camera/IMU payload records, immutable translation-trajectory records, raw
exact-pair signed translation-residual and translation-RMSE kernels, explicit
output-coverage accounting and binding, and strict persisted calibration-profile
plus separate assessment contracts. The committed fixture is synthetic and
rejected; there is no accepted real sensor or dataset profile. Planned next:
additional framework-neutral evaluator/lifecycle behavior, then—after explicit
approval—one dataset adapter with its actual profile and a shared-backend
feasibility spike. No estimator algorithm,
complete evaluator, numerical backend, model, training loop, dataset files,
approved split, dataset adapter, checkpoint, ONNX graph, TensorRT engine, ROS 2
node, or PX4 bridge exists yet. A candidate-only dataset registry exists, but it
is not data-use approval.

## Technology stack by status

| Layer | Current implementation | Planned or conditional boundary |
|---|---|---|
| Repository/core | Python `>=3.10`, standard library, setuptools, unittest, Git/GitHub, JSON, JSON Schema Draft 2020-12, Ruff | Numerical array/vision library for estimator work is unresolved. |
| Common VIO substrate | Generic causal replay, estimator envelope with explicit declaration/init/reset validation, direct replay-to-session recording, typed camera/IMU records, translation trajectories, raw residual/RMSE, output coverage plus batch and terminal-recorder binding, and strict calibration profile/assessment contracts | Additional geometry/evaluator and lifecycle behavior, actual dataset profiles, and adapters are planned; exact state/policy identifiers, final metric protocols, sensor configuration, conventions, thresholds, and numerical backend remain unresolved. |
| Native reference | Not implemented | A later rights-reviewed classical reference retains its native build/backend/runtime and has no learned-framework or tracker dependency. |
| Internal A/B/C/D system | Not implemented | Shared-backend feasibility precedes visual/inertial/fusion/health work. Exact backend, visual methods, learned component, deduplication, diagnostics, and D action remain unresolved. |
| Conditional learning | Not implemented; no framework is installed as a project dependency | Version 1 no-project-training is proposed in ADR-0004. Framework, model, data, objective, and schedule remain unresolved unless failure-atlas evidence opens one targeted branch. |
| Tracking | Tracker-independent schemas/files only | MLflow is optional and currently absent. |
| GPU execution | Dated A10 implementation-smoke evidence exists | Present state and every later task require fresh inventory and owner confirmation. |
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
├── environments/                          [current: dated A10 inventories]
├── experiments/
│   ├── schemas/                           [current: run/artifact/evidence schemas]
│   └── configs/                           [planned: frozen experiment configs]
├── configs/                               [current: calibration schemas/rejected synthetic fixtures; other configs planned]
├── src/compact_vio/
│   ├── replay.py                          [current]
│   ├── estimator.py                       [current: estimator envelope/interface declaration]
│   ├── execution.py                       [current: causal replay-to-estimator recorder]
│   ├── artifacts/                         [current]
│   ├── copy_audit.py                      [current]
│   ├── preflight.py                       [current]
│   ├── repository_policy.py               [current]
│   ├── contracts/                         [current: sensor payload/calibration-identity runtime records]
│   ├── data/                              [planned at first approved dataset adapter]
│   ├── geometry/                          [current: translation trajectory records]
│   ├── evaluation/                        [current: residual/RMSE, coverage, replay/output binding]
│   ├── backend/                           [planned at shared-backend feasibility spike]
│   ├── baselines/                         [planned at native classical reference]
│   ├── inertial/                          [planned with accepted propagation contract]
│   ├── vision/                            [planned with first selected A/B behavior]
│   ├── fusion/                            [planned with C correlation/deduplication behavior]
│   ├── health/                            [planned with D-monitor/D contract]
│   ├── estimators/                        [planned for tested estimator compositions; estimator.py remains the contract]
│   ├── learning/                          [conditional on post-failure-atlas decision]
│   │   ├── models/                        [conditional: one selected learnable component]
│   │   ├── training/                      [conditional: selected-framework train/checkpoint path]
│   │   └── inference/                     [conditional: frozen-checkpoint adapter]
├── tests/                                 [current; expands one slice at a time]
├── reports/                               [current: output policy/README; reviewed result files future]
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
  truth is a separate evaluation reference and is never estimator input.
- A replay contract that exposes no future samples and reproduces streaming state, warm-up, reset, dropout, and stale-data behavior.
- A framework-neutral estimator boundary. Every selected profile must provide
  the declaration identifiers required by the shared contract; native
  classical adapters consume the project contract directly, while learned
  adapters perform tensor conversion inside their own boundary.
- A frozen evaluator that reports trajectory error, metric scale,
  initialization, coverage, failures, and end-to-end timing.
- For internal A/B/C/D comparisons, one backend/state/init/IMU/factor/numerical/
  output contract and explicit visual-observation provenance. Native external
  references remain separate rather than being mislabeled same-backend controls.
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
but generic payloads are not deep-copied and no persistent trace format exists
yet. This proves only the recorder-observed envelope path: it does not prove
adapter-internal sample use
or reset behavior, define output opportunities, classify missing/failure causes,
or establish scientific run success.

The terminal execution-coverage bridge binds a caller-declared coverage ledger
to that full recorder snapshot. Produced outcomes must identify every output in
every successful batch exactly once. Missing outcomes may identify the failed
event or the unattempted planned suffix, so a surviving prefix cannot silently
be presented as the whole execution. The bridge still does not invent expected
opportunities, reason codes, failure taxonomy, thresholds, completion, or run
success.

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
