# Configuration registry

`configs/` contains versioned, machine-readable inputs that change data,
training, evaluation, or calibration behavior. It does not contain observed run
results, model binaries, credentials, or machine-local paths.

## Current runtime calibration

[`raft-hybrid-calibration.example.json`](raft-hybrid-calibration.example.json)
shows the combined camera/IMU shape accepted by `compact-vio-run
--model-package` and the web demo.

Its numbers are placeholders. Replace them with the recording sensor's actual
resolution, intrinsics, distortion, camera-to-IMU transform, and identity IMU
body transform. See [Input formats](../docs/input-formats.md).

The current RAFT-hybrid package manifest is not a configuration in this
directory. It is a checked binary-artifact manifest under ignored `outputs/`,
and a fresh clone does not include it.

## Data configurations

`data/` records source identities, allowed units, preprocessing, and dataset
roles used by acquisition or evaluation code.

| Group | Files |
|---|---|
| EuRoC Vicon development data | [`euroc_vicon_v1.json`](data/euroc_vicon_v1.json) |
| EuRoC Machine Hall evaluation data | [`euroc_machine_hall_full_pose_v1.json`](data/euroc_machine_hall_full_pose_v1.json), [`euroc_machine_hall_position_v1.json`](data/euroc_machine_hall_position_v1.json), [`euroc_machine_hall_mh02_position_v1.json`](data/euroc_machine_hall_mh02_position_v1.json) |
| TUM-VI bounded research records | `data/tumvi_*.json` |

A data configuration does not prove that bytes were downloaded, parsed, or
scientifically selected. Dataset rights and authority live under
[Governance](../governance/README.md); observed outcomes live under
[Technical reports](../reports/README.md).

## Training configurations

`training/` preserves the original learned CNN/IMU-recurrent experiment family:

- v1: initial compact model;
- v2: stride augmentation;
- v3–v4: recurrent/state-policy experiments;
- v5: translation-magnitude loss;
- v6–v7: trajectory-loss experiments;
- v8–v9: checkpoint-initialized fine-tuning experiments.

These files are consumed by `compact-vio-train`. They do **not** train the
RAFT-hybrid translation head used by the current web demo. Some later configs
require the exact initial checkpoint and SHA-256 named by their experiment
record. See [Training](../docs/training.md).

## Evaluation configurations

`evaluation/` contains frozen position-only checkpoint protocols. The current
schema-2 MH_01 protocol is
[`euroc_mh01_frozen_checkpoints_position_v2.json`](evaluation/euroc_mh01_frozen_checkpoints_position_v2.json).
The schema-1 file remains historical and must not be silently rewritten.

The current RAFT-hybrid full-pose benchmark is bound by its local package
manifest and reviewed completion report, not by these position-only protocols.
See [Evaluation](../docs/evaluation.md).

## Calibration schemas and templates

| Path | Role |
|---|---|
| [`schemas/calibration-profile.schema.json`](schemas/calibration-profile.schema.json) | Immutable calibration facts and validity conditions |
| [`schemas/calibration-assessment.schema.json`](schemas/calibration-assessment.schema.json) | Separate approval, revalidation, or invalidation decision |
| [`templates/calibration-profile.template.json`](templates/calibration-profile.template.json) | Visibly synthetic profile fixture |
| [`templates/calibration-assessment.template.json`](templates/calibration-assessment.template.json) | Visibly synthetic rejected assessment fixture |

Schema validity proves structure only. It does not approve a sensor, calibration,
dataset, run, model, or deployment.

## Contribution rules

- Keep configuration deterministic and human-reviewable.
- Do not add credentials, absolute machine paths, downloaded data, checkpoints,
  or generated outputs.
- Record exact source identities and units rather than unversioned aliases.
- Put measured outcomes in `reports/`, not back into the input configuration.
- Add or update focused tests when a parser or configuration contract changes.

See [Repository layout](../docs/repository-layout.md) for the ownership boundary
between configuration, reports, governance, and experiment evidence.
