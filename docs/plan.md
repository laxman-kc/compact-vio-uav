# Implementation plan

Status: Active roadmap; decision-dependent milestones blocked

Last reviewed: 2026-08-26

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

A newly created A10 was observed ready on 2026-08-27 and is approved only for
the current bounded implementation smoke. It is not approved for datasets or
training. No access or approval carries forward; every later worker task
requires fresh project-owner confirmation.

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
causal local-VIO scope, and PX4 control boundary. The physically anchored hybrid
below is the proposed research hypothesis in unresolved ADR-0004, not a selected
winner. Exact state interfaces, sensor profiles, thresholds, datasets, and
deployment choices remain milestone work:

1. Build causal, metric-scale local odometry; mapping, relocalization, and loop
   closure are outside the primary comparison.
2. Use a calibrated physical IMU propagation/preintegration path to anchor
   metric scale and time, then evaluate a compact learned visual correction or
   measurement as the primary hybrid candidate.
3. Compare that candidate against one stable filter-based classical baseline,
   an always-on learned visual–inertial control with the same data budget, and
   visual-only/IMU-only diagnostic controls.
4. Defer visual-compute gating until an always-on causal reference works. A
   post-encoder gate is reliability fusion, not compute skipping.
5. Treat uncertainty as secondary unless ADR-0004 explicitly selects calibrated
   uncertainty as the single primary contribution.
6. PX4 retains stabilization, failsafes, pilot override, and motor control. VIO
   is only a future health-gated odometry measurement source.
7. Do not select mono versus stereo from dataset convenience. Decide it from
   mission, payload, synchronization, robustness, bandwidth, and exact-target
   measurements.

This direction keeps the research physically grounded and the comparison
falsifiable without locking hardware or final-test outcomes prematurely.

### Simple model-training sequence

If ADR-0004 accepts a learned/hybrid comparison, the model-training path begins
only after the common data/evaluator substrate and one classical reference work.
PyTorch is the current framework proposal, not an accepted dependency:

1. Prepare approved training samples from the frozen training split. Validation
   is used for declared tuning; final-test sequences stay sealed.
2. Implement and run only the visual-only and IMU-only diagnostics needed to
   validate modality contribution. Use the selected framework only if a
   diagnostic is explicitly learned.
3. Train one always-on direct learned visual-inertial control in the selected
   framework.
4. Train one physically anchored hybrid in the selected framework: physical IMU
   propagation/preintegration provides the metric motion path and the learned
   visual component provides a correction or measurement.
5. Replay the classical reference and every frozen learned candidate through the
   same evaluator. Select from accuracy, scale, coverage/failures, and measured
   resource evidence—not training loss alone.
6. Export only an evidence-selected learned component. ONNX is conditional;
   TensorRT, Jetson, ROS 2, and PX4 remain later exact-target decisions.

Classical VIO bypasses any neural training framework. MLflow is optional run
visualization and never the authoritative model registry. TartanAir or other
synthetic pretraining, compute gating, robustness training, and uncertainty are
optional ablations after the direct and hybrid reference models work. No exact
neural architecture, parameter count, optimizer, loss, resolution, batch size,
or training duration is selected by this roadmap.

## Milestone overview

| ID | Milestone | Status at this review | Dependency that controls status |
|---|---|---|---|
| M0 | Reproducible repository foundation | Complete | Foundation commit and CI evidence |
| M1 | Planning traceability and static durability preflight | Complete | M0 |
| M2 | Artifact durability for important GPU work | Blocked | Required before long or irreplaceable paid runs |
| M3 | Scientific question and estimator contract | In progress | M1; local-VIO direction fixed, details remain |
| M4 | Replay sensor, time, frame, and calibration contract | Complete | Causal replay, typed sensor records, and calibration profile/assessment fixtures |
| M5 | Reproducible execution environments | In progress | Local path active; one live A10 is bounded to implementation smoke only |
| M6 | Dataset approval and representative ingestion | Blocked | Remaining M3 details, the M4 contract, and per-dataset rights review |
| M7 | Common causal replay and evaluator | In progress | Synthetic replay unblocked; real-data exit depends on M6 |
| M8 | Classical baseline reproduction | Blocked | M5–M7 and license review |
| M9 | Conditional novel-candidate experiments | Conditional; blocked | M7, M8, and accepted estimator/contribution scope |
| M10 | Optional uncertainty and health study | Conditional; blocked | Accepted estimator/contribution scope |
| M11 | Scientific selection and deployment shortlist | Blocked | Applicable M8–M10 evidence and frozen thresholds |
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

- Select one primary question, contribution, comparator, target population,
  metrics, thresholds, trials/seeds, and rejection rule before final testing.
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
  evaluator thresholds, and ADR-0004 remain unresolved; M3 stays in progress.

Prohibited work:

- No final architecture selection from paper-reported metrics on other devices.
- No combined primary claim spanning compactness, gating, robustness, and
  uncertainty.
- No primary metric-scale result with Sim(3) scale correction.

Exit evidence:

- Accepted ADR-0002 and ADR-0004.
- Frozen research protocol revision and estimator interface-control draft.
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

Current execution state: local, GitHub, and one freshly inventoried A10 approved
only for the current bounded implementation smoke. Learned-training and dataset
work remain outside this authorization.

Dependencies: M1 for the local CPU environment. Important or extended future
paid GPU work additionally depends on M2; estimator-specific environments depend
on M3 and M4.

Permitted work:

- Maintain a framework-neutral core environment for records, replay, geometry,
  evaluation, and repository tooling.
- Maintain an isolated native environment for each selected classical baseline;
  no learned-training framework is a dependency of the common core or classical
  lane.
- Add a separate learned-training environment only after ADR-0004 accepts that
  work and M9 starts. PyTorch is the current proposal. Add CUDA bindings only
  for a freshly inventoried worker that benefits from them.
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

Dependencies: sufficient M3/M4 interface detail for the chosen adapter,
`R-DATA-*`, and per-dataset rights review. Full or important paid-worker
acquisition additionally depends on M2/M5.

Required work:

Procedure authority: [Dataset governance policy](../governance/datasets/policy.md)
and [candidate registry](../governance/datasets/registry.yaml).

- For each candidate, verify official rights, exact source/version, modalities,
  sensors, calibration, timestamps, ground-truth coverage, byte estimate, and
  checksum strategy before download.
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

- Approved registry entries, acquisition manifests, immutable split manifest,
  validated representative replay profile, representative-ingestion report, and
  timestamp/frame/calibration negative-test report on the acquired sequence.

## M7 — Common causal replay and evaluator

Status: In progress.

Dependencies: M3/M4 contracts and `R-RI-*`, `R-DATA-*`, `R-EST-*`,
`R-EVAL-*`. Synthetic replay and geometry fixtures may proceed now; real-data
exit evidence depends on representative M6 data.

Required work:

- Implement canonical image/IMU/ground-truth/calibration records and conversion
  adapters that retain source provenance.
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
- These kernels are not aligned ATE, RPE, metric-scale evidence, run-level
  failure accounting, or a complete evaluator. M7 remains in progress.

Prohibited work:

- No estimator-specific evaluator or hidden candidate-specific preprocessing.
- No survivor-only aggregate without failure and coverage reporting.

Exit evidence:

- All adapters pass the same golden replay/geometry fixtures.
- Deliberately corrupted controls fail for the expected reason.

## M8 — Classical baseline reproduction

Status: Blocked.

Dependencies: M5–M7 and per-dependency licence review for the non-commercial
research lane.

Recommended comparison set to evaluate, not preselected dependencies:

- OpenVINS as the covariance-aware filter reference.
- One optimization or efficient local-odometry reference whose license and
  maintenance envelope fit the selected lane.
- Loop closure disabled for a local-odometry table; VI-SLAM results reported in
  a separate table if that scope is accepted.

Required work:

- Pin upstream commit/license/dependencies and isolate each build.
- Build and run the selected classical implementation through its native
  toolchain and expose it only through the common estimator adapter. Do not wrap
  it in a learned-framework module or require a learned framework/MLflow for
  installation, replay, or evaluation.
- Map identical permitted inputs and calibration to the common replay.
- Reproduce trajectories, failures, coverage, timing, CPU/GPU/RAM, and repeated
  run variation on the same platform.
- Explain deviations from published results without tuning on final-test data.

Exit evidence:

- At least one stable, understood classical reference and a frozen baseline
  scorecard before novel-model selection.
- A smoke check proves that the classical path imports and runs with every
  learned-training framework and MLflow absent.
- Recorded ADR-0002 follow-up feasibility/failure evidence; reopen the ADR before
  proceeding if the accepted estimator contract is invalidated.

## M9 — Conditional novel-candidate experiments

Status: Conditional; blocked.

Dependencies: M7, M8, frozen M3 protocol and M6 splits, plus accepted
ADR-0002/ADR-0004 decisions that require a novel learned, hybrid, or other
candidate. If the accepted scope is classical-only, record this milestone as
not applicable and proceed without manufacturing learned work.

Procedure authority: [Research protocol](protocols/research-protocol.md).

Required work is defined only after ADR-0002/ADR-0004 acceptance. The experiment
matrix must include the controls and ablations required by the selected
hypothesis while holding the frozen data, causality, evaluator, and declared
resource/training budgets constant.

For the current working direction, the smallest permitted training matrix is:

- visual-only and IMU-only diagnostics where needed;
- one always-on direct learned visual-inertial control;
- one physically anchored hybrid candidate; and
- only the ablation needed to isolate the learned correction from the physical
  propagation path.

If ADR-0004 accepts the proposed PyTorch path, the exact framework/runtime is
pinned in each run. The direct control and hybrid share the permitted inputs,
split, preprocessing, tuning policy, training/compute budget, seeds, and evaluator.
MLflow may mirror metrics locally, but retained evidence comes from the frozen
run bundle. Synthetic pretraining is a separate declared ablation and cannot be
silently folded into only one candidate.

Before requesting GPU capacity, each learned path must pass a tiny deterministic
CPU smoke covering sample construction, forward/backward execution, checkpoint
save/load, recurrent/reset state when present, and causal inference. Training
then uses only the approved train split; the frozen validation rule selects the
checkpoint; the selected checkpoint is evaluated through the same replay and
evaluator as M8 whether or not MLflow is enabled.

Prohibited work:

- No learned/hybrid model implementation or training before ADR-0004 accepts
  the primary contribution and framework choice. Framework-neutral records,
  replay, evaluation, and classical baseline work continue independently.
- No final-test tuning, overlapping windows across source groups, normalization
  fitted on held-out trajectories, bidirectional recurrence, or future frames.
- No compute-saving claim from parameter count/FLOPs alone or from a gate that
  runs after the expensive visual encoder.
- No checkpoint may exist only on temporary worker storage, and no MLflow server
  may be required to reconstruct a run.

Exit evidence:

- Complete run bundles for every declared trial, including failures.
- The selected primary hypothesis is accepted or rejected under its predeclared
  controls and frozen evaluator; claims outside the accepted scope are not
  implied.
- Recorded ADR-0004 follow-up evidence whether the hypothesis passes or fails.

## M10 — Optional uncertainty and health study

Status: Conditional; blocked.

Dependencies: applicable M8/M9 evidence and an accepted ADR-0002/ADR-0004
decision that makes uncertainty or health part of the scientific estimator
contract or contribution. Otherwise record this milestone as not applicable.

Deployment-specific uncertainty/health use under ADR-0006 is not an M10 entry
dependency; its exact-target and integration validation belongs to M12/M13.

Required work:

- Keep probabilistic state uncertainty separate from estimator health.
- Define state/frame/tangent/covariance representation and positive-semidefinite
  construction where covariance is produced.
- Evaluate likelihood, empirical coverage, sharpness, consistency where valid,
  risk–coverage, failure false negatives, OOD/corruption behavior, and
  accumulation semantics.

Prohibited work:

- Do not label an arbitrary confidence score as covariance.
- Do not feed learned uncertainty into PX4 before calibration and consistency
  evidence passes.

Exit evidence:

- Accepted uncertainty/health interface and nominal/OOD calibration report.

## M11 — Scientific selection and deployment shortlist

Status: Blocked.

Dependencies: M8 and every applicable M9/M10 milestone, with predeclared
thresholds.

Required work:

- Select the scientific winner, if supported, and a deployment shortlist across
  accuracy, scale, failure/coverage, robustness, uncertainty when applicable,
  runtime, memory, rights, reproducibility, and target relevance.
- Preserve the Pareto frontier and rejected alternatives; do not collapse all
  dimensions into an unreviewed scalar score.
- Freeze the scientific artifact and the shortlist's checkpoints/native builds,
  interfaces, data/model cards, and artifact hashes. Do not name a final
  deployable winner before exact-target evidence.

Exit evidence:

- Accepted scientific-selection/deployment-shortlist record with unchanged
  final-test thresholds and independently restorable evidence bundles.

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

1. Select and freeze the concrete values for the declared local-VIO
   state/frame/time/reset interface and the M3 research question.
2. Extend trajectory geometry and evaluation one explicitly declared operation
   or metric at a time, each followed by its negative control. Raw exact-pair
   translation RMSE is the first completed kernel.
3. Rights-check and ingest one representative sequence only, including its
   actual calibration profile and review evidence.
4. Reproduce one stable classical baseline through the common replay.
5. If an optional GPU worker is freshly approved and available, run one bounded
   environment/data smoke.
6. After ADR-0004 acceptance, implement the direct learned-control API with
   focused tests.
7. Run its tiny CPU train/checkpoint/inference smoke.
8. Run and review one bounded direct-control training configuration.
9. Implement the anchored-hybrid correction API with focused tests.
10. Run its tiny CPU train/checkpoint/inference smoke.
11. Run and review one bounded anchored-hybrid training configuration.
12. Perform common evaluation and select; export only if the selected candidate
   has a neural component and deployment scope is later approved.

The exact source licence, mono/stereo decision, model architecture,
hyperparameters, dataset roles/splits, thresholds, artifact stores, and target
hardware remain their existing decision gates. Worker deletion remains a
separate destructive action requiring explicit approval.
