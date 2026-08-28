# System architecture

Status: Training-first EuRoC development slice accepted; implementation in progress
Last reviewed: 2026-08-28

## Purpose

The architecture separates durable project state from disposable computation
and the common scientific substrate from estimator-specific implementations.
The accepted scope is causal metric-scale local VIO. ADR-0004 selects a compact
PyTorch training-first vertical slice over EuRoC Vicon Room `cam0`, IMU, and
ground truth. A/B/C/D reliability experiments are later research ablations, not
the implementation critical path. Mapping, loop closure, flight control, and
target deployment are outside the current core.

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

## Model and training boundary

The learned estimator consumes two temporally ordered `cam0` images and the
causally corresponding IMU window. A compact CNN encodes visual change. A
declared GRU or Conv1D implementation encodes the IMU window. Version 1 uses a
zero-initialized gated fusion cell per supervised frame pair; it does not expose
an untrained cross-frame recurrent state. The head predicts relative translation
and a declared relative-rotation representation. Exact shapes, normalization, rotation representation, loss
weights, optimizer, and schedule are resolved in versioned development
configuration and tested before a run; the architecture does not invent their
values.

Training starts with sample inspection and a tiny overfit/forward-backward/
save-load smoke, then one bounded configuration. Training membership alone
supplies fitted statistics and gradients. Validation serves only its declared
selection role, and held-out development test records never tune the model.
Every retained run remains reconstructable from versioned configuration,
manifests, trajectories, metrics, environment records, and the exact checkpoint.
Tracking services are optional views, never the authority. Checkpoints and large
histories stay out of Git.

The first checkpoint and held-out report establish a development prototype, not
a publishable or flight-ready claim. A native classical reference and the
earlier A/B/C/D-monitor/D reliability design remain later research work with
their own fairness and confirmation protocols.

## Current implementation boundary

Implemented now: repository/evidence tooling, the generic causal event-release
primitive, a framework-neutral estimator envelope with a required declaration
shape and initialization/reset validation, a direct causal execution recorder,
typed camera/IMU payload records, immutable translation-trajectory records, raw
exact-pair signed translation-residual and translation-RMSE kernels, explicit
output-coverage accounting and binding, a deterministic payload-omitted terminal
recorder-envelope projection, and strict persisted calibration-profile plus
separate assessment contracts. The committed fixture is synthetic and rejected.
The accepted next implementation boundary is the smallest real EuRoC adapter,
split manifest, learned model, training smoke, checkpoint path, and held-out
evaluation path. Until their execution evidence is recorded, the repository
makes no trained-model or real-data result claim. ONNX, TensorRT, ROS 2, PX4,
and flight integration remain outside this slice.

## Technology stack by status

| Layer | Current implementation | Planned or conditional boundary |
|---|---|---|
| Repository/core | Python `>=3.10`, standard library, setuptools, unittest, Git/GitHub, JSON, JSON Schema Draft 2020-12, Ruff | Estimator-specific numeric/image packages must be pinned in the learned environment. |
| Common VIO substrate | Generic causal replay, estimator envelope with explicit declaration/init/reset validation, direct replay-to-session recording, payload-omitted terminal envelope encoding, typed camera/IMU records, translation trajectories, raw residual/RMSE, output coverage plus batch and terminal-recorder binding, and strict calibration profile/assessment contracts | Payload-complete traces, additional geometry/evaluator and lifecycle behavior, actual dataset profiles, and adapters are planned; exact state/policy identifiers, final metric protocols, sensor configuration, conventions, thresholds, and numerical backend remain unresolved. |
| Development data | EuRoC Vicon Room family, monocular `cam0`, six-axis IMU, official calibration, and ground truth selected by ADR-0004 | Exact source units, identities, sizes, hashes, and sequence-level split memberships belong in acquisition/split manifests. |
| Learned estimator | PyTorch selected by ADR-0004; implementation evidence pending | Compact image-pair CNN, temporal IMU GRU, zero-initialized gated frame-pair fusion, and relative translation/rotation head. Exact numerical choices belong in versioned configuration. |
| Native reference and A/B/C/D | Not on the Version 1 critical path | Later rights-reviewed research ablations retain their native/fairness boundaries and cannot be inferred from prototype results. |
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
│   ├── schemas/                           [current: run/artifact/evidence/recorder-envelope schemas]
│   └── configs/                           [planned: frozen experiment configs]
├── configs/                               [current: calibration schemas/rejected synthetic fixtures; other configs planned]
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
│   ├── data/                              [planned: EuRoC adapter, calibration and split loading]
│   ├── geometry/                          [current: translation trajectory records]
│   ├── evaluation/                        [current: residual/RMSE, coverage, replay/output binding]
│   ├── learning/                          [planned by accepted ADR-0004]
│   │   ├── models/                        [planned: compact visual/IMU/fusion model]
│   │   ├── training/                      [planned: train/checkpoint path]
│   │   └── inference/                     [planned: checkpoint and trajectory path]
│   ├── backend/                           [later: classical/shared-backend research]
│   ├── baselines/                         [later: native classical reference]
│   ├── inertial/                          [later: modular ablation substrate]
│   ├── vision/                            [later: A/B visual channels]
│   ├── fusion/                            [later: C fusion policy]
│   ├── health/                            [later: D-monitor/D]
│   ├── estimators/                        [later tested compositions; estimator.py remains the contract]
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
