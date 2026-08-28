# Research protocol

Status: Active development protocol; confirmatory protocol remains unresolved
Last reviewed: 2026-08-28

## 1. Freeze points

### Research-scope freeze

ADR-0004 is the accepted development-scope freeze. It selects the EuRoC Vicon
Room `cam0` plus six-axis IMU vertical slice, source-sequence-disjoint
development membership, compact PyTorch relative-motion training, checkpoint
retention, and held-out evaluation. Versioned manifests/configuration own exact
archive identity, sequence membership, preprocessing, model dimensions,
optimization, and checkpoint selection. The development prototype is not a
publishable superiority claim or a deployment/flight decision.

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

Execute the accepted vertical slice in this order:

1. Acquire and verify the two official EuRoC Vicon Room archives.
2. Extract `cam0`, `imu0`, official calibration, and Vicon reference states.
3. Parse and validate every selected physical sequence without hidden repairs.
4. Freeze the development split before producing frame pairs.
5. Build consecutive-frame examples with exactly the IMU window in
   `(previous_timestamp, current_timestamp]` and training-only targets.
6. Pass a forward/backward/checkpoint smoke, then train the bounded compact
   CNN + IMU GRU + fusion model on the A10.
7. Select only by the declared validation loss and evaluate the selected
   checkpoint once on held-out development membership.
8. Export checkpoint, resolved configuration, data/calibration hashes,
   training history, predictions, held-out metrics, latency/resources, and all
   observed failures.

A/B/C/D reliability experiments, a native classical reference, failure-atlas
work, deployment export, and flight integration are later branches. They do not
block the real training prototype and are not inferred from its result.

## 5. Learned training and imported components

Before configuration B incorporates a frozen component, record its source,
commit/release, code and weight hashes, licence/redistribution terms, training
data disclosure, preprocessing, inference settings, and known benchmark overlap.
Paper performance is not incorporation evidence.

For the accepted learned prototype, record PyTorch/CUDA versions, accelerator,
determinism controls, model/configuration ID, source-sequence split and archive
hashes, calibration hashes, seed, stopping rule, and checkpoint-selection rule.
Run a small forward/backward/save-load smoke before the bounded GPU run.
Training uses only declared training membership; validation selects the
checkpoint; held-out development test data never selects it. A tracking tool
may mirror metrics but is not the authority.

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
