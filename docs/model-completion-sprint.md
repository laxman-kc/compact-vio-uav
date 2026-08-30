# Model completion sprint

Status: Active

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

The selected PyTorch checkpoint must also export to ONNX with checked output
and recurrent-state parity.

## Definition of done

- Full held-out trajectories are evaluated with complete coverage, translation
  ATE, relative translation/rotation error, final drift, and path length.
- The selected checkpoint beats the same-sequence zero-motion control on
  translation ATE, final drift, pair translation error, and pair rotation
  error. Its predicted/reference path-length ratio is within `[0.8, 1.2]`.
- One command accepts a video or timestamped image directory, camera timestamps,
  synchronized six-axis IMU CSV, calibration, and the selected checkpoint.
- The command writes a trajectory CSV, a trajectory visualization, and a
  machine-readable run summary.
- A local upload demo exposes the same inference path without duplicating model
  logic.
- The selected checkpoint exports to ONNX with explicit recurrent-state input
  and output. PyTorch and ONNX Runtime agree within `1e-5` absolute and relative
  tolerance on deterministic parity fixtures.
- The model package includes the selected PyTorch checkpoint identity, ONNX
  model identity, preprocessing/input contract, example command, and evaluation
  summary.

## Focused work

1. Complete full-pose trajectory metrics and trajectory-aware sequence loss.
2. Run focused model iterations and select the first checkpoint meeting the
   definition of done without changing held-out membership after inspection.
3. Add the recording inference command and local upload demo.
4. Add ONNX export and parity validation.
5. Validate the complete user path and update concise user documentation.

## Not in this sprint

- New TUM-VI acquisition, audit, parser, or contract work.
- ROS 2, PX4, SITL, HIL, or flight integration.
- Physical sensor or edge-device selection.
- Jetson-specific optimization or benchmarking.
- A new governance subsystem or broad research-paper reproduction.

Those items may follow only after the offline model package above is complete.
