# Research protocol

Status: Draft; primary hypothesis and numerical thresholds unresolved
Last reviewed: 2026-08-26

## 1. Protocol freeze points

1. Accept the project/release, estimator, sensor, and primary-contribution ADRs.
2. Approve dataset roles, rights, source groups, and split manifests.
3. Validate the common causal replay and evaluator with negative controls.
4. Reproduce selected classical references.
5. Freeze primary metrics, failure policy, thresholds, seeds/trials, and candidate budget.
6. Evaluate novel candidates and select without modifying the frozen final-test protocol.
7. Open export, target, and integration gates only for an evidence-selected candidate.

Changes after a freeze require a new protocol revision. Results produced under different revisions must not be pooled without disclosure.

## 2. Hypothesis registration

Before candidate implementation, record:

- One primary hypothesis with a falsifiable direction.
- Primary comparator.
- Target sequence/sensor/domain population.
- Independent experimental unit.
- Primary endpoint and units.
- Acceptance and rejection thresholds.
- Repeated seeds/trials and aggregation method.
- Experiment and compute budget.
- Stopping rule.
- Allowed exploratory metrics.

No primary hypothesis is selected in this foundation.

## 3. Data protocol

- Assign source groups before any derived samples are created.
- Keep related views, renders, weather variants, corruptions, windows, and underlying flights in one split unless an accepted protocol explicitly tests cross-variant transfer.
- Fit normalization and learned preprocessing on training data only.
- Use validation data for declared tuning only.
- Do not inspect final-test outputs until the protocol is frozen.
- Record imported model pretraining sources and check their overlap with evaluation data.
- Preserve exact dataset, calibration, preprocessing, and split-manifest hashes in each run.

## 4. Causality and estimator fairness

- Deliver sensor records in timestamp order.
- Emit an estimate no earlier than the newest measurement required to compute it.
- Prohibit future frames, future IMU samples, bidirectional recurrence, and full-sequence normalization in an online claim.
- Apply equivalent calibration access, sensor modalities, loop-closure policy, resets, and evaluation intervals to comparable candidates.
- Report algorithmic delay separately from wall-clock processing delay.
- Replay complete sequences, including initialization and post-reset behavior.

## 5. Required candidate controls

The accepted hypothesis determines the final set. A learned multimodal study normally requires:

- A classical filter reference.
- A classical optimization reference where compatible with scope.
- A visual-only diagnostic.
- An IMU-only diagnostic.
- An always-compute causal visual-inertial diagnostic.
- The proposed candidate and ablations isolating its claimed contribution.

Named implementations and versions remain unresolved until estimator, sensor, and license ADRs are accepted.

## 6. Evaluation

### Trajectory

Report per sequence and in predeclared aggregates:

- Translational and rotational absolute trajectory error where ground truth supports them.
- Relative pose error at declared time and distance intervals.
- Scale ratio and scale drift.
- Initialization success and time.
- Coverage/completion.
- Tracking loss, restart count, and time/distance to first failure.

A metric-scale primary claim cannot use Sim(3) scale correction. Alignment, interval, interpolation, ground-truth gaps, and failure penalties must be frozen.

### Uncertainty and health

If covariance is claimed, define its state and frame and evaluate likelihood, empirical coverage, sharpness, and consistency under nominal and perturbed inputs. Evaluate health/failure detection separately. A generic confidence score is not covariance.

### Resources

Record p50/p95/p99/max sensor-to-pose latency, deadline misses, throughput, queueing, input drops, peak memory, and relevant utilization. Power, energy, temperature, and throttling claims require the actual target device and sustained operation.

## 7. Robustness

Perturbations must represent declared failure modes and preserve a clean reference. Candidate classes include blur, exposure degradation, frame loss, timestamp offset/jitter, IMU gaps, noise, bias, saturation, calibration perturbation, and resource slowdown. Severity selection uses training/validation evidence, never final-test results.

## 8. Statistical and reporting rules

- Report all predeclared seeds/trials, not the best run.
- Keep per-sequence results visible alongside aggregates.
- Distinguish confirmatory and exploratory results.
- Include effect size and uncertainty appropriate to the experimental unit.
- Do not treat overlapping windows from one trajectory as independent experimental units.
- Preserve failed-run configuration and diagnosis.
- Record protocol deviations before interpreting the result.

## 9. Candidate selection

Maintain separate decisions for:

- Scientific winner: strongest evidence for the primary hypothesis.
- Deployable winner: best feasible combination of accuracy, failure behavior, rights, interfaces, and target-resource measurements.

Neither selection may be reduced to an undisclosed weighted average. Required dimensions and hard thresholds must be registered before final evaluation.
