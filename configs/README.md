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
  result. The TUM VI `room4` 512x512 record is a non-executable candidate
  identity only: it binds the official request/redirect observation, observed
  size, exact MD5-sidecar provenance, rights, and source capabilities while
  leaving selection, acquisition, SHA-256, layout, calibration, ground-truth
  schema, 16-bit preprocessing, adapter compatibility, and membership
  unresolved. A strict exact-field loader and focused tests now validate the
  non-executable record. Structural loading does not confer acquisition or
  evaluation authority. A separate one-use controller and
  `governance/datasets/acquisitions/tumvi-room4-512-16-transfer-2026-08-29.authorization.json`
  bind one operational transfer/read-only inventory to exact tracked inputs,
  runtime limits, and a quarantine destination. That authorization does not
  modify the candidate record, select the unit, allow extraction, or confer
  training, inference, evaluation, or publication authority. Its one execution
  retained verified bytes but failed strict inventory on an official DSO-tree
  symlink, so it produced no success receipt and cannot be retried.
  The separate structural-audit authorization executed once and recorded all
  4,485 TAR headers without following links or extracting payloads. Its exact
  audit now binds a documentation-only compatibility allowlist at
  `data/tumvi_room4_512_16_compatibility_slice_v1.json`: four complete `mav0`
  CSV members plus two common PNG names from each camera, 8 regular files and
  5,043,300 bytes. The associated controller and one-use authorization both
  passed CI, and the authorization executed once to publish exactly those eight
  regular members plus a tracked receipt. The authorization is consumed. This
  configuration, audit, and operational output do not establish payload
  validity, adapter compatibility, scientific dataset selection, membership,
  model access, training, inference, evaluation, or publication authority.
  A separate checked format-inspection specification at
  `data/tumvi_room4_512_16_format_inspection_v1.json` then froze three current
  EuRoC adapter-header comparisons, structural inspection of four CSV streams,
  four 33-byte PNG signature/IHDR observations, and seven separate cross-file
  predicates. The
  CI-green one-use authorization executed once and completed with
  `format_comparison_outcome: does_not_conform`. Camera and IMU headers, both
  camera indexes, selected-name membership, filename stems, and all four PNG
  IHDR tuples passed; the eight-column mocap header matched neither frozen
  17-column full-state target, and the first selected camera timestamp preceded
  both observed IMU and mocap ranges. Adapter, calibration, and ground-truth
  readiness remain false and scientific authority remains none. The next safe
  configuration work is a TUM-VI-specific adapter contract; minimal calibration
  metadata may be opened only under a later separate authorization if that
  contract justifies it. The EuRoC adapter and all model work remain closed.
- `training/` contains the fully resolved v1-v5 experiment configurations.
  Each new candidate changes only the fields declared by its reviewed plan.
- `evaluation/` contains frozen checkpoint-evaluation protocols after source,
  calibration, reference, and checkpoint hashes are known. A prospective data
  role is not itself an executable evaluation protocol. The MH01 v1 protocol
  remains immutable historical evidence at its recorded SHA-256; the schema-2
  MH01 protocol preserves its candidate, sampling, metric, and decision
  semantics while additionally binding every checkpoint's exact training
  revision, split membership, and source/calibration hashes. Only schema 2 is
  executable by the current evaluator.
- `schemas/` and `templates/` retain the generic calibration contracts and
  visibly synthetic validation fixtures.

Future `baselines/` or model-family namespaces are created only with their first
tested implementation; empty scaffolding is intentionally avoided.

Every claim-supporting run must preserve the fully resolved configuration in its
experiment bundle. Configuration files must contain no credentials, machine-
local absolute paths, or unversioned dataset aliases.
