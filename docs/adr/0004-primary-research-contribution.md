# ADR-0004: Primary research contribution

- Status: Proposed
- Decision owner: Project owner
- Decision date: TBD

## Context

Compactness, complementary perception, deterministic reliability handling,
learned uncertainty, robustness training, and deployment compression are
different research claims. Treating them as co-primary would make the result
movable and hide which mechanism caused an improvement.

The previous working direction compared a direct learned VIO control with a
physically anchored learned correction. The reviewed refactor removes that
training-first comparison from the critical path. It keeps causal metric-scale
local VIO, physical IMU propagation, common replay/evaluation, and native
classical references, but organizes the internal experiment around observable
flight failure modes and one modular estimator.

## Proposed decision

The proposed primary contribution is **deterministic reliability-aware handling
of complementary visual measurements in a causal metric-scale local-VIO
system**.

The proposed primary mechanism comparison is:

- **C — dual visual channels:** fast visual-motion observations and
  rights-approved frozen learned-landmark observations enter one shared track
  manager and one shared backend under fixed measurement handling.
- **D — reliability-aware dual visual:** the identical C system adds one
  predeclared deterministic reliability action policy.

The primary comparison is D versus C. A **D-monitor** control runs the same
diagnostics and records the same health signals as D but takes no fusion action;
it separates monitoring overhead from the effect of the protocol-declared
action policy.
Weighting and hard gating are not interchangeable labels: the confirmatory
protocol must select one as D's primary action, and any alternative is a
separate ablation.

The broader internal matrix is:

- **A:** fast visual-motion channel plus IMU and the shared backend.
- **B:** rights-approved frozen learned-landmark channel plus IMU and the shared
  backend.
- **C:** both visual channels plus explicit provenance, correlation, and
  duplicate-measurement handling, with fixed measurement handling.
- **D-monitor:** C plus diagnostics that do not alter fusion.
- **D:** C plus the deterministic reliability action declared by the applicable
  development or confirmatory protocol.

One native classical implementation remains an external reference in its own
runtime and backend. It is not represented as an A/B/C/D internal ablation.
"Same backend" for A/B/C/D also requires the same state, initialization, IMU
path, factor policy, robust loss, numerical settings, output schedule, accepted
measurement/resource budget, permitted inputs, preprocessing, and evaluator.

If accepted, Version 1 performs no project-side model training. Configuration B
may use a frozen pretrained component only after its exact code, weights,
licence, provenance, preprocessing, and evaluation-data overlap are reviewed.
Direct end-to-end learned VIO becomes an optional external comparator, not a
prerequisite. A project training branch opens only after a discovery failure
atlas isolates a declared, plausibly learnable failure and a separate training
plan is approved.

## Two freeze points

Acceptance of this ADR is the **research-scope freeze**. It selects the primary
contribution, comparator, endpoint family, target phenomenon/population, and
independent experimental unit so bounded engineering may proceed.

A later **confirmatory-protocol freeze**, before untouched final-test access,
selects the exact confirmatory run set from source groups already assigned to
sealed final-test membership before any use. It also selects numerical
thresholds, trials, budgets, aggregation, stopping rules, and the single
deterministic D action. It never retroactively reassigns a seen development or
discovery group to final test, and it does not permit numerical values to move
after results are inspected.

## Decisions still required before acceptance

- Accept or reject reliability-aware handling as the single primary
  contribution.
- Accept or reject D versus C as the primary comparison and D-monitor as a
  required control.
- Name the target failure phenomenon/population, primary endpoint family, and
  independent experimental unit.
- Accept or reject removal of direct learned VIO from the critical path.
- Accept or reject the Version 1 no-project-training rule.
- Define the fairness/resource-policy fields that must be identical across
  A/B/C/D.

## Not selected by this proposal

This proposal does not select a dataset or sequence, mono or stereo, a physical
sensor, optical-flow method, learned detector or matcher, backend, track-merging
rule, reliability signal, action, threshold, state vector, optimizer, numerical
library, training framework, model architecture, compute budget, deployment
target, or flight scope. EuRoC, KLT, SuperPoint, LightGlue, Ceres, VINS-Fusion,
OpenVINS, Basalt, and PyTorch remain candidates or examples until their
applicable evidence and decision gates pass.

Ground truth is separate from causal replay input, estimator input, online
reliability logic, and final-test tuning. Version 1 uses it only in evaluation;
a later approved supervised branch may expose labels from training membership
only.

## Evidence required before acceptance

- Named decision owner and date.
- One primary contribution, comparator, endpoint family, target population, and
  independent experimental unit.
- Claim-to-evidence and negative-control matrices.
- Same-backend fairness contract for A/B/C/D.
- D-monitor control and a rule that one primary D action is frozen later.
- Explicit Version 1 and conditional-training boundaries.

## Follow-up evidence

- Dataset and evaluator feasibility from M6/M7.
- Shared-backend feasibility and one native reference from M8.
- Controlled A/B/C/D-monitor/D and negative-control evidence from M9 when the
  proposal is accepted and applicable.
- Discovery failure-atlas evidence before any targeted training request.
- Frozen-threshold claim decision from M11. A failed hypothesis is a valid
  result and does not authorize changing the primary claim after inspection.

If this ADR is later accepted, it supersedes only ADR-0002 Decision bullet 4,
which describes the scientific comparison. ADR-0002's accepted local-VIO,
no-loop-closure, PX4, common-replay, and no-Sim(3) boundaries remain unchanged.
Until acceptance, ADR-0002 remains authoritative in full.

Reopen or supersede this ADR only when its protocol is invalidated, not merely
because the selected hypothesis fails.
