# Third-party notices

This document is an inventory aid, not a replacement for the license and notice files shipped by
each dependency. CompactVIO-UAV does not currently have a selected source license, and nothing in
this document grants additional permission to copy, modify, redistribute, or package this
repository.

## Python and native dependencies

Dependencies are installed from their upstream distributions; their source is not vendored in
this repository. The exact selected version and its accompanying metadata remain authoritative.

| Component | Project use | Upstream license or notice |
|---|---|---|
| PyTorch | Tensor and model runtime | [pytorch/pytorch LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| TorchVision | RAFT-small implementation and pretrained-weight interface | [pytorch/vision LICENSE](https://github.com/pytorch/vision/blob/main/LICENSE) |
| ONNX | Translation-head interchange format | [onnx/onnx LICENSE](https://github.com/onnx/onnx/blob/main/LICENSE) |
| ONNX Runtime | Export parity and optional inference checks | [microsoft/onnxruntime LICENSE](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |
| OpenCV | Recording and image processing | [opencv/opencv LICENSE](https://github.com/opencv/opencv/blob/4.x/LICENSE) |
| Pillow | Image decoding and synthetic example generation | [python-pillow/Pillow LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| PyYAML | YAML calibration parsing | [yaml/pyyaml LICENSE](https://github.com/yaml/pyyaml/blob/main/LICENSE) |
| Gradio | Local web interface | [gradio-app/gradio LICENSE](https://github.com/gradio-app/gradio/blob/main/LICENSE) |
| jsonschema | Governance and schema validation | [python-jsonschema/jsonschema COPYING](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING) |
| Ruff | Development linting and formatting | [astral-sh/ruff LICENSE](https://github.com/astral-sh/ruff/blob/main/LICENSE) |

The dependency ranges used by the project are declared in `pyproject.toml`. A binary distribution
or hosted deployment must review the exact resolved dependency set and carry every notice its
distribution method requires.

## Pretrained weights and model packages

The runtime can initialize TorchVision RAFT-small weights. Model weights, exported ONNX files,
and packaged CompactVIO candidates are ignored by Git and are not released by this source tree.
Before publishing any model package, the release owner must separately verify:

1. the provenance and redistribution terms of every included weight;
2. the exact file and manifest hashes;
3. required attribution and notice text;
4. whether training-data or upstream-model terms impose additional conditions.

This notice does not authorize model-artifact redistribution.

## Datasets and user recordings

EuRoC, TUM-VI, and user recordings are not distributed by this repository. Users must obtain
third-party datasets from their official source and follow the terms attached to that dataset.
The built-in workflow bundle is generated from synthetic pixels and synthetic IMU values; it
contains no copied third-party recording and provides no accuracy evidence.
