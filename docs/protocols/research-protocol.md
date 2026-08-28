# Research protocol

Status: Draft; ADR-0004 proposal and numerical confirmatory protocol unresolved
Last reviewed: 2026-08-27

## 1. Freeze points

### Research-scope freeze

Before dataset-specific estimator or frontend work, accept a protocol revision
that records:

- One primary contribution and comparator.
- Target phenomenon/population and independent experimental unit.
- Primary endpoint family and required nominal/resource guardrail families.
- Exact A/B/C/D-monitor/D definitions when that matrix is accepted.
- Causal inputs, ground-truth separation, fairness controls, and allowed
  exploratory outputs.
- Version 1 and conditional-training boundaries.

ADR-0004 currently proposes deterministic reliability-aware D versus fixed-
handling C, but it is not accepted. Documentation, framework-neutral replay,
and evaluator work may proceed; the proposal does not authorize dataset,
frontend, backend, pretrained-model, threshold, or training choices.

### Confirmatory-protocol freeze

After representative ingestion, evaluator validation, shared-backend
feasibility, and discovery work—but before untouched final-test access—freeze:

- The exact confirmatory run set, selected only from source groups already
  assigned to sealed final-test membership before any use. A seen development,
  discovery, or stress group cannot be reassigned to final test.
- Primary metric definition, association/alignment/interpolation policy, units,
  numerical thresholds, and failure penalties.
- Trials/seeds, aggregation, uncertainty reporting, compute/resource budget,
  stopping rule, and final candidate/configuration identities.
- One deterministic D action policy and thresholds derived only from
  development evidence, then frozen for confirmatory use.

Changes after either freeze require a new protocol revision. Results produced
under different revisions are not pooled without disclosure. The second freeze
cannot change the primary claim merely because discovery results are weak.

## 2. Data protocol

- Approve one exact representative dataset unit before download or adapter work;
  a candidate registry entry is not approval.
- Before any use, record two explicit axes for every acquired source group:
  project role (`integration`, `discovery`, `stress`, or `confirmatory`) and
  split membership (`train`, `validation`, or `final-test`). Final-test
  membership is sealed and may be used only in the confirmatory role; a group
  used for integration, discovery, or stress cannot later become final test.
  Freeze both axes before derived samples are created.
- Keep related views, renders, weather variants, corruptions, windows, and
  underlying flights in one split unless an accepted protocol explicitly tests
  cross-variant transfer.
- Fit normalization and learned preprocessing on training membership only.
- Use validation membership only for declared tuning.
- Do not inspect final-test outputs until the confirmatory protocol is frozen.
- Record imported-model pretraining sources and check their overlap with
  evaluation data.
- Preserve exact dataset, calibration, preprocessing, and split hashes per run.
- Ground truth follows a separate evaluation branch. It never enters causal
  estimator input, track/reliability decisions, or final-test tuning. If a later
  training decision permits supervision, labels come only from approved
  training membership.

## 3. Causality and fairness

- Deliver sensor records through the common causal replay boundary.
- Emit an estimate no earlier than the newest measurement required to compute
  it.
- Prohibit future frames, future IMU samples, bidirectional recurrence, and
  full-sequence normalization in an online claim.
- Apply equivalent calibration access, sensor modalities, source groups,
  loop-closure policy, resets, and evaluation to comparable configurations.
- For internal A/B/C/D-monitor/D mechanism isolation, also freeze backend state,
  initialization, IMU path, factors, robust loss, numerical settings, output
  schedule, accepted-measurement/resource budget, preprocessing, and evaluator.
- A native classical reference may retain its native backend/runtime. Report it
  separately; do not present it as a same-backend ablation.
- Report algorithmic delay separately from wall-clock processing delay.
- Replay complete sequences, including initialization and post-reset behavior.

## 4. Staged configuration order

Only the stages permitted by accepted decisions execute:

1. Finish the common replay/evaluator and failure/lifecycle semantics.
2. Approve and ingest one representative dataset unit.
3. Run a time-bounded feasibility spike to determine whether one backend can
   accept externally supplied visual-motion, learned-landmark, and dual-channel
   observations under one state/init/reset/output contract.
4. Reproduce one rights-compatible native classical reference through the
   common replay/evaluator. Its native backend remains separate.
5. Implement A: one selected fast visual-motion channel plus IMU/shared backend.
6. Implement B: one rights-approved frozen learned-landmark channel plus
   IMU/shared backend. No project-side training occurs in Version 1.
7. Implement C: both channels with provenance and an explicit correlated/
   duplicate-measurement policy.
8. Implement D-monitor: C plus the exact D diagnostics, but no fusion action.
9. Implement D: C plus one deterministic reliability action declared for that
   protocol stage; the primary confirmatory action is frozen only at the later
   confirmatory-protocol freeze.
10. Build a discovery failure atlas, then decide whether any specific deficit
    is plausibly learnable.
11. Open one targeted training/fine-tuning branch only through a new decision
    and protocol revision; otherwise record training as not applicable.
12. Freeze and execute the confirmatory protocol.

No optical-flow algorithm, learned detector/matcher, weights, backend, health
signal, threshold, action, framework, or dataset is selected by this order.
Switching A/B/C/D changes the intended visual evidence or the protocol-declared
D action, not the backend or evaluator.

## 5. Imported learned components and conditional training

Before configuration B incorporates a frozen component, record its source,
commit/release, code and weight hashes, licence/redistribution terms, training
data disclosure, preprocessing, inference settings, and known benchmark overlap.
Paper performance is not incorporation evidence.

If targeted training is later approved, record framework/version, accelerator
stack, determinism controls, model/configuration ID, source-group split hashes,
seeds, stopping rule, and checkpoint-selection rule. Run a tiny CPU smoke before
requesting GPU capacity. Training uses only approved training membership,
validation follows its declared purpose, and final-test data never selects a
checkpoint. A tracking tool may mirror metrics but is not the authority.

## 6. Evaluation

### Trajectory and lifecycle

Report per sequence and in predeclared aggregates:

- Translational and rotational absolute trajectory error where supported.
- Relative pose error at declared time/distance intervals.
- Scale ratio/drift without Sim(3) correction for the primary metric-scale
  result.
- Initialization success/time, coverage/completion, tracking loss, restart and
  recovery, and time/distance to first failure.
- Every failed, partial, reset, stale, invalid, and non-initializing run.

Alignment, association, interpolation, ground-truth gaps, output opportunities,
failure taxonomy, and penalties must be frozen. No candidate-specific evaluator
or survivor-only aggregate is permitted.

### Frontend, reliability, and resources

Record channel provenance and declared diagnostics such as track count/age,
spatial coverage, geometric validity, rejection reason, and D action. The exact
set remains a later contract. Monitoring output is not covariance, and a
reliability signal is not a failure label without an accepted taxonomy.

Record sensor-to-pose p50/p95/p99/max latency, deadline misses, throughput,
queueing, input drops, peak memory, and relevant utilization. Power, energy,
temperature, and throttling claims require the actual target device. A10 timing
is execution-platform evidence only, never embedded-runtime evidence.

## 7. Discovery failure atlas

Discovery starts with nominal data, one declared visual fault family, and one
timing/IMU control family. Additional conditions are added only through a
protocol revision. Preserve severity, affected channel, estimator outcome,
coverage, recovery, and all negative results.

Darkness, blur, low texture, or any other condition is not automatically a
learnable failure. First exclude information loss, exposure/sensor faults,
timing/calibration error, backend behavior, and domain shift. Training opens
only when the isolated mechanism and success criterion are declared.

Perturbation severity is chosen from development/validation evidence, never
from final-test results. Discovery and confirmatory atlas outputs remain
separate.

## 8. Statistical and reporting rules

- Report all predeclared trials, not the best run.
- Keep per-sequence results visible with aggregates.
- Distinguish confirmatory and exploratory results.
- Include effect size and uncertainty appropriate to the experimental unit.
- Do not treat overlapping windows from one trajectory as independent units.
- Preserve failed-run configuration and diagnosis.
- Record protocol deviations before interpreting results.

## 9. Selection

Maintain separate decisions for:

- Scientific result: whether evidence supports the accepted primary hypothesis.
- Deployable result: which feasible configuration, if any, satisfies rights,
  interface, failure, and exact-target constraints.

Neither selection is an undisclosed weighted average. Required dimensions and
hard thresholds are registered before final evaluation. A rejected hypothesis
and a no-winner outcome are valid results.
