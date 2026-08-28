# ADR-0004: Training-first compact VIO development slice

- Status: Accepted
- Decision owner: Project owner
- Decision date: 2026-08-28

## Context

The repository foundation is substantially ahead of the estimator itself: it
has causal replay, sensor and calibration contracts, execution recording, and
evaluation primitives, but no real-data adapter, learned estimator, training
loop, checkpoint, or held-out result. The project owner explicitly directed the
project to stop treating documentation and an A/B/C/D reliability study as the
critical path and to execute the real dataset, calibration, model-training, and
evaluation workflow.

The earlier proposal made deterministic reliability-aware C-versus-D testing
the Version 1 contribution and deferred all project-side training until after a
failure atlas. That order is rejected for the development prototype. It remains
useful as later research work after the trained vertical slice is reproducible.

## Decision

Version 1 is a **training-first compact learned VIO development prototype** with
this end-to-end boundary:

1. Use the EuRoC MAV Vicon Room family as the initial development dataset.
2. Consume monocular `cam0` images, the six-axis IMU stream, and the official
   camera/IMU calibration. Ground truth is available only as a training label
   for training membership and as an evaluator reference for validation/test
   membership; it is never an inference input.
3. Validate the official calibration, timestamp relationships, coordinate
   conventions, units, file continuity, and source identity before constructing
   examples. The project consumes dataset calibration; it does not claim to
   have recalibrated EuRoC hardware.
4. Assign complete source sequences to disjoint train, validation, and held-out
   test membership before windowing or normalization. Derived windows from one
   sequence cannot cross those boundaries.
5. Implement a compact PyTorch model with an image-pair CNN encoder, a temporal
   IMU encoder using a declared GRU or Conv1D implementation, zero-initialized
   gated frame-pair fusion, and relative translation plus relative rotation
   outputs. The exact
   layer sizes and encoder variant belong in the versioned development
   configuration, not in this ADR.
6. Prove the pipeline with data inspection and a tiny overfit/forward-backward-
   checkpoint smoke, then run one bounded training configuration. Retain the
   resolved configuration, split manifest, environment, seed, history, and
   selected `checkpoint.pt` outside normal Git history.
7. Run inference on held-out development sequences and report trajectory
   coverage, ATE, RPE, rotation error, latency, and memory under explicitly
   versioned metric semantics. Report failures and partial trajectories.

Exact sequence membership, download URLs, archive/file hashes, sizes,
preprocessing values, model dimensions, loss weights, optimizer settings,
batch size, epochs, checkpoint rule, and numerical evaluation policies are
development configuration and manifest values. They must be recorded before
the applicable operation, but changing them during honest development does not
rewrite this architectural decision or silently create a scientific final test.

## Research boundary

The first successful output is a **trained development prototype**. It proves
only that the declared data-to-checkpoint-to-held-out-evaluation path executes
reproducibly on the recorded development split. It is not, by itself:

- a publishable superiority claim;
- a statistically confirmed UAV-population result;
- an onboard latency, power, or thermal claim;
- an ONNX/TensorRT parity result; or
- authorization for ROS 2, PX4, motor control, or physical flight.

A publishable claim requires a separately frozen confirmatory protocol and
untouched test membership. Deployment and flight readiness remain governed by
ADR-0006 and the staged safety gates.

## Later research ablations

The earlier A/B/C/D-monitor/D design is retained as optional follow-up research,
not as a prerequisite for the training-first slice:

- A: fast visual-motion measurements plus IMU;
- B: learned visual measurements plus IMU;
- C: complementary visual channels under fixed fusion;
- D-monitor: C plus diagnostics without intervention; and
- D: C plus one predeclared reliability intervention.

Those comparisons require their own shared-backend fairness configuration,
rights review, native classical reference, controls, and confirmatory freeze.
They must not be inferred from the learned prototype's metrics.

## Rejected alternatives

- **A/B/C/D before any training:** rejected because it delays the explicitly
  required real learned-estimator workflow.
- **No project-side Version 1 training:** rejected by the project owner's
  2026-08-28 direction.
- **Train on window-random splits:** rejected because sequence leakage would
  invalidate held-out evidence.
- **Build deployment and flight integration in the same slice:** rejected
  because offline training does not establish target or safety fitness.

## Consequences

- Dataset ingestion, calibration validation, model code, training, checkpoint
  loading, and held-out evaluation are now the implementation critical path.
- PyTorch is selected for this learned-development lane. Exact dependency and
  CUDA versions remain environment/run-manifest facts.
- Existing framework-neutral replay, contracts, recorder, artifact policy, and
  evaluation primitives remain reusable; they do not need to be expanded before
  the first smallest end-to-end training slice unless the slice exposes a
  concrete missing behavior.
- A native classical baseline, reliability handling, learned uncertainty,
  compression, ONNX, and target deployment are later evidence-driven work.
- Failed training or weak accuracy is a valid development result and must not be
  hidden by changing test membership.

## Evidence

Required implementation evidence:

- Official-source and rights record plus acquisition identity for every used
  EuRoC unit.
- Validated EuRoC `cam0`/IMU/calibration adapter and source-sequence split
  manifest.
- Dataset/sample inspection and overfit smoke evidence.
- Versioned PyTorch environment and resolved train configuration.
- Restorable checkpoint with provenance and checksum.
- Held-out trajectories, coverage/failure accounting, metric report, and
  resource measurements.

The existing [decision brief](evidence/0004-decision-brief.md) remains a
historical, non-authoritative analysis of the superseded reliability-first
proposal. It is not evidence that the training-first implementation has run.

## Follow-up

- Complete the M6–M9 data, training, checkpoint, and held-out-evaluation path.
- Decide M10 baselines or reliability ablations only from observed prototype
  evidence.
- Freeze a separate untouched protocol before any publishable comparison.

Reopen or supersede this ADR if the development dataset cannot support the
declared inputs/labels, the model boundary materially changes, or the project
owner changes the primary development objective. Ordinary configuration tuning
does not reopen it.
