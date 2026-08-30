# Offline model-completion sprint result

Date: 2026-08-30

Outcome: software path completed; model quality rejected

## What now works

- `compact-vio-run` accepts MP4, image ZIP, or timestamped images plus camera
  timestamps, six-axis IMU, calibration, and a model package.
- It integrates relative translation and rotation into a trajectory and writes
  CSV, SVG, self-contained HTML, and JSON outputs.
- `compact-vio-demo` provides a local upload page with a **Run VIO** button.
- The packaged runtime binds frozen TorchVision RAFT-small `C_T_V2`, causal
  gyro rotation, a train-only feature clamp, and a stateless
  `831 -> 128 -> 128 -> 3` translation head.
- The translation head exports to ONNX. Fresh ONNX Runtime parity against
  PyTorch passed at `1e-5` relative and absolute tolerance; observed maximum
  absolute error was `8.20e-8`.
- The package carries its evaluation summary and displays an
  `experimental_rejected` warning in both the CLI and demo.

The local package manifest SHA-256 is
`4125e0d0fd265869d6306c151d00a4cb7f1ba4381db0b2fbdacc3705d3f9247f`.
The translation-head ONNX SHA-256 is
`d2f5facbc547182e45a3459ea30123ad3ee8da4ca1a451ee6503c823c40b30ec`.
Model binaries are retained under
`outputs/raft-hybrid-experimental-20260830/` and are ignored by Git.

## Model result

All metrics are raw and unaligned. `Drift/path` must be at most `2%`; path ratio
must be in `[0.8, 1.2]`. Pair translation, pair rotation, and translation ATE
must each beat the same-sequence zero-motion baseline.

| Sequence | Coverage | Pair t RMSE | Zero pair t | Pair r RMSE | Zero pair r | ATE | Zero ATE | Drift/path | Path ratio | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| V1_03 difficult | 2093/2093 | 0.01382 m | 0.04301 m | 0.000188 rad | 0.03763 rad | 0.68775 m | 2.20797 m | 1.230% | 0.8781 | Pass |
| V2_03 difficult | 1889/1889 | 0.02144 m | 0.05646 m | 0.001460 rad | 0.04827 rad | 1.47895 m | 2.05572 m | 1.771% | 0.8522 | Pass |
| MH03 medium (fresh) | 2630/2630 | 0.03518 m | 0.06121 m | 0.000073 rad | 0.01723 rad | 3.82490 m | 4.67385 m | **3.281%** | **0.5316** | **Reject** |

The model therefore tracks local motion better than zero motion and beats zero
on raw ATE in all three listed sequences, but it underestimates traveled
distance and accumulates too much endpoint drift on the fresh sequence. It is a
runnable experimental model, not the accepted end model.

## Stopped experiments

The bounded follow-ups did not fix the fresh-sequence failure: Machine Hall
head adaptation, closed-form calibration, causal velocity GRU training, a
single scalar correction, and an exact scalar-feasibility check all failed to
produce a candidate meeting every gate. Model tuning was stopped. MH04 and
MH05 were not opened.

## Remaining gap

The user-facing software path is present. The remaining model problem is
translation generalization across sequences, specifically path magnitude and
long-horizon drift. A full image-to-trajectory ONNX graph is also not present;
only the portable translation head is ONNX while RAFT and gyro preprocessing
run through PyTorch/Python. ROS, PX4, and physical hardware integration were
outside this sprint.
