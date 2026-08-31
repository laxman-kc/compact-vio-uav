# CompactVIO RAFT-hybrid model card

## Model status

- Package status: `experimental_rejected`
- Software status: runnable offline candidate
- Quality status: failed the frozen held-out acceptance gate
- Distribution status: local package only; no public download is available
- Output: relative translation + gyro-derived rotation integrated into a local 6-DoF trajectory

## Architecture

The current candidate uses:

1. frozen TorchVision RAFT-small `C_T_V2` optical flow;
2. causal gyro integration and image-rotation compensation;
3. a fixed 10 × 16 grid of residual-flow statistics plus IMU context (831 values);
4. a stateless `831 → 128 → 128 → 3` GELU translation MLP with 123,395 parameters;
5. feature-range clamps derived only from training data to prevent unsupported normalized
   extrapolation during inference;
6. raw SE(3) integration in the local IMU sensor frame.

The translation head has an ONNX export with PyTorch/ONNX Runtime parity. RAFT, calibration,
timestamp handling, gyro preprocessing, and trajectory integration remain host/PyTorch code; this
is not a full-pipeline ONNX model.

## Evaluation gate

Every evaluated sequence must have complete coverage. The candidate must:

- beat same-sequence zero motion on raw translation ATE;
- beat zero motion on pair translation RMSE;
- beat zero motion on pair rotation RMSE;
- keep predicted/reference path length in `[0.8, 1.2]`;
- keep final translation drift at or below 2% of reference path length.

## Results

| Sequence | Role | Coverage | Pair translation RMSE | Raw ATE | Path ratio | Normalized drift | Result |
|---|---|---:|---:|---:|---:|---:|---|
| V1_03 difficult | Development | 100% | 0.01382 m | 0.68775 m | 0.8781 | 1.230% | Pass |
| V2_03 difficult | Development | 100% | 0.02144 m | 1.47895 m | 0.8522 | 1.771% | Pass |
| MH_03 medium | Held-out final | 100% | 0.03518 m | 3.82490 m | 0.5316 | 3.281% | **Fail** |

On MH_03, zero-motion ATE was 4.67385 m and pair translation RMSE was 0.06121 m, so the candidate
did improve local motion over zero. It still failed total-distance scale and long-horizon drift,
which are necessary for useful odometry.

## Intended use

- Reproduce and inspect the offline camera + IMU inference pipeline.
- Test recording ingestion, model packaging, ONNX-head export, and result reporting.
- Explore rough local motion trends in research recordings with an explicit warning.

## Not intended for

- distance or position measurement;
- navigation, autonomy, control, or obstacle avoidance;
- ROS/PX4 integration or physical flight;
- claims of state-of-the-art accuracy or faithful reproduction of a cited paper.

## Known limitations

- Generalization failed on the fresh Machine Hall sequence.
- Distance was underestimated by 46.8% on the final test.
- Uploaded recordings do not include ground truth, so their accuracy is not measurable in the UI.
- The package is local and Git-ignored; a fresh clone does not include trained weights.
- The full vision + IMU pipeline is not one portable ONNX graph.
- The repository does not yet provide a public RAFT-hybrid training command that reproduces the
  packaged head; the retained `compact-vio-train` command belongs to the historical CNN/GRU lane.

See the [offline completion report](../reports/offline-model-completion-sprint-2026-08-30.md) and
the [history index](history/README.md) for detailed evidence and stop rules.

## Interpretation

This model is useful for exercising the complete upload-to-trajectory workflow and for research on
the remaining generalization problem. It is not a finished odometry model. A successful upload
means the software produced an estimate; it does not change the rejected benchmark verdict.
