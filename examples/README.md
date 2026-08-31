# Examples

The example helper creates CompactVIO's existing, rights-cleared workflow fixture. It packages
synthetic image frames, synthetic IMU samples, calibration metadata, and a bundle manifest into a
ZIP file.

It does **not** load a model, run inference, download a dataset, or demonstrate positioning accuracy.

## Create the example bundle

Install the package with the lightweight data dependency:

```bash
python -m pip install -e '.[data]'
```

Then run:

```bash
python examples/create_example_bundle.py
```

The default output is:

```text
outputs/compact-vio-workflow-example.zip
```

You can choose another destination with `--output`:

```bash
python examples/create_example_bundle.py --output /tmp/compact-vio-example.zip
```

The helper refuses to overwrite an existing file. The generated bundle contains:

```text
frames/
  2000000000.png
  ...                         # 12 synthetic frames
imu.csv
calibration.json
compact-vio-bundle.json
```

Inspect it without extracting it:

```bash
python -m zipfile -l outputs/compact-vio-workflow-example.zip
```

Processing a recording is a separate step and requires a compatible local model package. The
built-in fixture may exercise the runtime, but it is excluded from benchmark and scientific
evidence and does not test accuracy.

The generated content contains no copied real-world recording. Dataset redistribution rights,
model-artifact release rights, and the repository's source-license decision remain separate
unresolved matters.
