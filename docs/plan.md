# Implementation plan

Status: Active roadmap; decision-dependent milestones blocked

Last reviewed: 2026-08-27

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
forward; dataset work, training, and every later worker task require fresh
inventory and project-owner confirmation.

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

## Accepted scope and proposed research direction

ADR-0001 and ADR-0002 record the accepted public non-commercial research lane,
causal metric-scale local-VIO scope, no-loop-closure comparison, and PX4 control
boundary. ADR-0004 is now a review-ready proposal, not an accepted claim:

1. Organize one modular estimator around physical IMU propagation,
   complementary visual evidence, one shared backend, and explicit health.
2. Use internal A/B/C/D-monitor/D configurations to isolate visual-channel and
   deterministic reliability effects. Hold backend state, initialization, IMU
   path, factors, robust loss, numerics, output schedule, inputs, preprocessing,
   resource/measurement budget, and evaluator fixed.
3. Keep one rights-compatible native classical implementation as an external
   reference in its own backend/runtime, reported separately.
4. Make D versus C the proposed primary comparison and D-monitor the monitoring-
   overhead control. The owner must still accept or reject that proposal.
5. Defer direct end-to-end VIO to optional external work. Version 1 no-project-
   training is proposed; frozen learned weights require rights/provenance review.
6. Open targeted training only after a discovery failure atlas isolates a
   declared plausibly learnable deficit and a new decision approves the data,
   component, framework, objective, selection rule, and budget.
7. Keep ground truth separate from causal replay/estimator input, online
   reliability logic, and final-test tuning. Version 1 uses it only for
   evaluation; a later approved supervised branch may use training-membership
   labels only.
8. Keep uncertainty/covariance, compute gating, compression, and deployment as
   separate conditional questions rather than co-primary claims.
9. PX4 retains stabilization, failsafes, pilot override, and motor control.
10. Do not select mono/stereo, dataset, backend, visual method, learned model,
    reliability action/threshold, framework, or target from convenience.

### Two freezes

- **Research-scope freeze:** accept one contribution, comparator, endpoint
  family, target phenomenon/population, independent experimental unit, and
  fairness contract. This is ADR-0004 work.
- **Confirmatory-protocol freeze:** after representative ingestion, evaluator,
  backend feasibility, and discovery evidence, select the exact confirmatory
  run set only from source groups already assigned to sealed final-test
  membership before use; then fix numerical metrics/thresholds, trials, budgets,
  aggregation, stopping rules, and D action before final-test access.

### Conditional training path

There is no scheduled model-training phase in Version 1 and no selected
framework. If failure-atlas evidence later opens one targeted branch:

1. Name the isolated deficit and why it is learnable rather than information
   loss, sensor/exposure failure, timing/calibration error, backend behavior, or
   domain shift.
2. Approve the exact component, framework, training membership, objective,
   preprocessing, seeds/trials, compute budget, stopping rule, and checkpoint
   selection rule.
3. Run a tiny deterministic CPU sample/forward/backward/save/load/inference
   smoke before requesting GPU capacity.
4. Train one bounded configuration, evaluate it through the unchanged causal
   replay/evaluator, and retain all failures.
5. Export only an evidence-selected learned component. ONNX and every target-
   specific runtime remain conditional.

A tracking service may mirror metrics but is never the authority. No exact
model architecture, parameter count, framework, optimizer, loss, resolution,
batch size, or training duration is selected by this roadmap.

## Milestone overview

| ID | Milestone | Status at this review | Dependency that controls status |
|---|---|---|---|
| M0 | Reproducible repository foundation | Complete | Foundation commit and CI evidence |
| M1 | Planning traceability and static durability preflight | Complete | M0 |
| M2 | Artifact durability for important GPU work | Blocked | Required before long or irreplaceable paid runs |
| M3 | Scientific question and estimator contract | In progress | M1; local-VIO direction fixed, details remain |
| M4 | Replay sensor, time, frame, and calibration contract | Complete | Causal replay, typed sensor records, and calibration profile/assessment fixtures |
| M5 | Reproducible execution environments | In progress | Local path active; worker tasks require fresh inventory and authorization |
| M6 | Dataset approval and representative ingestion | Blocked | Accepted research scope, sufficient M3/M4 detail, project-owner dataset-scope approval, and per-dataset rights review |
| M7 | Common causal replay and evaluator | In progress | Synthetic replay unblocked; real-data exit depends on M6 |
| M8 | Shared-backend feasibility and native reference | Blocked | M5–M7, accepted scope, and dependency rights review |
| M9 | Conditional A/B/C/D-monitor/D experiments | Conditional; blocked | M8, accepted ADR-0004 scope, and a future Accepted backend-selection ADR |
| M10 | Discovery failure atlas and conditional targeted learning | Conditional; blocked | Applicable M9 evidence and a frozen discovery protocol |
| M11 | Confirmatory final-test execution and scientific selection | Blocked | Applicable M8–M10 evidence, sealed final-test membership, and frozen confirmatory protocol |
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

Dependencies: M1; the local-VIO direction recorded in
[ADR-0002](adr/0002-estimator-scope.md); `R-RI-*`, `R-EST-*`. Accepted
[ADR-0002](adr/0002-estimator-scope.md) and
[ADR-0004](adr/0004-primary-research-contribution.md) are exit evidence, not
entry dependencies.

Required decisions/evidence:

- First accept one primary question, contribution, comparator, target
  phenomenon/population, endpoint family, independent experimental unit, and
  fairness contract as the research-scope freeze.
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
- The primary question, concrete declaration values, sample-level lineage,
  endpoint family, evaluator thresholds, and ADR-0004 acceptance remain
  unresolved; M3 stays in progress.

Prohibited work:

- No final architecture selection from paper-reported metrics on other devices.
- No combined primary claim spanning compactness, gating, robustness, and
  uncertainty.
- No primary metric-scale result with Sim(3) scale correction.

Exit evidence:

- Accepted ADR-0002 and ADR-0004.
- Frozen research-scope protocol revision and estimator interface-control
  draft. The confirmatory numerical protocol remains a later freeze.
- Claim-to-evidence and negative-control matrix.

M7–M11 produce the ADRs' follow-up empirical evidence. Material contradiction
reopens or supersedes the affected ADR; hypothesis rejection alone does not
authorize changing ADR-0004's primary claim after results are seen.

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
not inferred from it. Learned-training, dataset work, and every later worker
task require fresh inventory and authorization.

Dependencies: M1 for the local CPU environment. Important or extended future
paid GPU work additionally depends on M2; estimator-specific environments depend
on M3 and M4.

Permitted work:

- Maintain a framework-neutral core environment for records, replay, geometry,
  evaluation, and repository tooling.
- Maintain an isolated native environment for each selected classical baseline;
  no learned-training framework is a dependency of the common core or classical
  lane.
- Add a separate learned-training environment only after post-failure-atlas
  evidence and an accepted targeted-training decision select that work and its
  framework. Add CUDA bindings only for a freshly inventoried worker that
  benefits from them.
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

## M6 — Dataset approval and representative ingestion

Status: Blocked.

Dependencies: accepted research-scope freeze, sufficient M3/M4 interface detail
for the chosen adapter, `R-DATA-*`, and per-dataset rights review. Full or
important paid-worker acquisition additionally depends on M2/M5.

Required work:

Procedure authority: [Dataset governance policy](../governance/datasets/policy.md)
and [candidate registry](../governance/datasets/registry.yaml).

- For each candidate, verify official rights, exact source/version, modalities,
  sensors, calibration, timestamps, ground-truth coverage, byte estimate, and
  checksum strategy before download.
- Require the project owner to approve the exact dataset, release, unit,
  modalities, role, split membership, and acquisition location. Keep the
  dataset-file rights review as a separate required record; technical evidence
  collection cannot self-approve either scope or rights.
- Assign a declared role and source-group ID; freeze train/validation/final-test
  membership before windows, normalization, corruption, or augmentation.
- Acquire one rights-checked representative sequence first and validate frames,
  units, timing, calibration, missing data, ground-truth interpolation, and
  causal streaming. Expand only to approved subsets that fit the applicable
  capacity and retention budget.

Prohibited work:

- Candidate registration is not download approval.
- Dataset repository code licenses must not be treated as dataset-file rights.
- EuRoC or another benchmark must not silently serve both tuning and final test.

Exit evidence:

- Project-owner dataset-scope approval, separate dataset-file rights review,
  approved registry entries, acquisition manifests, immutable split manifest,
  validated representative replay profile, representative-ingestion report,
  and timestamp/frame/calibration negative-test report on the acquired
  sequence.

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
- The recorder does not define expected opportunities, infer missing outputs or
  failure causes, prove adapter-internal reset/sample use, or establish
  scientific run success. Persistent full-run traces and complete
  lifecycle/failure-policy evidence remain open; generic payload objects are not
  deep-copied by the in-memory snapshot.
- A terminal execution-coverage bridge now binds caller-declared outcomes to the
  complete recorder plan. Every successfully recorded output ordinal is bound
  exactly once; explicit missing slots may reference the failed event and
  unattempted suffix. It rejects active snapshots and does not create expected
  opportunities, reasons, failure labels, thresholds, or a success decision.
- These kernels are not aligned ATE, RPE, metric-scale evidence, coverage or
  completion evidence, frame-correctness proof, run-level failure accounting,
  or a complete evaluator. M7 remains in progress.

Prohibited work:

- No estimator-specific evaluator or hidden candidate-specific preprocessing.
- No survivor-only aggregate without failure and coverage reporting.

Exit evidence:

- All adapters pass the same golden replay/geometry fixtures.
- Deliberately corrupted controls fail for the expected reason.

## M8 — Shared-backend feasibility and native reference

Status: Blocked.

Dependencies: M5–M7, accepted research scope, representative ingestion,
evaluator/lifecycle semantics, and per-dependency rights review.

Required work:

- Freeze a backend-facing observation contract: measurement time, camera,
  track identity, pixel/bearing value, channel provenance, geometric validity,
  optional measurement-noise representation, and rejection reason.
- Freeze backend state, initialization, reset, causality, output, and feasibility
  resource criteria without selecting values from paper results.
- Time-box a shortlist spike. Prove whether one candidate can accept synthetic
  visual-motion, learned-landmark, and dual-channel observations through the
  same interface and can expose reset/failure behavior with loop closure off.
- Record an evidence-based backend recommendation or an explicit no-selection
  result. No backend is selected by this roadmap.
- After the spike, propose a backend-selection ADR from the evidence and require
  the project owner to mark it `Accepted` with a decision date before M9. If no
  candidate passes or no ADR is accepted, stop; a recommendation alone does not
  authorize A/B/C/D work.
- Separately pin, build, and reproduce one rights-compatible native classical
  reference through the common replay/evaluator. Retain its native backend and
  runtime; do not force it through a learned framework or call it a same-backend
  internal control.

Exit evidence:

- One shared-backend candidate passes the frozen feasibility criteria and is
  selected by a future `Accepted` backend-selection ADR, or work stops with an
  explicit no-selection report and revised scope/contract.
- One stable native classical reference has pinned source/rights/dependencies,
  reproducible build/run evidence, complete trajectory/failure/resource output,
  and no learned-framework/tracker dependency.
- Recorded ADR-0002 follow-up evidence; material contradiction reopens the
  affected scope before A/B/C/D work.

## M9 — Conditional A/B/C/D-monitor/D experiments

Status: Conditional; blocked.

Dependencies: accepted ADR-0004 research scope, M6/M7 data/evaluator evidence,
M8 shared-backend/native-reference evidence, a future `Accepted` backend-
selection ADR, frozen configuration definitions, and rights review for every
imported component.

Procedure authority: [Research protocol](protocols/research-protocol.md).

Required order when ADR-0004 is accepted:

1. A — one selected fast visual-motion channel plus IMU/shared backend.
2. B — one rights-approved frozen learned-landmark channel plus IMU/shared
   backend; Version 1 performs no project-side training.
3. C — A+B with explicit track provenance and correlated/duplicate-measurement
   policy.
4. D-monitor — C plus the exact D diagnostics, with no fusion action.
5. D — C plus one predeclared deterministic reliability action.

Every internal configuration freezes backend/state/init/IMU/factors/robust
loss/numerics/output schedule, permitted inputs, preprocessing, accepted
measurement/resource budget, and evaluator. B must demonstrate unique channel
evidence under that fairness policy before C/D claims proceed. D must meet the
primary endpoint plus nominal-accuracy, coverage, and resource guardrails.

Prohibited work:

- No A/B/C/D implementation before ADR-0004 acceptance and M8 feasibility.
- No assumption that optical flow, a named learned model, a backend, a health
  signal, weighting, gating, or any threshold has been selected.
- No final-test tuning, overlapping source groups, future inputs, hidden
  candidate preprocessing, or silent duplicate/correlated measurements.
- No project-side training, synthetic pretraining, learned reliability, or
  direct learned VIO on the critical path.

Exit evidence:

- Complete run bundles for every declared configuration/trial, including
  failures and D-monitor overhead.
- Mechanism-isolation report for A/B/C/D-monitor/D plus the separately reported
  native reference.
- Recorded ADR-0004 follow-up evidence; claims outside the accepted scope remain
  exploratory.

## M10 — Discovery failure atlas and conditional targeted learning

Status: Conditional; blocked.

Dependencies: applicable M9 evidence and a discovery protocol frozen without
final-test access.

Required work:

- Run nominal data, one declared visual fault family, and one timing/IMU control
  family first; add conditions only through protocol revision.
- Retain channel diagnostics, estimator/lifecycle outcomes, coverage, failures,
  recovery, runtime, and negative results without converting them into an
  unaccepted taxonomy.
- Diagnose whether a deficit is information loss, sensor/exposure failure,
  timing/calibration error, backend behavior, domain shift, or plausibly
  learnable.
- Open one targeted training/fine-tuning branch only after a separate decision
  selects the learnable component, data, framework, objective, trials, budget,
  stopping rule, and checkpoint selection. Otherwise record training as not
  applicable.
- Keep probabilistic covariance/uncertainty separate from deterministic health.
  Any uncertainty study requires its own accepted state/frame/propagation and
  calibration protocol.

Prohibited work:

- Do not call a condition learnable merely because both visual channels fail.
- Do not label a health score as covariance or feed it to PX4.
- Do not use final-test results to choose fault severity, thresholds, training
  data, or model configuration.

Exit evidence:

- Discovery atlas with complete condition/channel/failure/coverage evidence.
- Explicit no-training decision or an accepted, bounded targeted-training plan
  and its tracker-independent run bundles.
- A frozen candidate/configuration set ready for the later confirmatory freeze.

## M11 — Confirmatory final-test execution and scientific selection

Status: Blocked.

Dependencies: M8 and every applicable M9/M10 milestone, a frozen candidate set,
source groups assigned to sealed final-test membership before any use, and an
owner-approved confirmatory protocol.

Required work:

- Freeze the exact confirmatory run set only from already sealed final-test
  membership, together with metric semantics, thresholds, trials, budgets,
  aggregation, stopping rules, and the single D action. Never reassign a seen
  development, discovery, or stress group to final test.
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

1. Record ADR-0004 as a review-ready proposal and align requirements,
   architecture, protocol, and roadmap without accepting its unresolved owner
   choices. **Completed by this documentation slice; ADR remains Proposed.**
2. Continue one framework-neutral M7 evaluator/lifecycle behavior at a time.
   Terminal recorder-plan to explicit coverage binding is now implemented;
   proceed only to the next separately declared behavior
   with caller-declared policy identity and focused negative controls. Do not
   invent final thresholds, schedule, failure taxonomy, or dataset semantics.
3. After the research-scope freeze is accepted, obtain owner approval for
   exactly one dataset release/unit/modality/role and acquisition location
   after official rights/modality/calibration/GT/size review. EuRoC remains only
   a candidate until that record exists.
4. Download only the approved unit and implement one adapter under `data/`,
   including actual calibration assessment, provenance, and negative controls.
5. Complete evaluator/lifecycle semantics supported by that data, then run the
   time-bounded shared-backend feasibility spike under `backend/`.
6. Reproduce one native classical reference under `baselines/` and report it
   separately.
7. After ADR-0004 and M8 pass, add A, then B, then C, then D-monitor, then D;
   create `inertial/`, `vision/`, `fusion/`, `health/`, and `estimators/` only
   with their first tested behavior.
8. Build the discovery failure atlas. Open `learning/` only if a later accepted
   decision authorizes one targeted branch.
9. Freeze the confirmatory protocol and execute it without moving thresholds or
   accessing final test early.
10. Export only an evidence-selected learned component and only if deployment
    scope is later approved.

The exact source licence, mono/stereo decision, dataset, backend, visual method,
learned component/weights, correlation policy, reliability signal/action,
framework, model architecture, hyperparameters, roles/splits, thresholds,
artifact stores, and target hardware remain their existing decision gates.
No task in this queue assumes Brev/A10 use. Worker deletion remains a separate
destructive action requiring explicit approval.
