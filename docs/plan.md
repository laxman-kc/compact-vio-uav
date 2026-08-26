# Implementation plan

Status: Active roadmap; decision-dependent milestones blocked

Last reviewed: 2026-08-26

Requirements authority: [Project requirements](requirements/project-requirements.md)

Decision authority: [ADR index](adr/README.md)

Evidence ledger: [Progress](progress.md)

## Planning contract

This roadmap owns milestone order, dependencies, permitted work, prohibited
premature work, and exit evidence. It does not redefine requirements, accept an
ADR, assign a dataset role, or select a model, sensor, edge board, license, or
flight scope.

The project advances only when a milestone's exit evidence exists. A later
milestone may be explored in a disposable, non-claiming spike only when the
earlier milestone explicitly permits it; a spike cannot be reported as project
evidence.

Milestone bullets summarize permitted scope and required outcomes. Where a
milestone links an artifact policy, dataset policy, research protocol, or
experiment lifecycle, that linked record governs the procedure and wins over a
roadmap summary if wording drifts.

## Evidence-based recommendation awaiting decisions

The following is the recommended package to evaluate in ADR-0002 through
ADR-0004. It is not an accepted architecture:

1. Make causal, metric-scale local odometry the first estimator scope; evaluate
   mapping/relocalization separately if the mission requires it.
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
6. Do not select mono versus stereo from dataset convenience. Decide it from
   mission, payload, synchronization, robustness, bandwidth, and exact-target
   measurements.

This recommendation preserves the simplified, physically grounded direction
from the design feedback while keeping a falsifiable classical reference and
preventing architecture preference from becoming evidence.

## Milestone overview

| ID | Milestone | Status at this review | Dependency that controls status |
|---|---|---|---|
| M0 | Reproducible repository foundation | Complete | Foundation commit and CI evidence |
| M1 | Planning traceability and static durability preflight | In progress | M0 |
| M2 | Project authority, artifact durability, and paid-worker control | Blocked | M1; ADR-0001 and ADR-0005 |
| M3 | Scientific question and estimator contract | Blocked | M2; authorized provisional estimator/contribution choices |
| M4 | Replay sensor, time, frame, and calibration contract | Blocked | M3; generic contract requirements |
| M5 | Reproducible execution environments | Blocked | M2–M4 |
| M6 | Dataset approval and representative ingestion | Blocked | M3–M5 |
| M7 | Common causal replay and evaluator | Blocked | M3, M4, representative M6 data |
| M8 | Classical baseline reproduction | Blocked | M5–M7 and license review |
| M9 | Conditional novel-candidate experiments | Conditional; blocked | M7, M8, and accepted estimator/contribution scope |
| M10 | Optional uncertainty and health study | Conditional; blocked | Accepted estimator/contribution scope |
| M11 | Scientific selection and deployment shortlist | Blocked | Applicable M8–M10 evidence and frozen thresholds |
| M12 | Conditional export, exact-target benchmark, and deployable selection | Blocked | M11; authorized provisional sensor/target choices |
| M13 | Conditional ROS 2/PX4 and staged safety validation | Blocked | M12; accepted integration scope |
| M14 | Release evidence and final worker disposition | Blocked | All applicable prior milestones |

## M0 — Reproducible repository foundation

Status: Complete.

Dependencies: none.

Permitted work completed:

- Versioned requirements, architecture, ADR, dataset, artifact, and experiment
  contracts.
- Strict run/bundle schemas, safe artifact inventory/verification, repository
  policy, package build, tests, and SHA-pinned CI actions.
- A clean GitHub checkout and standard-library test run on the A10 worker.

Exit evidence:

- Foundation commit `ea07ccbc7ee1ab7ba870473be63625259b4b64fc`.
- Successful GitHub Actions run recorded in [progress](progress.md).
- A10 inventory in
  [environments/a10/inventory-2026-08-26.md](../environments/a10/inventory-2026-08-26.md).

## M1 — Planning traceability and static durability preflight

Status: In progress.

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

## M2 — Project authority, artifact durability, and paid-worker control

Status: Blocked.

Dependencies: M1; project-owner authorization to evaluate provisional release
and storage choices; `R-INFRA-*`. Accepted
[ADR-0001](adr/0001-project-and-release-scope.md) and
[ADR-0005](adr/0005-artifact-storage.md) are exit evidence, not entry
dependencies.

Required decisions/evidence:

- Record project purpose, release lanes, source/model/report license intent, and
  dependency-license policy.
- Record the artifact-vault and independent backup failure domains, access,
  encryption, capacity, retention, recovery-point objective, cost budget, and
  recovery owner.
- Estimate worst-case retained bytes plus an explicit reserve. For filesystem-
  backed candidates, run `compact-vio-preflight`; for another backend, approve
  and record a provider-specific static check.
- Follow the authoritative [artifact policy](../governance/artifacts/policy.md)
  and [experiment lifecycle](protocols/experiment-lifecycle.md) for the
  representative export/backup/restore drill and evidence bundle.
- Record transfer throughput, expected teardown-transfer duration, A10 spending
  ceiling, next review time, and who can authorize deletion.

Prohibited work:

- No important or long-running GPU experiment before the restore drill passes.
- No claim that GitHub, a GitHub Actions artifact, or two paths on one filesystem
  are independent backups.
- No destructive `brev delete` without a separate explicit approval and the
  applicable preservation/teardown audit.

Exit evidence:

- Accepted ADR-0001 and ADR-0005.
- Successful applicable static check and representative restore report.
- Two checksum-verified copies outside Brev in reviewed independent failure
  domains.
- Paid-worker authorization record.

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

Status: Blocked.

Dependencies: M2; project-owner authorization to evaluate provisional estimator
and contribution choices; `R-RI-*`, `R-EST-*`. Accepted
[ADR-0002](adr/0002-estimator-scope.md) and
[ADR-0004](adr/0004-primary-research-contribution.md) are exit evidence, not
entry dependencies.

Required decisions/evidence:

- Select one primary question, contribution, comparator, target population,
  metrics, thresholds, trials/seeds, and rejection rule before final testing.
- Freeze local VIO versus VI-SLAM, loop-closure policy, state variables,
  transform direction, frames, metric-scale mechanism, initialization, reset,
  recurrence warm-up, output timestamp, output rate, and latency definition.
- Define causality: for each output, list exactly which camera and IMU samples
  are available and when the estimate becomes available.
- Separate scientific-winner criteria from deployable-winner criteria.

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

Status: Blocked.

Dependencies: M3; `R-DATA-*`, `R-EST-*`, and `R-CAL-*`.

Physical-sensor selection in [ADR-0003](adr/0003-sensor-contract.md) remains
deferred until the deployment and integration milestones require it.

Required decisions/evidence:

- Define a modality-neutral canonical schema for exposure time, IMU intervals,
  clock mapping/offset sign, frames, axes, units, gravity, validity, provenance,
  and calibration versioning.
- Require each replayed dataset profile to record its actual mono/stereo,
  shutter, resolution/rates, intrinsics/distortion, camera–IMU transform,
  temporal calibration, IMU stochastic parameters, and available diagnostics.
- Define the validation rules that each approved profile must satisfy before its
  records enter the common evaluator.

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

## M5 — Reproducible execution environments

Status: Blocked.

Dependencies: M2–M4.

Permitted work:

- Maintain separate local-development, A10 x86-64 execution, and future target
  environment definitions.
- Pin base image digest, OS/architecture, Python/C++ dependencies, compiler,
  CUDA/driver/framework/runtime versions, Git SHA, and hardware inventory.
- Rebuild from a clean checkout and run deterministic CPU/GPU smoke fixtures.

Prohibited work:

- Do not use an unrecorded global A10 environment for claim-supporting runs.
- Do not treat the A10 stack as the future Jetson/edge stack.

Exit evidence:

- Rebuild instructions and dependency locks reproduce the declared smoke output
  on a clean A10 checkout.

## M6 — Dataset approval and representative ingestion

Status: Blocked.

Dependencies: M3–M5; `R-DATA-*`; dataset governance.

Required work:

Procedure authority: [Dataset governance policy](../governance/datasets/policy.md)
and [candidate registry](../governance/datasets/registry.yaml).

- For each candidate, verify official rights, exact source/version, modalities,
  sensors, calibration, timestamps, ground-truth coverage, byte estimate, and
  checksum strategy before download.
- Assign a declared role and source-group ID; freeze train/validation/final-test
  membership before windows, normalization, corruption, or augmentation.
- Acquire one representative sequence first and validate frames, units, timing,
  calibration, missing data, ground-truth interpolation, and causal streaming.
- Expand only to approved subsets that fit M2 capacity and retention budgets.

Prohibited work:

- Candidate registration is not download approval.
- Dataset repository code licenses must not be treated as dataset-file rights.
- EuRoC or another benchmark must not silently serve both tuning and final test.

Exit evidence:

- Approved registry entries, acquisition manifests, immutable split manifest,
  validated representative replay profile, representative-ingestion report, and
  timestamp/frame/calibration negative-test report on the acquired sequence.

## M7 — Common causal replay and evaluator

Status: Blocked.

Dependencies: M3, M4, representative M6 data; `R-RI-*`, `R-DATA-*`,
`R-EST-*`, `R-EVAL-*`.

Required work:

- Implement canonical image/IMU/ground-truth/calibration records and conversion
  adapters that retain source provenance.
- Implement online-equivalent causal replay, warm-up/reset/dropout/stale-state
  behavior, and explicit output availability time.
- Implement trajectory geometry and metric-scale checks, per-sequence ATE/RPE,
  initialization, completion, coverage, failures, resets, scale, and runtime
  distributions.
- Add frame, unit, timestamp, scale, split-leakage, future-leakage, and partial-
  trajectory negative controls.

Prohibited work:

- No estimator-specific evaluator or hidden candidate-specific preprocessing.
- No survivor-only aggregate without failure and coverage reporting.

Exit evidence:

- All adapters pass the same golden replay/geometry fixtures.
- Deliberately corrupted controls fail for the expected reason.

## M8 — Classical baseline reproduction

Status: Blocked.

Dependencies: M5–M7; accepted dependency/license lane.

Recommended comparison set to evaluate, not preselected dependencies:

- OpenVINS as the covariance-aware filter reference.
- One optimization or efficient local-odometry reference whose license and
  maintenance envelope fit the selected lane.
- Loop closure disabled for a local-odometry table; VI-SLAM results reported in
  a separate table if that scope is accepted.

Required work:

- Pin upstream commit/license/dependencies and isolate each build.
- Map identical permitted inputs and calibration to the common replay.
- Reproduce trajectories, failures, coverage, timing, CPU/GPU/RAM, and repeated
  run variation on the same platform.
- Explain deviations from published results without tuning on final-test data.

Exit evidence:

- At least one stable, understood classical reference and a frozen baseline
  scorecard before novel-model selection.
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

Prohibited work:

- No final-test tuning, overlapping windows across source groups, normalization
  fitted on held-out trajectories, bidirectional recurrence, or future frames.
- No compute-saving claim from parameter count/FLOPs alone or from a gate that
  runs after the expensive visual encoder.

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
- Build the production TensorRT engine/native package on the exact pinned target
  stack; an A10-built engine is not target evidence.
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

## M14 — Release evidence and final worker disposition

Status: Blocked.

Dependencies: every milestone applicable to the accepted scope.

Required work before release:

- Revalidate code/model/data/dependency rights and separate incompatible lanes.
- Restore release and reproducibility-critical bundles from their recorded
  locations; verify manifests, hashes, loadability, reports, and provenance.
- Publish only approved code, metadata, documentation, and intentionally reviewed
  binary channels.

Required work before final Brev lifecycle action:

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

Two independent decision tracks are unblocked after M1 validation:

Release/rights track for ADR-0001:

1. Record intended purpose, users, distribution surfaces, and research versus
   commercial lanes.
2. Build the dependency/data/model/report rights matrix and obtain legal review
   wherever eligibility cannot be established by authoritative terms.
3. Select and explicitly accept or reject the project/license/release proposal.

Durability/cost track for ADR-0005:

1. Authorize provisional vault/backup candidates for evidence gathering; record
   retained-byte estimate, reserve, retention/RPO, spend, and owners.
2. Run the filesystem preflight or an approved provider-specific equivalent.
3. Run the representative transfer/backup/restore drill under the artifact
   policy and record evidence.
4. Accept or reject ADR-0005 based on the durability evidence.

M3 begins only after both tracks satisfy M2 exit evidence. A cost-saving worker
teardown may occur earlier under the exception above; it is not evidence that M2
or M14 passed.

Until those inputs exist, repository validation and documentation refinement are
permitted; dataset download, training, and prolonged GPU work remain blocked.
Worker deletion remains a separate explicitly approved destructive action under
the cost-control exception.
