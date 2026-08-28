# Implementation plan

Status: Active training-first roadmap

Last reviewed: 2026-08-28

Requirements authority: [Project requirements](requirements/project-requirements.md)

Decision authority: [ADR index](adr/README.md)

Evidence ledger: [Progress](progress.md)

## Planning contract

This roadmap owns milestone order, dependencies, permitted work, prohibited
premature work, and exit evidence. It does not redefine requirements, assign a
dataset role, accept an ADR, or silently select a sensor, edge board, licence,
or flight scope.

The project advances only when a milestone's exit evidence exists. A later
milestone may be explored in a disposable, non-claiming spike only when the
earlier milestone explicitly permits it; a spike cannot be reported as project
evidence.

Local implementation, synthetic fixtures, evaluator work, and bounded CPU tests
may proceed before the durability gate. A future short reproducible GPU check
may proceed only after fresh owner confirmation and must use a pushed revision,
a time/cost bound, and disposable outputs. M2 gates important or extended paid
GPU work and irreplaceable retained artifacts; it is not a global
implementation gate.

An A10 was observed ready on 2026-08-27 and was authorized for that bounded
implementation smoke only. The dated state and authorization do not carry
forward. ADR-0004 authorizes source/local implementation of the training-first
slice; an actual paid-worker run still requires current inventory and a bounded
run record under the infrastructure requirements.

Milestone bullets summarize permitted scope and required outcomes. Where a
milestone links an artifact policy, dataset policy, research protocol, or
experiment lifecycle, that linked record governs the procedure and wins over a
roadmap summary if wording drifts.

## Lean delivery rule

Implementation proceeds in small verifiable slices, not multi-hour planning
phases:

- One slice has one concrete output, such as one interface record, one adapter,
  one metric, one baseline wrapper, or one training control.
- A normal local documentation or implementation slice contains one reviewable
  behavior and one verification boundary. If the work expands beyond that
  boundary, stop coherently, record the exact blocker, and split the remainder
  instead of extending the slice into a broad multi-hour phase.
- Each slice changes only the necessary files, runs focused checks first, and
  updates progress once. The full design is not re-audited unless a decision or
  dependency actually changes.
- Dataset transfers and model training may legitimately run longer than one
  slice. Their preparation, launch, monitoring, result review, and export are
  separate bounded tasks; elapsed GPU runtime is not treated as planning time.
- No broad hyperparameter sweep is the first experiment. Run one configuration,
  inspect its data, causality, loss, and runtime evidence, then authorize the
  next change.

## Accepted scope and execution direction

ADR-0001 and ADR-0002 retain the public non-commercial research lane, causal
metric-scale local-VIO scope, no-loop-closure comparison, and PX4 control
boundary. ADR-0004 now accepts this development critical path:

1. Ingest EuRoC Vicon Room `cam0`, six-axis IMU, official calibration, and
   ground truth through one source-identified adapter.
2. Assign complete source sequences to disjoint train, validation, and held-out
   development-test membership before windowing or fitted preprocessing.
3. Train one compact PyTorch relative-motion model: image-pair CNN, declared
   temporal IMU GRU/Conv1D encoder, gated frame-pair fusion, and
   translation/rotation outputs.
4. Validate the complete data/calibration/sample path, pass a tiny overfit and
   checkpoint-load smoke, then execute one bounded training configuration.
5. Integrate held-out relative predictions into trajectories and report ATE,
   RPE, rotation error, coverage/failures, latency, and memory under recorded
   metric semantics.
6. Treat that output as a development prototype. Publication claims require a
   later confirmatory freeze; deployment and flight readiness require separate
   target and safety evidence.
7. Keep A/B/C/D-monitor/D, a native classical reference, reliability learning,
   uncertainty, compression, ONNX, and target deployment as follow-up work, not
   blockers for the first trained vertical slice.
8. PX4 retains stabilization, failsafes, pilot override, and motor control.

### Development and scientific freezes

- **Development configuration freeze:** before each operation, record the exact
  source units and identities, split membership, preprocessing, model, loss,
  optimizer, seed, schedule, environment, and checkpoint rule. Development may
  revise these values transparently without presenting the held-out development
  set as a final scientific test.
- **Confirmatory-protocol freeze:** before any publishable claim, select an
  untouched run set from already sealed source-group membership and fix metric
  semantics, thresholds, trials, budgets, aggregation, and stopping rules. No
  seen development sequence may be relabeled as untouched confirmation.

### Training-first vertical slice

PyTorch is selected for the learned-development lane; the exact package/CUDA
versions are pinned in its environment. Execute in this order:

1. Record exact EuRoC unit identity, rights, acquisition location, modalities,
   official calibration, and source-sequence split manifest.
2. Implement and test parsing, calibration validation, causal image-pair/IMU
   window construction, relative-pose labels, and train-only normalization.
3. Implement the compact model, losses, trainer, checkpoint save/load, and
   deterministic CPU smoke.
4. Run a tiny overfit check. Fix data/geometry defects before spending on a
   full run; do not tune against held-out development test.
5. Run one bounded training configuration, export the selected checkpoint, and
   execute held-out inference/evaluation with failed and partial runs visible.
6. Decide later work from measured evidence. Do not silently expand the first
   run into a broad sweep, A/B/C/D study, or deployment claim.

A tracking service may mirror metrics but is never the authority. Exact layer
sizes, parameter count, rotation representation, optimizer, loss weights,
resolution, batch size, and duration belong in the versioned development
configuration and must not be invented in documentation.

## Milestone overview

| ID | Milestone | Status at this review | Dependency that controls status |
|---|---|---|---|
| M0 | Reproducible repository foundation | Complete | Foundation commit and CI evidence |
| M1 | Planning traceability and static durability preflight | Complete | M0 |
| M2 | Artifact durability for important GPU work | Blocked | Required before long or irreplaceable paid runs |
| M3 | Scientific question and estimator contract | In progress | M1; ADR-0004 training-first direction accepted, runtime details remain |
| M4 | Replay sensor, time, frame, and calibration contract | Complete | Causal replay, typed sensor records, and calibration profile/assessment fixtures |
| M5 | Reproducible execution environments | In progress | Local path active; worker tasks require fresh inventory and authorization |
| M6 | EuRoC development ingestion and split | In progress | ADR-0004, sufficient M3/M4 detail, exact unit identity/rights/acquisition record |
| M7 | Common causal replay and evaluator | In progress | Synthetic replay unblocked; real-data exit depends on M6 |
| M8 | Compact model and bounded training | In progress | M5–M7 data/sample path and accepted ADR-0004 |
| M9 | Held-out prototype inference and evaluation | Blocked | Restorable M8 checkpoint and complete M7 metric semantics |
| M10 | Later baselines, reliability ablations, and failure atlas | Conditional | Reproducible M9 prototype evidence and a separately frozen ablation protocol |
| M11 | Confirmatory final-test execution and scientific selection | Blocked | Reproducible candidate set, sealed untouched membership, and frozen confirmatory protocol |
| M12 | Conditional export, exact-target benchmark, and deployable selection | Blocked | M11; authorized provisional sensor/target choices |
| M13 | Conditional ROS 2/PX4 and staged safety validation | Blocked | M12; accepted integration scope |
| M14 | Release evidence and conditional final worker disposition | Blocked | All applicable prior milestones |

## M0 — Reproducible repository foundation

Status: Complete.

Dependencies: none.

Permitted work completed:

- Versioned requirements, architecture, ADR, dataset, artifact, and experiment
  contracts.
- Strict run/bundle schemas, safe artifact inventory/verification, repository
  policy, package build, tests, and SHA-pinned CI actions.
- A clean GitHub checkout and standard-library test run on the historical A10
  worker that was later terminated.

Exit evidence:

- Foundation commit `ea07ccbc7ee1ab7ba870473be63625259b4b64fc`.
- Successful GitHub Actions run recorded in [progress](progress.md).
- A10 inventory in
  [environments/a10/inventory-2026-08-26.md](../environments/a10/inventory-2026-08-26.md).

## M1 — Planning traceability and static durability preflight

Status: Complete.

Dependencies: M0.

Permitted work:

- Add this roadmap, the non-normative requirements index, and the dated progress
  ledger.
- Enforce basic requirement/ADR/milestone identifier and reference consistency in
  standard-library tests; these syntax checks do not replace human authority
  review.
- Add an optional read-only preflight for filesystem-backed candidates. It
  requires explicit capacity/reserve, non-nested paths, distinct client-visible
  filesystem identifiers, and a caller-supplied failure-domain record while
  stating that none of those observations proves independent failure domains.

Prohibited claims/actions:

- Do not claim artifact durability from free-space inspection or path existence.
- Do not write a probe to an unspecified storage location.
- Do not download datasets, train models, or terminate the worker.

Exit evidence:

- Local tests, repository policy, installed CLI smoke, schema validation, and CI
  all pass.
- `compact-vio-preflight` reports blockers and limitations and always states that
  satisfied static checks do not verify independence, outside-worker storage,
  writes, or restoration and do not complete M2.

## M2 — Artifact durability for important GPU work

Status: Blocked.

Dependencies: M1; `R-INFRA-*`. Accepted
[ADR-0001](adr/0001-project-and-release-scope.md) and
[ADR-0005](adr/0005-artifact-storage.md) are exit evidence, not entry
dependencies.

Required before long training, large sweeps, or any paid run expected to produce
irreplaceable retained results:

- Record the immutable Git revision, approved dataset subset, expected runtime,
  cost limit, review time, and export destination.
- Confirm enough space for selected retained artifacts and an independent
  recovery copy outside the worker.
- Run one representative export, checksum, restore-to-a-new-location, and
  load/open test before relying on the worker for irreplaceable results.
- Keep source, configuration, manifests, and small results in GitHub. Treat any
  future temporary GPU-worker disk as disposable scratch space.
- Review the exact licence of each dataset or third-party implementation before
  use in the non-commercial research lane.

The governance storage-plan and worker-authorization records are optional audit
support. The post-export evidence sidecar remains the required compact M2
evidence record under the artifact policy. None is the research architecture or
blocks local code, synthetic fixtures, evaluator work, bounded CPU tests, or a
future short GPU smoke/reproduction task whose outputs are disposable and
reproducible from the pushed revision.

Prohibited work:

- No important or long-running GPU experiment before the restore drill passes.
- No claim that GitHub, a GitHub Actions artifact, or two paths on one filesystem
  are independent backups.
- No claim that a static preflight or checksum comparison alone proves a
  successful restore.
- No destructive `brev delete` without a separate explicit approval and the
  applicable preservation/teardown audit.

Exit evidence:

- Accepted research-only project scope in ADR-0001. The exact licence remains a
  later external-reuse/release decision.
- Storage/export approach recorded in ADR-0005.
- Representative restore report with two verified copies outside the temporary
  worker and a successful load/open check.

### Cost-control teardown exception

M14 is the final project teardown, not the only permitted time to release paid
capacity. At any milestone, the project owner may explicitly authorize a
cost-saving lifecycle action after a fresh state check, confirmation that the
remote commit is reachable, confirmation that the worker holds no unique source
or configuration, export/verification of every artifact that must be retained
at that point, and a record of what will be destroyed.

The action must match the lifecycle capability re-observed at that time. A
stoppable instance may be stopped when continued disk retention is intentional;
compute billing stops, but storage charges can continue and future restart
capacity is not guaranteed. A non-stoppable instance must be terminated to halt
charges and loses its disk. A shell disconnect or reboot is not cost control.
Destructive deletion or termination always requires explicit approval.

## M3 — Scientific question and estimator contract

Status: In progress.

Dependencies: M1 and the accepted local-VIO/training-first directions in
[ADR-0002](adr/0002-estimator-scope.md) and
[ADR-0004](adr/0004-primary-research-contribution.md); `R-RI-*`, `R-EST-*`.

Required decisions/evidence:

- Treat the ADR-0004 development question as fixed: can the declared compact
  learned model complete a reproducible EuRoC data-to-checkpoint-to-held-out-
  trajectory path? Do not turn that prototype question into a superiority claim.
- Later freeze exact metrics, thresholds, trials/seeds, compute budget,
  aggregation, stopping rule, and rejection rule before final testing.
- Freeze state variables, transform direction, frames, metric-scale mechanism,
  initialization, reset, recurrence warm-up, output timestamp, output rate, and
  latency definition. Local VIO and no loop closure are already fixed.
- Define causality: for each output, list exactly which camera and IMU samples
  are available and when the estimate becomes available.
- Separate scientific-winner criteria from deployable-winner criteria.

Implemented interface-control slice (not M3 exit evidence by itself):

- A standard-library declaration record now requires explicit identifiers for
  state schema/variables, scale, initialization/reset/recurrence, output time
  and schedule, causality, latency, staleness, and input-gap policies without
  choosing their values.
- Declared estimator sessions check exact interface identity, explicit
  initialization state, the profile-declared valid/initialized relationship,
  and the profile-declared post-reset state before adapter delivery. These are
  wrapper-observable checks, not proof of adapter-internal reset behavior. The
  prior undeclared envelope is compatibility-only.
- Concrete declaration values, sample-level lineage, endpoint semantics, and
  evaluator policies remain unresolved; M3 stays in progress even though
  ADR-0004 is accepted.

Prohibited work:

- No final architecture selection from paper-reported metrics on other devices.
- No combined primary claim spanning compactness, gating, robustness, and
  uncertainty.
- No primary metric-scale result with Sim(3) scale correction.

Exit evidence:

- Accepted ADR-0002 and ADR-0004.
- Frozen development-scope protocol revision and estimator interface-control
  draft. Any claim-supporting confirmatory protocol remains a later freeze.
- Claim-to-evidence and negative-control matrix.

M6–M11 produce the ADRs' follow-up empirical evidence. Material contradiction
reopens or supersedes the affected ADR; weak prototype results are valid
evidence and do not authorize split leakage or an inflated claim.

## M4 — Replay sensor, time, frame, and calibration contract

Status: Complete.

Dependencies: M1, the fixed local-VIO direction, and `R-DATA-*`, `R-EST-*`, and
`R-CAL-*`. Synthetic timing/causality work may proceed while M3 interface details
are completed.

Physical-sensor selection in [ADR-0003](adr/0003-sensor-contract.md) remains
deferred until the deployment and integration milestones require it.

Completed contract evidence:

- Implement a deterministic event replay boundary that distinguishes sensor
  measurement time from estimator availability time, uses one declared clock,
  and preserves invalid/reset events.
- Define a modality-neutral canonical schema for exposure time, IMU intervals,
  clock mapping/offset sign, frames, axes, units, gravity, validity, provenance,
  and calibration versioning.
- Require each replayed dataset profile to record its actual mono/stereo,
  shutter, resolution/rates, intrinsics/distortion, camera–IMU transform,
  temporal calibration, IMU stochastic parameters, and available diagnostics.
- Define the validation rules that each approved profile must satisfy before its
  records enter the common evaluator.
- Keep immutable profile facts separate from review, revalidation, and
  invalidation decisions; bind them by exact identity, revision, raw-file hash,
  validity fingerprint, and threshold scope.

Prohibited work:

- Do not select the future physical camera/IMU merely to permit public-dataset
  research.
- Do not treat online calibration as a substitute for a validated replay or
  physical sensor profile.
- Do not copy a universal reprojection/timing threshold from one example sensor.

Exit evidence:

- Versioned calibration schema/profile template with synthetic/golden contract
  fixtures.
- Timestamp/frame/calibration negative tests pass without acquiring a candidate
  dataset.

This milestone does not approve a dataset or physical sensor. M6 must create
and review an actual profile for the selected representative sequence before
its records enter the evaluator.

## M5 — Reproducible execution environments

Status: In progress.

Current durable execution state: local and GitHub. Dated A10
implementation-smoke evidence exists, but current worker state and authority are
not inferred from it. ADR-0004 authorizes the training-first implementation;
each paid-worker run still requires current inventory and a bounded run record.

Dependencies: M1 for the local CPU environment. Important or extended future
paid GPU work additionally depends on M2; estimator-specific environments depend
on M3 and M4.

Permitted work:

- Maintain a framework-neutral core environment for records, replay, geometry,
  evaluation, and repository tooling.
- Maintain an isolated native environment for each selected classical baseline;
  no learned-training framework is a dependency of the common core or classical
  lane.
- Add a separate PyTorch learned-training environment for the accepted ADR-0004
  slice. Pin exact framework/CUDA bindings to the execution environment; add
  CUDA only for a currently inventoried worker that benefits from it.
- Keep MLflow as an optional extra. A valid run must work with tracking disabled.
- Maintain separate local-development, future GPU-execution, and future target
  environment definitions.
- Pin base image digest, OS/architecture, Python/C++ dependencies, compiler,
  CUDA/driver/framework/runtime versions, Git SHA, and hardware inventory.
- Rebuild from a clean checkout and run deterministic CPU/GPU smoke fixtures.

Prohibited work:

- Do not use an unrecorded global worker environment for claim-supporting runs.
- Do not treat a training-worker stack as the future Jetson/edge stack.

Exit evidence:

- Current exit target: rebuild instructions and dependency locks reproduce the
  declared core smoke output from a clean local checkout.
- When an optional future GPU worker is provisioned, append separate inventory
  and CUDA smoke evidence; historical A10 evidence does not satisfy that future
  check.

## M6 — EuRoC development ingestion and split

Status: In progress.

Dependencies: accepted ADR-0004, sufficient M3/M4 interface detail for the
adapter, `R-DATA-*`, and exact-unit rights/acquisition evidence. Full or
important paid-worker acquisition additionally depends on M2/M5.

Required work:

Procedure authority: [Dataset governance policy](../governance/datasets/policy.md)
and [candidate registry](../governance/datasets/registry.yaml).

- For each used EuRoC Vicon Room unit, record official rights, exact
  source/version, modalities, sensors, calibration, timestamps, ground-truth
  coverage, byte estimate, acquisition location, and checksum strategy before
  training uses it.
- Record the exact release/unit, `cam0`/IMU/ground-truth modalities, role, split
  membership, and acquisition location. Dataset-file rights evidence remains a
  distinct record from the architectural selection.
- Assign a declared role and source-group ID; freeze train/validation/final-test
  membership before windows, normalization, corruption, or augmentation.
- Acquire one rights-checked representative sequence first and validate frames,
  units, timing, calibration, missing data, ground-truth interpolation, and
  causal sample construction. Expand only to the source-disjoint train,
  validation, and held-out development-test units recorded in the split
  manifest and fitting the applicable capacity/retention budget.

Prohibited work:

- Dataset repository code licenses must not be treated as dataset-file rights.
- An EuRoC source sequence must not silently serve more than one split role.

Exit evidence:

- Separate dataset-file rights evidence, acquisition manifests, immutable
  source-sequence split manifest, validated representative replay profile,
  representative-ingestion report, and timestamp/frame/calibration negative-
  test report on the acquired sequence.

## M7 — Common causal replay and evaluator

Status: In progress.

Dependencies: M3/M4 contracts and `R-RI-*`, `R-DATA-*`, `R-EST-*`,
`R-EVAL-*`. Synthetic replay and geometry fixtures may proceed now; real-data
exit evidence depends on representative M6 data.

Required work:

- Implement canonical image/IMU/calibration records plus a separate evaluation-
  reference record and conversion adapters that retain source provenance.
- Implement online-equivalent causal replay, warm-up/reset/dropout/stale-state
  behavior, and explicit output availability time.
- Keep canonical records, estimator outputs, replay, and evaluator
  framework-neutral. A classical adapter must run without the learned-training
  framework installed; a learned adapter performs framework conversion
  internally.
- Implement trajectory geometry and metric-scale checks, per-sequence ATE/RPE,
  initialization, completion, coverage, failures, resets, scale, and runtime
  distributions.
- Add frame, unit, timestamp, scale, split-leakage, future-leakage, and partial-
  trajectory negative controls.

Implemented evaluator slice (not M7 exit evidence by itself):

- Immutable Cartesian translation trajectories now require explicit reference
  and tracked frames, transform direction, unit, clock, timestamp semantics,
  sequence/segment scope, ordered sample identity, and time.
- One stable raw translation RMSE primitive requires exact pre-paired samples
  and a no-default policy explicitly declaring exact association, no
  interpolation, no alignment, and no scale correction.
- A raw signed translation-residual series reuses that policy and retains
  estimated-minus-reference Cartesian components for every exact pair. It is an
  in-memory diagnostic record only.
- Synthetic controls prove offsets, rotations, and scale errors are retained;
  empty/partial or convention-mismatched trajectories fail instead of being
  silently paired or reported as survivors.
- An explicit output-coverage ledger now partitions every caller-declared
  expected opportunity into missing, invalid, or valid output state; records
  reference availability and explicit usability separately; and requires
  reason codes for every non-usable item.
- The coverage primitive supplies exact counts and derived fractions without inferring
  an output schedule, timestamp association, pass/fail threshold, completion,
  reset, tracking loss, or estimator-failure classification.
- An exact binding layer now links every declared opportunity to its triggering
  replay event and, for produced outcomes, the precise ordinal in that event's
  retained estimator-output tuple. It rejects missing/extra/reordered slots,
  reused or unbound envelopes, wrong event identity, output-validity mismatch,
  mixed clocks, and output availability before the triggering event.
- Binding uses no timestamp proximity and does not assume one output per event.
- A direct execution recorder now constructs and privately retains one fresh,
  clock-matched replay/session pair. It releases one event at a time, retains no
  partially validated batch, keeps the first failed event separately, and does
  not consume the later replay suffix after failure. Structurally frozen
  in-memory snapshots retain the full event plan, causal watermark, execution
  counts, reset generation, and whether session delivery/reset transition
  occurred for the failed event.
- The recorder now requires and retains an immutable lifecycle-policy
  declaration. Its five caller-supplied opaque IDs name only the recorder's
  existing replay-exhaustion, processing-exception, process-control-exception,
  and unattempted-suffix semantics; no taxonomy, threshold, output schedule, or
  scientific-success value is selected.
- The recorder does not define expected opportunities, infer missing outputs or
  failure causes, prove adapter-internal reset/sample use, or establish
  scientific run success. Persistent full-run traces, accepted meanings for the
  declared lifecycle-policy IDs, complete failure classification, and scientific
  acceptance evidence remain open; generic payload objects are not deep-copied
  by the in-memory snapshot.
- A terminal execution-coverage bridge now binds caller-declared outcomes to the
  complete recorder plan. Every successfully recorded output ordinal is bound
  exactly once; explicit missing slots may reference the failed event and
  unattempted suffix. It rejects active snapshots and does not create expected
  opportunities, reasons, failure labels, thresholds, or a success decision.
- A terminal-only, payload-omitted recorder-envelope encoder now projects the
  complete planned-event metadata, successful output envelopes,
  lifecycle-policy declaration, counts, and first-failure metadata into
  deterministic JSON governed by a strict structural schema. It has no
  deserializer or filesystem writer and derives no field by reading,
  representing, typing, or hashing payloads.
- The recorder envelope is not a full execution trace. The encoder adds no
  dedicated representation, type, hash, or cryptographic commitment for omitted
  payloads, so the envelope alone cannot prove their identity. It also does not
  prove replayability, dataset provenance, adapter lineage, coverage, lifecycle
  success, or scientific acceptance. Payload-complete trace/run-manifest
  integration remains open.
- Schema validity alone does not authenticate recorder origin or prove all
  cross-array counts/references in arbitrary external JSON. A trusted envelope
  must be produced by the encoder from a validated terminal snapshot.
- These kernels are not aligned ATE, RPE, metric-scale evidence, coverage or
  completion evidence, frame-correctness proof, run-level failure accounting,
  or a complete evaluator. M7 remains in progress.

Prohibited work:

- No estimator-specific evaluator or hidden candidate-specific preprocessing.
- No survivor-only aggregate without failure and coverage reporting.

Exit evidence:

- All adapters pass the same golden replay/geometry fixtures.
- Deliberately corrupted controls fail for the expected reason.

## M8 — Compact model and bounded training

Status: In progress.

Dependencies: M5 environment, M6 source-identified split/sample path, M7 metric
semantics needed for validation selection, and accepted ADR-0004.

Required work:

- Implement a compact image-pair CNN, a declared GRU or Conv1D IMU encoder,
  zero-initialized gated frame-pair fusion, and relative translation/rotation
  heads in PyTorch.
- Resolve input shapes, causal IMU-window boundaries, rotation representation,
  normalization provenance, objective terms, optimizer, seed, schedule, and
  checkpoint-selection rule in one versioned development configuration.
- Add tensor-shape, finite-output, causal-window, geometry-sign, gradient, and
  checkpoint round-trip tests.
- Inspect representative samples and pass a tiny overfit/forward/backward/
  save-load/inference smoke before a longer run.
- Run one bounded configuration, retaining history, failures, environment,
  resolved configuration, and selected checkpoint identity outside normal Git
  history.

Prohibited work:

- No ground truth as an inference feature, no source-sequence leakage, and no
  fitted preprocessing from validation or held-out development test.
- No broad sweep before one complete configuration is inspected end to end.
- No claim that smoke overfit or training loss is held-out VIO quality.

Exit evidence:

- Focused model/training tests and a passing tiny overfit/checkpoint smoke.
- One restorable `checkpoint.pt` with exact configuration, environment, split,
  seed, selection rule, history, checksum, and failure record.

## M9 — Held-out prototype inference and evaluation

Status: Blocked.

Dependencies: M6 held-out development membership, M7 evaluator/lifecycle
semantics, and a restorable M8 checkpoint.

Required work:

- Load the selected checkpoint without optimizer/training state and run causal
  inference over every held-out development sequence.
- Integrate relative translation/rotation predictions using the declared frame,
  transform, unit, timestamp, initialization, and reset conventions.
- Report per-sequence and aggregate ATE, RPE, rotation error, output coverage,
  failures, latency, and memory. Preserve partial and non-initializing runs.
- Retain predicted/reference trajectories, resolved evaluation configuration,
  checkpoint identity, environment, and checksums in a restorable result bundle.

Prohibited work:

- No hyperparameter, preprocessing, checkpoint, association, or alignment tuning
  after inspecting held-out development-test outcomes.
- No publishable superiority, onboard-performance, deployment, or flight claim
  from this development evaluation.

Exit evidence:

- Complete held-out development run bundle and metric/failure report.
- Explicit prototype limitations and an evidence-based next-work decision.

## M10 — Later baselines, reliability ablations, and failure atlas

Status: Conditional.

Dependencies: reproducible M9 prototype evidence and a separately frozen
development-ablation protocol without confirmatory-test access.

Permitted follow-up work:

- Reproduce one rights-compatible native classical reference in its native
  runtime and report it separately.
- Implement A, B, C, D-monitor, and D only after freezing the shared-backend
  fairness fields and the independent mechanism under test.
- Build a failure atlas covering declared nominal, visual, and timing/IMU
  conditions while preserving coverage, failures, recovery, runtime, and
  negative results.
- Open further fine-tuning, synthetic pretraining, learned reliability, or
  uncertainty only as separately declared ablations with their own data and
  selection controls.

Prohibited work:

- Do not retrofit A/B/C/D labels onto the Version 1 learned prototype.
- Do not use confirmatory membership to choose fault severity, thresholds,
  training data, model configuration, or the primary reliability action.
- Do not label a health score as covariance or feed it to PX4.

Exit evidence when this milestone is invoked:

- Complete baseline/ablation/failure bundles and mechanism-isolation report.
- A frozen candidate/configuration set ready for an optional confirmatory
  protocol.

## M11 — Confirmatory final-test execution and scientific selection

Status: Blocked.

Dependencies: complete M9 prototype evidence and any applicable M10 work, a
frozen candidate set, source groups assigned to sealed final-test membership
before any use, and an owner-approved confirmatory protocol.

Required work:

- Freeze the exact confirmatory run set only from already sealed final-test
  membership, together with metric semantics, thresholds, trials, budgets,
  aggregation, stopping rules, and—only when M10 reliability work is part of the
  claim—the primary intervention. Never reassign a seen development, discovery,
  or stress group to final test.
- Execute the complete sealed final-test matrix for every frozen candidate and
  preserve partial, failed, reset, and non-initializing runs.
- Select the scientific winner, if supported, and a deployment shortlist across
  accuracy, scale, failure/coverage, robustness, uncertainty when applicable,
  runtime, memory, rights, reproducibility, and target relevance.
- Preserve the Pareto frontier and rejected alternatives; do not collapse all
  dimensions into an unreviewed scalar score.
- Freeze the scientific artifact and the shortlist's checkpoints/native builds,
  interfaces, data/model cards, and artifact hashes. Do not name a final
  deployable winner before exact-target evidence.

Exit evidence:

- Immutable confirmatory-protocol and sealed-run-set identities, complete
  final-test run bundles, and an accepted scientific-selection/deployment-
  shortlist record with unchanged thresholds and independently restorable
  evidence bundles.

## M12 — Conditional export, exact-target benchmark, and deployable selection

Status: Blocked.

Dependencies: M11; project-owner authorization to evaluate provisional physical
sensor and target choices; `R-DEP-*`. Accepted
[ADR-0003](adr/0003-sensor-contract.md) and
[ADR-0006](adr/0006-deployment-scope.md) are exit evidence, not entry
dependencies.

Required work:

- If a neural component exists, perform early operator/parser feasibility, then
  framework-to-portable-runtime step/state and full-trajectory parity.
- Select the exact sensor/target only after mission, power, mass, thermal,
  memory, interface, synchronization, update-rate, latency, and budget envelopes
  are recorded.
- Characterize the physical sensor candidate's synchronization, calibration
  repeatability/residuals, timing sensitivity, and gap from the research data.
- Pin the candidate OS/runtime/integration compatibility matrix and, when
  integration or physical testing is proposed, record the interface/fault-test
  plan, named safety authority, environment, and preconditions.
- Build the selected native/runtime package on the exact pinned target stack.
  Build a TensorRT engine only if the winner has a neural component and
  ADR-0006 selects TensorRT; a training-worker-built engine is not target
  evidence.
- Measure sustained batch-one sensor-to-output p50/p95/p99 latency, deadline
  misses, memory, power, temperature, clocks, and throttling, then rerun complete
  trajectory/failure evaluation for every precision.
- Revalidate uncertainty/health calibration and failure behavior on the exact
  target for every deployed precision when those outputs exist.
- Select the deployable winner only from candidates that pass the exact-target
  hard constraints. If none pass, record failure, keep final-test data sealed,
  revise scope/protocol explicitly, and return to the earliest affected
  milestone rather than lowering thresholds after inspection.

Exit evidence:

- Accepted ADR-0003 and ADR-0006, portable-model/native-build provenance,
  target-built artifact, parity report, sustained exact-target benchmark meeting
  frozen thresholds, and accepted deployable-selection record—or an explicit
  no-winner decision and revision path.

## M13 — Conditional ROS 2/PX4 and staged safety validation

Status: Blocked.

Dependencies: M12; accepted integration/flight scope in ADR-0006;
`R-SAFE-*`.

Required sequence:

- Pin PX4, matching message definitions, ROS 2, OS, transport, and simulator.
- Validate ENU/NED and FLU/FRD transforms, sample timestamp and clock sync,
  capture-to-EKF delay, lever arm, covariance/noise source, resets, staleness,
  unknown fields, and actual fused measurements.
- Progress replay → SITL → HIL → propeller-off bench → contained ground-truth
  test only after each prior stage passes.
- Inject estimator loss, delay, timestamp jumps, frame errors, bad covariance,
  reset, sensor dropout, process death, and communication loss; verify the
  configured position-loss/fallback behavior and pilot override.

Prohibited work:

- VIO never commands motors directly or replaces flight-controller stabilization.
- Offline benchmark success never authorizes physical flight.

Exit evidence:

- Release-pinned interface-control document, SITL/HIL reports, hazard review,
  calibration evidence, rollback path, explicit physical-test authority, and
  ADR-0003/ADR-0006 follow-up evidence. Material contradiction reopens or
  supersedes the affected ADR before the next integration stage.

## M14 — Release evidence and conditional final worker disposition

Status: Blocked.

Dependencies: every milestone applicable to the accepted scope.

There is no worker to dispose of at this review. The lifecycle branch below
applies only if a future paid worker exists at release time.

Required work before release:

- Revalidate code/model/data/dependency rights and separate incompatible lanes.
- Restore release and reproducibility-critical bundles from their recorded
  locations; verify manifests, hashes, loadability, reports, and provenance.
- Publish only approved code, metadata, documentation, and intentionally reviewed
  binary channels.

Required work before any final future-worker lifecycle action:

- Confirm the exact source commit is reachable from GitHub and the worker has no
  unique source/configuration.
- Verify primary and backup artifact copies and the representative restore.
- Inventory disposable worker data and re-observe lifecycle capability.
- If retained stopped storage is intentional, record that choice, persistence
  scope, residual storage cost, restart/capacity risk, next review time, and
  owner; then confirm stopped state and absence of compute billing.
- If zero-charge final teardown is intended, record deletion intent, obtain
  explicit destructive-action approval, terminate/delete, then independently
  confirm inactive and billing state.

Exit evidence:

- Release manifest and rights review, plus one reviewed lifecycle branch:
  either a stop record with residual-cost/risk/review ownership, or a deletion
  record with post-delete restore check and confirmed inactive/zero-charge state.

## Immediate execution queue

Execute these as separate small slices; do not combine them into one long phase:

1. Record exact EuRoC Vicon Room unit identities, rights, modalities,
   acquisition location, sizes/checksums, and sequence-disjoint split roles.
2. Implement the smallest `cam0`/IMU/ground-truth adapter and validate official
   calibration, timestamps, frames, units, continuity, and relative-pose label
   construction with focused negative tests.
3. Implement the compact PyTorch visual encoder, temporal IMU encoder, gated fusion,
   relative translation/rotation heads, losses, trainer, and checkpoint loader
   with focused tensor/geometry/gradient tests.
4. Run sample inspection and one tiny overfit/forward-backward/save-load smoke.
5. From a pushed immutable revision and current bounded worker record, run one
   training configuration; monitor loss/runtime and export the selected
   checkpoint plus tracker-independent run evidence.
6. Execute held-out development inference and trajectory integration, then
   report ATE, RPE, rotation error, coverage/failures, latency, and memory.
7. Verify the retained checkpoint/result bundle and update the progress ledger
   with only observed results.
8. Based on prototype evidence, separately decide whether a native classical
   reference or A/B/C/D reliability/failure-atlas work is worth running.
9. Freeze and execute a confirmatory protocol only for a publishable claim.
10. Export ONNX or begin target/ROS/PX4 work only after its separate evidence
    and deployment decisions pass.

The dataset family/modalities, PyTorch framework, and model family are selected
by ADR-0004. Exact source units/hashes, split roles, preprocessing, layer sizes,
rotation representation, hyperparameters, metric policies, artifact stores,
and target hardware remain versioned configuration or later-decision values.
No task in this queue assumes current Brev/A10 state. Worker deletion remains a
separate destructive action requiring explicit approval.
