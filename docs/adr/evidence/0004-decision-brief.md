# ADR-0004 decision brief

Status: Recommendation for project-owner review; non-authoritative

This brief supplies the literature-backed scope, claim-to-evidence matrix, and
negative-control matrix requested by
[ADR-0004](../0004-primary-research-contribution.md). It does not accept that ADR
or select an implementation. Only a dated owner decision can do that.

## Recommended research scope

### Target phenomenon

The recommended primary phenomenon is **time-localized degradation of visual-
correspondence reliability during causal metric-scale local UAV VIO**, with
predeclared strata for:

- High apparent image motion or motion blur.
- Poor, changing, or spatially non-uniform illumination.

This is narrower than "all UAV failures." Low texture, vibration, dynamic
objects, total visual loss, timing faults, calibration faults, and IMU faults
remain separate discovery or stress families unless a later protocol revision
brings one into scope. Timing and IMU faults are useful specificity controls;
the proposed visual action must not be claimed to repair them.

### Target population

The recommended primary population is **complete, causally replayable, metric-
ground-truthed camera–IMU UAV source groups assigned before use to one or more
accepted visual-degradation strata and evaluated as local VIO without loop
closure**. Target-absent nominal source groups form a separate guardrail
population; they are not pooled into or reweighted within the primary
degradation estimand.

This wording does not select a dataset, camera count, sequence, physical
sensor, or corruption generator. A future dataset decision must prove that its
exact unit can represent the accepted population. Results may generalize only
to the independently sampled source groups and conditions actually covered by
the frozen protocol.

### Primary endpoint family

The recommended family is **full-run, failure-aware local-trajectory
reliability**. The primary D-versus-C estimand is a paired contrast in retained
failure-free operation or usable-output coverage over the complete causal
replay for the accepted target population.

Before final-test access, the confirmatory protocol must select exactly one
coordinate within this family—time, traveled distance, or declared output
opportunity—and freeze its event, censoring, missing-output, aggregation, and
uncertainty rules. Initialization failure, tracking loss, stale or invalid
output, reset, recovery, and incomplete output remain visible outcomes; a
surviving trajectory prefix cannot stand in for the complete run.

Mandatory secondary and guardrail families are:

- Metric-scale absolute and relative translational/rotational trajectory error
  under the common frozen association and alignment policy, without Sim(3)
  scale correction for the primary metric-scale claim.
- Nominal-condition accuracy and coverage.
- Processing latency, memory, and declared compute-budget use on the stated
  execution platform.

This brief selects no numerical metric threshold, failure threshold, weighted
score, trial count, statistical test, or action threshold.

### Independent experimental unit

The recommended independent unit is **one independently acquired parent
flight/trajectory source group**: the maximal group of sensor streams that
share one raw physical-acquisition ancestry. Every rendered, corrupted, or
otherwise perturbed variant remains nested under that source group regardless
of how many perturbation realizations exist.

C, D-monitor, and D are paired repeated treatments on the same immutable causal
replay. Frames, IMU samples, poses, relative-pose pairs, overlapping windows,
camera views, rendered/corrupted variants, severity levels, seeds, restarts,
and repeated executions are nested observations or technical replicates; they
do not increase the inferential sample size. When multiple trajectories share
a higher-level session or acquisition process that is the level sampled by the
claim, that level remains an analysis cluster.

## Primary comparison and falsification rule

The recommended primary comparison remains D versus C. D-monitor is a required
mechanism control:

- C versus D measures the complete monitoring-plus-action package.
- C versus D-monitor measures diagnostic and monitoring perturbation.
- D-monitor versus D isolates the action contribution under identical
  diagnostics.

The hypothesis is not supported when D fails to improve the frozen primary
endpoint over C in the accepted target population, or when D violates a frozen
nominal accuracy, coverage, or resource guardrail. A null or harmful result is
valid evidence and does not authorize changing the endpoint or population
after final-test inspection.

Exact margins and decision thresholds belong to the later confirmatory freeze,
not this scope recommendation.

## Same-backend fairness contract

All A/B/C/D-monitor/D configurations must hold these fields fixed:

- Source-group and causal-input identities, record order, timestamps,
  modalities, calibration, and preprocessing.
- Each visual-channel implementation and imported weight set whenever that
  channel is enabled; channel-specific preprocessing may not change between
  configurations that use the channel.
- The track identity/provenance representation, backend observation contract,
  candidate eligibility rules, and capacity/resource ceiling.
- Initialization, IMU path, state definition, backend factors, robust loss,
  optimizer, numerical settings, reset/stopping policy, and output
  opportunities.
- Evaluator, association/alignment/interpolation policy, software revision,
  dependencies, toolchain, execution platform, seed policy, and external
  resource limits.

Differing visual evidence is the declared treatment in A/B/C: A enables only
the fast visual-motion channel, B enables only the frozen learned-landmark
channel, and C enables both plus the one frozen correlation/duplicate policy.
The IMU path, backend, evaluator, and other invariants above do not change.

D-monitor and D both add the identical diagnostics implementation and
configuration to C. D-monitor may record the action that would have been
requested but must not change measurement weights, acceptance, backend inputs,
estimator state, reset behavior, or outputs. D and D-monitor may differ only
through the one deterministic action frozen for the applicable protocol. Thus
C versus D measures monitoring plus action, while D-monitor versus D isolates
the action.

Do not force realized accepted-measurement counts or weights to be equal across
configurations: channel availability differs in A/B/C, and changing acceptance
or weight is the D action's proposed mechanism. Freeze the candidate stream,
eligibility/capacity policy, and external resource ceiling applicable to each
declared comparison. Retain realized actions, weights, accept/reject counts,
downstream state divergence, latency, and resource use as mediators or
outcomes. Randomize or counterbalance execution order within platform/session
blocks so cache, temperature, system load, and time drift are not confused with
the treatment effect.

## Claim-to-evidence matrix

| Proposed claim | Minimum supporting evidence | Evidence that is insufficient |
|---|---|---|
| D improves full-run reliability over C under the target visual degradation | Paired complete-run C/D evidence on sealed source groups; frozen primary endpoint, missing/failure rules, and nominal/resource guardrails | Best-run output, surviving-prefix ATE, unpaired datasets, or thresholds chosen after results |
| The deterministic action, rather than monitoring alone, causes the change | D-monitor/D paired contrast with identical diagnostics and recorded actions | D/C alone or diagnostics produced by different code |
| A and B supply complementary evidence in C | A/B/C results under one backend; channel provenance; unique accepted evidence; explicit correlation/deduplication accounting | More raw matches, a paper benchmark, or C using a different backend/budget |
| D does not impose unacceptable nominal harm | Target-absent nominal C/D runs under frozen accuracy, coverage, latency, memory, and compute guardrails | Degraded-condition improvement alone |
| The result applies beyond one sequence | Per-unit results and uncertainty across independently acquired parent groups representing the accepted population | Frames, windows, seeds, corruptions, or repeated executions counted as independent units |

The brief does not propose a covariance or calibrated-uncertainty claim. A
health or reliability signal remains distinct from covariance until separate
state, frame, propagation, and calibration evidence exists.

## Negative-control matrix

| Control | Purpose | Required interpretation |
|---|---|---|
| D-monitor | Separate diagnostic overhead from action effect | A C/D-monitor difference is monitoring perturbation, not action benefit |
| Target-absent nominal C/D | Detect false actions and nominal harm | A guardrail, not positive robustness evidence |
| Harness-null | Verify identical input hashes, order, timestamps, calibration, evaluator, and opportunity accounting | Failure invalidates the comparison before scientific interpretation |
| Timing/IMU specificity family | Test whether a visual-reliability claim is being overgeneralized | D need not repair nonvisual faults; apparent repair requires mechanism review |
| Optional discovery-only deterministic pseudo-signal | Test the action path independently of current visual health | Never a confirmatory control unless frozen before final-test access |

An oracle signal using ground truth or future data may be used only as a
clearly labelled discovery upper bound. It is not a causal deployable
configuration and cannot support the primary claim.

## Discovery and confirmation boundary

Discovery may expose every endpoint component and per-unit paired contrast,
build the failure atlas, and compare candidate coordinates, diagnostics, and
actions using development/discovery membership only.

Before confirmation, freeze the target population, unit inclusion/grouping,
one primary endpoint coordinate, event/failure taxonomy, missing-output rule,
single D action, run order, resource ceiling, aggregation, uncertainty method,
and guardrail decisions. Then execute every registered final-test unit and
report all failures and deviations. D versus C remains the sole primary
contrast; D-monitor is mechanistic secondary evidence.

## Owner decision checklist

ADR-0004 remains `Proposed` until the project owner records a date and accepts
or rejects each item:

1. The target phenomenon and target population above.
2. Full-run, failure-aware local-trajectory reliability as the primary endpoint
   family.
3. Parent acquisition group as the independent experimental unit.
4. D versus C as the primary comparison and D-monitor as required control.
5. The same-backend fairness contract and later single-action freeze.
6. Removal of direct learned VIO from the critical path.
7. No project-side training in Version 1.

Acceptance still does not choose a dataset, sequence, mono/stereo setup,
backend, visual method, learned component, reliability signal, action,
threshold, framework, compute budget, deployment target, or flight scope.

## Source map and limits

- [Visual-Inertial Odometry of Aerial Robots](https://arxiv.org/abs/1906.03289)
  establishes the camera–IMU aerial-odometry problem boundary; it does not
  choose this project's state or implementation.
- [EuRoC MAV dataset paper](https://doi.org/10.1177/0278364915620033),
  [official dataset page](https://projects.asl.ethz.ch/datasets/euroc-mav/),
  and the [UZH-FPV paper](https://rpg.ifi.uzh.ch/docs/ICRA19_Delmerico.pdf)
  document MAV sequences with illumination, blur, and high-apparent-motion
  challenges. They support the phenomenon recommendation, not dataset
  approval.
- [Robust SLAM Systems: Are We There Yet?](https://arxiv.org/abs/2109.13160)
  supports condition-stratified robustness evaluation and independent versus
  combined perturbations; it does not define this project's VIO endpoint.
- [Characterizing SLAM Benchmarks and Methods](https://arxiv.org/abs/1905.07808)
  supports failure-atlas and component-level profiling; it does not establish
  a causal benefit for D.
- [Selective Sensor Fusion for Neural VIO](https://arxiv.org/abs/1903.01534)
  provides mechanism plausibility for selective handling under corrupted or
  missing data. It is end-to-end learned vision–IMU fusion, not the proposed
  modular dual-visual experiment.
- [A Benchmark Comparison of Monocular VIO Algorithms for Flying Robots](https://rpg.ifi.uzh.ch/docs/ICRA18_Delmerico.pdf)
  supports joint accuracy, latency, CPU, and memory reporting. It does not
  select monocular sensing or an implementation here.
- [NIST paired-observation guidance](https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm)
  supports natural C/D pairing, while
  [NIST randomized-block guidance](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm)
  supports blocking controlled nuisance factors and randomizing the rest.

No cited source exactly tests the proposed C/D dual-visual architecture with a
shared backend, D-monitor, causal replay, complete-run accounting, and no-Sim(3)
metric-scale evaluation. That gap is why this remains a falsifiable proposal
rather than an accepted scientific claim.
