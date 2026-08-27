# Configuration registry

This directory holds versioned, human-reviewable configuration contracts and
will later hold approved baseline, model-candidate, and experiment
configuration. It intentionally contains no default estimator, sensor, dataset
split, loss, threshold, or deployment target: those values remain blocked by
the decision gates in `docs/`.

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

The later dataset adapter projects one validated profile into the existing
runtime `CalibrationRecord` without inventing fields: `calibration_id`,
`sensor_profile_id`, `revision_id`, `provenance_id`,
`validity_conditions_id`, and `replay_clock_id` map directly; the profile
schema `$id` supplies `schema_id`; and each camera/IMU stream plus its frame
supplies one modality-specific `SensorBinding`. That adapter and any real
profile remain M6 work.

When a track is approved, add its configuration below one of these namespaces:

- `baselines/` for classical reference implementations;
- `models/` for learned or hybrid candidate definitions;
- `experiments/` for resolved run configurations that reference frozen dataset
  and split manifests.

Every claim-supporting run must preserve the fully resolved configuration in its
experiment bundle. Configuration files must contain no credentials, machine-
local absolute paths, or unversioned dataset aliases.
