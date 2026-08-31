# ADR-0007: RAFT, gyro, and compact translation-head runtime

- Status: Accepted
- Decision owner: Project owner
- Decision date: 2026-08-30

## Context

ADR-0004 created a real, reproducible learned image-pair CNN + IMU recurrent prototype. That lane
proved the training and evaluation workflow, but its integrated trajectory remained worse than a
zero-motion reference on the primary development sequence.

The project owner then directed a one-day model-completion sprint focused on a useful offline
camera + IMU trajectory model, ONNX export, and a simple upload/run experience. The implemented
candidate materially changed the model boundary: frozen RAFT optical flow and causal gyro
integration became the motion frontend, while a small learned head predicted translation.

The public architecture must describe the runnable candidate rather than silently continuing to
present the earlier experiment as the active model.

## Decision

The current offline candidate is a compact hybrid VIO pipeline:

1. accept one calibrated monocular camera stream and one synchronized six-axis IMU stream;
2. use frozen TorchVision RAFT-small `C_T_V2` to estimate dense optical flow;
3. integrate causal gyro samples and remove predicted image rotation from the flow;
4. aggregate a fixed 10 × 16 residual-flow grid plus IMU context into 831 features;
5. apply normalization/range clamps derived only from training data;
6. predict previous-IMU-frame translation with a stateless `831 → 128 → 128 → 3` GELU MLP;
7. use gyro-derived relative rotation and integrate a raw local SE(3) trajectory;
8. package the exact weights, contracts, translation-head ONNX, and evaluation summary together.

The UI and command-line runner must use this same packaged implementation. Execution success and
model accuracy must remain separate statuses.

## Quality decision

The candidate passed the two development sequences and failed the separately held-out MH_03
sequence on path-length ratio and normalized final drift. The package is therefore retained as
`experimental_rejected`, not as an accuracy-accepted model.

The software may be used to reproduce the pipeline, test recordings, and inspect rough motion
trends with an explicit warning. It must not be described as reliable distance/position
measurement, navigation, control, deployment, or flight readiness.

## ONNX boundary

The compact translation head exports to ONNX with checked PyTorch/ONNX Runtime parity. RAFT,
calibration/rectification, timestamped gyro preprocessing, feature construction, and trajectory
integration remain host/PyTorch code. The project must say “translation-head ONNX,” not “full VIO
ONNX.”

## Consequences

- ADR-0004 remains historical evidence for the completed original learned prototype, but no longer
  defines the current runnable model architecture.
- The current architecture, model card, README, demo, and package must agree on this hybrid model.
- Model binary publication remains gated by ADR-0001 rights/licensing review.
- A fresh untouched-sequence pass is required before the candidate can be called quality accepted.
- Jetson, TensorRT/full-pipeline export, ROS 2, PX4, and flight remain outside this decision.

## Evidence

- [Offline model completion report](../../reports/offline-model-completion-sprint-2026-08-30.md)
- [Model completion sprint](../model-completion-sprint.md)
- Package evaluation summary bound by the local checked manifest
- V1_03, V2_03, and one-shot MH_03 result artifacts recorded by the sprint

## Rejected alternatives

- Presenting the original ADR-0004 CNN/GRU model as the active runtime is rejected because it does
  not match the packaged code.
- Calling the candidate accepted because it runs is rejected because the final accuracy gate
  failed.
- Shipping a GRU or post-hoc calibration candidate is rejected because no tested variant passed
  all frozen gates.
- Treating translation-head ONNX as a complete deployable graph is rejected.

## Follow-up

Improve distance/drift generalization under a predeclared untouched-sequence protocol. Revisit
deployment only after the offline candidate passes that quality gate and a rights-reviewed model
artifact can be distributed.
