# Export and model packaging

CompactVIO-UAV has separate export paths for the historical learned model and
the current RAFT-hybrid candidate. Neither path is a Jetson, TensorRT, ROS 2,
PX4, or flight deployment.

## Current RAFT-hybrid boundary

Only the compact translation head is exported to ONNX. Its graph accepts a
batch of 831-value feature vectors and returns translation in the previous IMU
sensor frame.

The graph does not contain:

- camera decoding, calibration, or rectification;
- TorchVision RAFT optical flow;
- timestamp or gyro processing;
- feature construction;
- rotation output or SE(3) trajectory integration.

Use “translation-head ONNX,” not “full VIO ONNX.”

## Export the hybrid translation head

Install the ONNX dependencies, then provide exact source identities:

```bash
python -m pip install -e '.[onnx]'

compact-vio-export-raft-head-onnx \
  --head-checkpoint /path/to/translation-head.pt \
  --expected-head-sha256 <head-sha256> \
  --clamp-artifact /path/to/feature-clamp.pt \
  --expected-clamp-sha256 <clamp-sha256> \
  --output /new/path/translation-head.onnx \
  --manifest /new/path/translation-head.onnx.json
```

The exporter checks the frozen `831 → 128 → 128 → 3` architecture, embeds the
feature clamp and optional 3 × 3 post-head matrix, validates the ONNX contract,
and runs deterministic PyTorch/ONNX Runtime parity. Tolerances cannot exceed
`1e-5` relative or absolute error.

## Build a checked hybrid package

```bash
compact-vio-package-raft-hybrid \
  --raft-weights /path/to/raft-small-c-t-v2.pth \
  --head-checkpoint /path/to/translation-head.pt \
  --feature-clamp /path/to/feature-clamp.pt \
  --evaluation-summary /path/to/evaluation-summary.json \
  --head-onnx /path/to/translation-head.onnx \
  --head-onnx-manifest /path/to/translation-head.onnx.json \
  --output /new/path/model-package
```

The resulting manifest binds all runtime artifacts, preprocessing and output
contracts, and the evaluation outcome. A rejected evaluation remains runnable
but must stay visibly marked `experimental_rejected`.

The necessary binary inputs are intentionally absent from a fresh clone.
Packaging code alone cannot recreate the local packaged candidate without the exact
rights-reviewed weights, head, clamp, and evaluation summary.

## Historical learned-model exports

Create an optimizer-free legacy inference checkpoint:

```bash
compact-vio-export-inference \
  --source-checkpoint /path/to/training-checkpoint.pt \
  --expected-source-sha256 <sha256> \
  --inference-policy <policy-id> \
  --output /new/path/inference-checkpoint.pt
```

Export the supported legacy learned model to a checked stateful ONNX graph:

```bash
compact-vio-export-onnx \
  --source-checkpoint /path/to/inference-checkpoint.pt \
  --expected-source-sha256 <sha256> \
  --expected-inference-policy <policy-id> \
  --output /new/path/compact-vio.onnx \
  --manifest /new/path/compact-vio.onnx.json
```

These commands operate on the earlier CNN/IMU-recurrent model family. Their
stateful ONNX graph is not the RAFT-hybrid runtime used by the current web app.

## What parity proves

Export parity proves that a declared source component and exported graph agree
on the tested fixtures within the frozen tolerance. It does not prove:

- end-to-end camera/IMU trajectory parity when only the head is exported;
- accuracy on a new recording;
- target-device latency, power, memory, or thermal fitness;
- TensorRT operator support or numerical equivalence;
- ROS/PX4 compatibility or safety.

See [Current architecture](architecture.md), [Model card](model-card.md), and
[ADR-0007](adr/0007-raft-gyro-hybrid-runtime.md) for the active boundary.
