# CompactVIO-UAV documentation

CompactVIO-UAV turns synchronized monocular camera and IMU recordings into an
inspectable local 3D trajectory. The local software path runs end to end, but the current
RAFT-hybrid model is a research preview that failed its held-out distance and
drift gates.

## Run and understand the current model

| Guide | Use it for |
|---|---|
| [Getting started](getting-started.md) | Install the app and run the local demo |
| [Input formats](input-formats.md) | Prepare a recording bundle or separate input files |
| [Understanding results](interpreting-results.md) | Read the trajectory, metrics, downloads, and warnings |
| [Troubleshooting](troubleshooting.md) | Resolve model-package, timestamp, calibration, and runtime errors |
| [CLI reference](cli-reference.md) | Find the supported command for each workflow |

## Release and assets

There is no public model-package download yet. The current weights are not
included in a fresh clone, and both uploads and the built-in synthetic example
still require a local, checked package. The unresolved source-license decision
and separate model-asset redistribution review block a public asset release;
this is not an installation error.

Use the [project README](../README.md) for the current release status and
[Contributing](../CONTRIBUTING.md) for source-development setup. Do not invent
or mirror an unofficial model download.

## Model and engineering reference

| Reference | Contents |
|---|---|
| [Model card](model-card.md) | Current RAFT-hybrid architecture, benchmark, intended use, and limitations |
| [Current architecture](architecture.md) | Runnable data flow and software boundaries |
| [Training](training.md) | Legacy CNN/GRU training lane and the current RAFT-hybrid training gap |
| [Evaluation](evaluation.md) | Evaluation surfaces, metrics, and acceptance rules |
| [Export and packaging](export.md) | Inference checkpoints, ONNX boundaries, and hybrid packages |
| [Repository layout](repository-layout.md) | Where code, configuration, evidence, and governance belong |

## Research and project records

| Record | Role |
|---|---|
| [Architecture decisions](adr/README.md) | Accepted, superseded, and unresolved technical decisions |
| [Requirements](requirements/README.md) | Normative requirements and traceability entry point |
| [Research protocol](protocols/research-protocol.md) | Data, causality, comparison, and claim controls |
| [Experiment lifecycle](protocols/experiment-lifecycle.md) | Per-run authorization, execution, export, and review procedure |
| [Technical reports](../reports/README.md) | Dated, claim-supporting results and evidence |
| [Historical records](history/README.md) | Long-form plan, progress ledger, and completed sprint record |
| [Configuration registry](../configs/README.md) | Machine-readable data, training, evaluation, and calibration inputs |
| [Governance](../governance/README.md) | Rights, policy, authority, and receipt records |
| [Experiment schemas](../experiments/README.md) | Run and artifact evidence formats |

For code changes, start with [Contributing](../CONTRIBUTING.md). Security issues
follow the [security policy](../SECURITY.md). The repository does not yet have
a selected source license; see
[ADR-0001](adr/0001-project-and-release-scope.md) before assuming reuse rights.
