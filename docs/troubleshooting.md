# Troubleshooting

## The demo says no model package is configured

Pass the current package manifest when launching the app:

```bash
compact-vio-demo --model-package /path/to/model-package/manifest.json
```

The experimental package is Git-ignored and is not included in a fresh clone.
There is currently no public download command. The built-in synthetic example
generates sensor inputs, not model weights, so it also needs a configured model
package.

## The model path exists locally but fails verification

Point `--model-package` at `manifest.json`, not at a `.pt` or `.onnx` file. Keep
every package artifact beside the manifest with its original filename. If an
external manifest SHA-256 was supplied, verify that it identifies the same raw
file bytes.

Use `--checkpoint` only for the historical CNN/GRU model path. A legacy
checkpoint cannot be substituted for a RAFT-hybrid manifest.

## MP4 input asks for camera timestamps

MP4 containers do not supply the required sensor timestamps. Add a camera CSV:

```csv
timestamp_ns
2000000000
2050000000
```

Alternatively, upload timestamp-named images in a recording bundle. See
[Input formats](input-formats.md).

## The IMU has insufficient pre-roll

Include at least two IMU samples strictly before the first camera timestamp.
Keep the camera and IMU stationary during a 1–2-second pre-roll. The runtime
uses the mean pre-frame gyro reading as its bias estimate, so moving during
that period can corrupt later rotation estimates. IMU timestamps must be
strictly increasing and overlap the camera stream.

## Calibration or image resolution is rejected

Every source frame must exactly match `camera.resolution` in the calibration
file. The runtime performs its own rectification and resize; it does not silently
accept a mismatched source resolution.

The current hybrid also requires:

- pinhole camera model;
- radtan distortion;
- a valid camera-to-IMU `T_BS`;
- identity `imu.T_BS`.

Start from
[`configs/raft-hybrid-calibration.example.json`](../configs/raft-hybrid-calibration.example.json).

## A recording bundle is rejected

The bundle must contain `frames/`, `imu.csv`, and `calibration.json`, optionally
inside one wrapper directory. The reader rejects absolute paths, `..` traversal,
symlinks, encrypted members, case-insensitive duplicates, ambiguous calibration
files, unsupported entries, and excessive archive expansion.

Fix the archive rather than disabling these checks.

## CPU processing appears stuck

RAFT is compute-heavy. CPU inference can spend substantial time on each frame
pair. Use `--device cuda` when a compatible CUDA environment is available, and
start with the small built-in example. A faster run does not imply a more
accurate trajectory.

## The app says the trajectory was created but the benchmark failed

This is expected for the current package:

- processing succeeded and output files were written;
- the packaged model separately failed its held-out distance/drift gate.

These are not contradictory states. See [Understanding the output](interpreting-results.md)
and the [Model card](model-card.md).

## The app cannot tell whether my upload is accurate

An ordinary upload has no reference trajectory, so its individual error is
unknown. The package benchmark describes performance on recorded evaluation
sequences; it is not ground truth for your upload.

## I expected a complete ONNX model

The current ONNX artifact covers only the 831-feature translation head. RAFT,
calibration, gyro processing, feature construction, rotation, and trajectory
integration remain outside the graph. See [Export and packaging](export.md).

## The port is already in use

Choose another local port:

```bash
compact-vio-demo \
  --model-package /path/to/model-package/manifest.json \
  --port 7861
```

## An optional dependency is missing

Install the group that owns the workflow:

```bash
python -m pip install -e '.[demo]'       # web app and runtime
python -m pip install -e '.[train]'      # historical training lane
python -m pip install -e '.[onnx]'       # ONNX export and parity
python -m pip install -e '.[governance]' # schema validation
```

For the exact failing command and supported flags, use the
[CLI reference](cli-reference.md) and `COMMAND --help`.
