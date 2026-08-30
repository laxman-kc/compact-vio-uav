# Model completion sprint

Status: Software complete; model quality rejected

## Outcome

Finish the current offline compact-VIO model phase with one runnable path:

```text
recording + synchronized IMU + calibration
                    |
              selected model
                    |
           integrated 6-DoF trajectory
                    |
       CSV + visualization + runtime summary
```

The runnable package uses PyTorch/TorchVision for RAFT and gyro processing. Its
stateless translation head exports to ONNX with checked output parity. A full
image-to-trajectory ONNX graph was not produced.

## Definition of done

- Full held-out trajectories are evaluated with complete coverage, translation
  ATE, relative translation/rotation error, final drift, and path length.
- The selected checkpoint has complete pair coverage, beats the same-sequence
  zero-motion control on translation ATE, pair translation error, and pair
  rotation error, and keeps raw final translation drift at or below `2%` of
  the reference path length. Its predicted/reference path-length ratio is
  within `[0.8, 1.2]`.

  Final drift is normalized by reference path length instead of compared with
  zero motion because a near-closed trajectory makes the zero-motion endpoint
  error artificially small: it measures start-to-end displacement rather than
  whether the intervening path was tracked. This is still a raw, unaligned,
  unscaled endpoint bound; it does not add loop closure or post-processing.
- One command accepts a video or timestamped image directory, camera timestamps,
  synchronized six-axis IMU CSV, calibration, and the selected checkpoint.
- The command writes a trajectory CSV, a trajectory visualization, and a
  machine-readable run summary.
- A local upload demo exposes the same inference path without duplicating model
  logic.
- The translation head exports to ONNX. PyTorch and ONNX Runtime agree within
  `1e-5` absolute and relative tolerance on deterministic parity fixtures.
- The model package includes the selected PyTorch checkpoint identity, ONNX
  model identity, preprocessing/input contract, example command, and evaluation
  summary.

## Completed work

1. Full-pose trajectory metrics and trajectory-aware training were added.
2. The bounded model iterations and fresh-sequence evaluation were completed.
3. `compact-vio-run` accepts an MP4, image ZIP, or timestamped image directory
   plus synchronized IMU and calibration, then writes CSV/SVG/HTML/JSON.
4. `compact-vio-demo` provides a local upload-and-run interface.
5. The translation head has a checked ONNX export and the complete local model
   package binds the TorchVision RAFT weights, head, clamp, ONNX, input contract,
   and evaluation summary.

## Final sprint result

The V1_03 development gate selected the first compact RAFT/IMU candidate that
meets the corrected definition above. It uses frozen TorchVision RAFT-small
`C_T_V2` flow features, causal gyro rotation, and a stateless
`831 -> 128 -> 128 -> 3` translation head with 123,395 trainable parameters.
The head file SHA-256 is
`bbb9c85a33af81347fd8044438190b42e501fe5be72ba553e8a7265ecf2ca2c5`.

On all 2,093 V1_03 pairs it produced raw translation ATE `0.695041 m`
(zero motion `2.207973 m`), pair translation RMSE `0.014335 m` (zero
`0.043006 m`), pair rotation RMSE `0.000188 rad`, path-length ratio `0.8811`,
and final translation drift `1.060922 m`, or `1.344%` of the `78.920 m`
reference path. The model was frozen before any V2_03 or MH03 evaluation.

A training-only feature-range clamp fixed a previously unbounded
standardization extrapolation without changing the head weights. The corrected
candidate passed V1_03 and V2_03, then completed the one-shot MH03 evaluation
over all 2,630 pairs. On MH03 it beat zero motion on raw ATE (`3.82490 m`
versus `4.67385 m`) and pair translation/rotation error, but failed the frozen
path and endpoint gates: path ratio `0.531632` and normalized final drift
`3.281%`. It is therefore rejected as the final quality-selected model.

The planned bounded follow-ups were completed and stopped: Machine Hall
head-only adaptation, closed-form calibration, a causal velocity GRU, one
scalar correction, and an exact scalar-feasibility check produced no candidate
that passed all gates on both development sequences. No GRU or calibration
replacement was selected. `MH_04_difficult` and `MH_05_difficult` remain
unopened.

The code deliverable is nevertheless runnable as an explicitly
`experimental_rejected` package. It can process a recording and produce a
trajectory, and the UI shows the rejection warning rather than presenting the
model as accepted. The local package manifest is
`outputs/raft-hybrid-experimental-20260830/model-package/manifest.json`; binary
model artifacts remain ignored by Git and are not included in a fresh clone.

## Not in this sprint

- New TUM-VI acquisition, audit, parser, or contract work.
- ROS 2, PX4, SITL, HIL, or flight integration.
- Physical sensor or edge-device selection.
- Jetson-specific optimization or benchmarking.
- A new governance subsystem or broad research-paper reproduction.

Those items may follow only after the offline model package above is complete.
