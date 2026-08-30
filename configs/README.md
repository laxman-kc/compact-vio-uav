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
  configuration gate is now implemented at pushed commit
  `bc71dd5ebfdc636994a384a0a5dd2fd22184720d`; GitHub Actions
  [run 33286985057](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33286985057)
  passed its Python 3.10 and 3.12 jobs. The canonical contract is
  `data/tumvi_room4_512_16_adapter_contract_v1.json`. The strict loader at
  `src/compact_vio/data/tumvi_adapter_contract.py` accepts only the canonical
  tracked contract at exact `HEAD`, revalidates six exact tracked evidence
  identities, and rejects duplicate, missing, extra, reordered list, wrong-type,
  changed-worktree, untracked, hash-mismatched, linked, noncanonical evidence,
  alternate-contract-location, or moving-`HEAD` inputs.
  The contract freezes raw LF-only CSV grammars; exact per-column
  lexeme-to-source-labelled-output mappings; minimum row, arity, timestamp,
  filename, stereo-index, and resource rules; and prospective interval behavior
  expressed only as integer-token ordering with no clock-equivalence claim.
  Segment rules, clock/gap thresholds, pose interpolation, image decoding, and
  preprocessing remain null or blocked. The public surface is only
  `TumviAdapterContract`, `TumviAdapterContractError`, and
  `load_tumvi_adapter_contract`; this is a policy loader, not a real-payload
  parser or adapter. It reads no dataset payload, calibration, image, learning,
  or model path. Every readiness flag remains false and scientific authority is
  `none`. Gate 2 is implemented at pushed commit
  `3379060f83801230e5fe8c52e7bd0c3c288e5253`; GitHub Actions
  [run 33289072534](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33289072534)
  passed on Python 3.10 and 3.12. The module
  `src/compact_vio/data/tumvi_adapter_parser.py` parses only exact caller-supplied
  synthetic `io.BytesIO` fixtures under the frozen contract. It verifies
  claimed byte size/SHA-256, preserves source lexemes, enforces resource and
  stereo-byte rules, and denies the known inspected real CSV hashes before any
  read. Its `synthetic-fixture-only-origin-not-authenticated/v1` label is not
  authenticated provenance. No filesystem/CLI/package-level data export,
  calibration, image, EuRoC, learning/model, or segment path was added, and no
  real data was opened by Gate 2. Every operational readiness flag remains
  false and scientific authority remains `none`. Gate 3 must separately review
  calibration-metadata evidence and a one-use real-payload adapter probe as
  alternatives; this configuration documentation selects and authorizes neither.
  Real payloads, segment production, dataset membership, and all model work
  remain closed.
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
