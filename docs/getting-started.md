# Getting started

CompactVIO has two setup levels. A clean clone can install the code, create a safe example bundle,
and run the standard test suite; tests for unavailable optional runtimes may be skipped. Camera +
IMU inference additionally requires a checked model package, which is not yet distributed publicly.

## 1. Install a clean clone

```bash
git clone https://github.com/laxman-kc/compact-vio-uav.git
cd compact-vio-uav
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[data,dev]'
```

Verify the checkout without model weights:

```bash
python -m unittest discover -s tests
compact-vio-run --help
compact-vio-demo --help
```

You can also generate and inspect the rights-cleared workflow input:

```bash
python examples/create_example_bundle.py --output /tmp/compact-vio-example.zip
```

This creates input data only. It does not claim model accuracy and does not make inference possible
without a model package.

## 2. Install the demo runtime

```bash
python -m pip install -e '.[demo,dev]'
```

The demo needs a package containing RAFT weights, the translation head, feature clamp, ONNX head,
and checked evaluation summary. The current local package is normally at:

```text
outputs/raft-hybrid-experimental-20260830/model-package/manifest.json
```

That path is Git-ignored. There is no official download or clean-clone build recipe yet because
source and model-asset redistribution terms are unresolved. Do not download an unverified package
from an unofficial link.

## 3. Start the web app

If the checked package exists locally:

```bash
compact-vio-demo \
  --model-package outputs/raft-hybrid-experimental-20260830/model-package/manifest.json
```

Open `http://127.0.0.1:7860`.

Choose **Run built-in example** first. The app generates a deterministic synthetic camera + IMU
recording and runs the same ingestion, package-loading, inference, integration, and export path used
for uploads.

The example proves that the workflow connects. It does not test accuracy because it is not a
benchmark sequence.

## 4. Use your recording

Package the inputs into one ZIP using [Input formats](input-formats.md). Drop it into **Recording
bundle**. Processing starts automatically after selection.

Use **Advanced: use separate files** only when your inputs are not bundled together.

## Command-line inference

```bash
compact-vio-run \
  --recording /path/to/frames \
  --imu /path/to/imu.csv \
  --calibration /path/to/calibration.json \
  --model-package /path/to/model-package/manifest.json \
  --output outputs/my-run \
  --device cpu
```

The output directory contains `trajectory.csv`, `trajectory.svg`, `summary.json`, and
`summary.html`. CUDA is recommended for speed; CPU is supported but RAFT can be slow.

## Common errors

- **No model package configured:** the code is installed, but inference assets are missing. Supply
  a checked local manifest; no official public package exists yet.
- **MP4 needs timestamps:** provide `--camera-timestamps`, or use timestamp-named images.
- **Not enough IMU pre-roll:** keep the rig stationary and include at least two IMU samples before
  the first camera frame; a stationary 1–2-second pre-roll matches the current gyro-bias
  initialization.
- **Calibration resolution mismatch:** every image must exactly match `camera.resolution`.
- **CPU feels stalled:** RAFT is compute-heavy. Use CUDA when available.

## Next

- Prepare data: [Input formats](input-formats.md)
- Read a result: [Understanding the output](interpreting-results.md)
- Understand model quality: [Model card](model-card.md)
- Find every command: [CLI reference](cli-reference.md)
- Diagnose setup problems: [Troubleshooting](troubleshooting.md)
