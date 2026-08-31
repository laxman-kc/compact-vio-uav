# Understanding the output

## Two different questions

The app deliberately reports two independent statuses:

1. **Trajectory created** means the recording was parsed, the model ran, and result files were
   written.
2. **Accuracy** asks whether the path is close to the real motion. An ordinary upload has no
   ground truth, so its individual accuracy is unknown.

A successful run is not evidence that the estimate is correct.

## Result metrics

- **Estimated distance travelled:** sum of all predicted translation-step lengths.
- **Start-to-end distance:** straight-line displacement between the first and final estimated pose.
- **Frames processed:** camera frames accepted by the run.
- **Processing time:** local input loading, decoding, model inference, and pose integration through
  trajectory creation. It excludes writing and downloading the result files.

The chart is a raw local-frame integration. It has no GPS alignment, global map, smoothing, scale
fit, or loop closure. The first pose is defined as `(0, 0, 0)`.

## Current model warning

The package passed both development sequences but failed the separate MH_03 held-out sequence. On
that test it estimated 69.5 m for a 130.7 m reference path, 46.8% short. Its endpoint drift was
4.29 m, or 3.28% of path length, above the frozen 2% limit.

That is why the UI says to use an uploaded result only for exercising the workflow or inspecting a
rough motion trend—not as a distance, position, or navigation measurement.

## Downloads

`compact-vio-result.zip` contains:

- `summary.html` — readable trajectory and model-quality explanation;
- `summary.json` — machine-readable run facts and quality assessment;
- `trajectory.csv` — timestamped poses and relative motion steps;
- `trajectory.svg` — standalone trajectory chart.

The individual files are also available under **Individual result files**.

## `trajectory.csv` contract

Each row is one camera pose. The first row is the identity pose and has zero motion increments.

| Columns | Meaning |
|---|---|
| `timestamp_ns` | Camera timestamp in integer nanoseconds |
| `x_m`, `y_m`, `z_m` | Integrated position in the local start frame, metres |
| `qw`, `qx`, `qy`, `qz` | Integrated orientation quaternion in scalar-first order |
| `delta_x_previous_m`, `delta_y_previous_m`, `delta_z_previous_m` | Relative translation expressed in the previous IMU sensor frame |
| `delta_rx_rad`, `delta_ry_rad`, `delta_rz_rad` | Relative rotation vector in radians |

The relative increments are model outputs; the global position and quaternion are their raw causal
integration. A CSV row is not an independently measured pose.

## `summary.json` contract

The stable top-level facts include:

- `run_status`, `sequence_id`, `frames`, and `predicted_pairs`;
- `recording_duration_s`, `runtime_s`, and `mean_runtime_ms_per_pair`;
- `predicted_path_length_m` and `final_displacement_m`;
- `trajectory_convention`, `motion_frame`, and calibration identity/usage;
- `backend_id`, `model_identity`, and packaged `quality_status`;
- `accuracy_for_this_recording`, which remains `unverified_without_ground_truth` for a normal
  upload;
- `model_quality`, a structured copy of the packaged benchmark assessment.

`run_status: completed` describes execution only. It must not be interpreted as an accuracy pass.
The packaged benchmark can be rejected while a recording run completes successfully.

Next: read the [model card](model-card.md), inspect the [current architecture](architecture.md), or
return to [Getting started](getting-started.md).
