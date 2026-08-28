# Configuration registry

This directory holds versioned, human-reviewable inputs for the implemented
EuRoC acquisition, compact learned-VIO training, and frozen evaluation paths.
Checked-in files declare exact identities and policies; machine-local paths,
credentials, downloaded data, checkpoints, and run outputs remain outside this
directory.

Current calibration files:

- `schemas/calibration-profile.schema.json` defines immutable sensor,
  intrinsics, distortion, camera–IMU transform, clock mapping, IMU
  characterization, provenance, validity, procedure, and diagnostic facts.
- `schemas/calibration-assessment.schema.json` defines the separate initial
  review, revalidation, or invalidation decision for one exact profile revision.
- `templates/` contains visibly synthetic schema fixtures. The assessment
  fixture is rejected and `approved_for_replay` is false. Neither template is a
  sensor choice, numerical recommendation, physical calibration, or dataset-use
  approval.

Schema validity proves structure only. Replay approval requires a matching
assessment whose raw profile hash, identity, revision, validity fingerprint,
scope, criteria, and required checks all validate. A profile never approves
itself and is not edited after assessment; changes create a new revision.

The EuRoC adapter reads native camera, IMU, calibration, full-pose reference,
and position-only Leica records without replacing their source calibration.
Generic calibration profiles still project into runtime `CalibrationRecord`
objects without inventing fields: `calibration_id`, `sensor_profile_id`,
`revision_id`, `provenance_id`, `validity_conditions_id`, and
`replay_clock_id` map directly; the profile schema `$id` supplies `schema_id`;
and each camera/IMU stream plus its frame supplies one modality-specific
`SensorBinding`.

Current namespaces:

- `data/` records exact source archives, sequence roles, split membership, and
  acquisition policies. The `MH_02_easy` record is prospective: it reserves one
  position-only v2-versus-v5 evaluation and does not claim extraction or a
  result.
- `training/` contains the fully resolved v1-v5 experiment configurations.
  Each new candidate changes only the fields declared by its reviewed plan.
- `evaluation/` contains frozen checkpoint-evaluation protocols after source,
  calibration, reference, and checkpoint hashes are known. A prospective data
  role is not itself an executable evaluation protocol.
- `schemas/` and `templates/` retain the generic calibration contracts and
  visibly synthetic validation fixtures.

Future `baselines/` or model-family namespaces are created only with their first
tested implementation; empty scaffolding is intentionally avoided.

Every claim-supporting run must preserve the fully resolved configuration in its
experiment bundle. Configuration files must contain no credentials, machine-
local absolute paths, or unversioned dataset aliases.
