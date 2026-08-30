# Progress evidence

Status: Append-only dated evidence ledger

Roadmap authority: [Implementation plan](plan.md)

Decision authority: [ADR index](adr/README.md)

Requirement authority: [Project requirements](requirements/project-requirements.md)

Each entry records observed evidence at a point in time. It does not remain a
claim about live external state, change a milestone, or accept an ADR. Future
entries must include the milestone ID, relevant commit/evidence path, validation
result, and explicit remaining blockers.

## 2026-08-26 — M0 foundation baseline

- Evidence commit: `ea07ccbc7ee1ab7ba870473be63625259b4b64fc`.
- GitHub repository: `laxman-kc/compact-vio-uav`, branch `main`.
- GitHub Actions: Python 3.10/3.12 foundation CI succeeded in
  [run 32997583985](https://github.com/laxman-kc/compact-vio-uav/actions/runs/32997583985).
- Local unit tests: 20 passed at the evidence commit.
- Repository policy: passed at the evidence commit.
- A clean A10 clone at `/home/ubuntu/compact-vio-uav` reproduced the
  standard-library tests at the same commit. It is a disposable checkout outside
  Brev's generally documented `/home/ubuntu/workspace` stop-persistence path;
  no persistence claim is made for it.
- Implemented: governance, ADRs, schemas, artifact inventory/verification,
  repository policy, package/CI foundation, and environment inventory.
- Not implemented: estimator, canonical data/replay, approved data roles/splits,
  baseline integration, training, export runtime, edge benchmark, ROS 2/PX4, or
  a flight system.
- M0 evidence was sufficient; it did not satisfy artifact restore requirement
  `R-INFRA-003`.

## 2026-08-26 — M1 uncommitted planning and durability-preflight start

- Working-tree state at this entry: uncommitted; an immutable evidence commit and
  CI link must be appended before M1 can complete.
- Added the roadmap, requirements index/source mapping, and this evidence ledger.
- Started a standard-library-only, read-only durability preflight. Its contract
  can report `static_checks_satisfied`, but always reports
  `artifact_restore_gate_passed=false` and lists what it cannot verify.
- Observed local filesystem at review time: 460 GiB total, 411 GiB used, 14 GiB
  available, 97% capacity. This is insufficient evidence for a project artifact
  vault because no retained-byte estimate or reserve has been approved.
- `tmutil destinationinfo` reported no configured Time Machine destination at
  review time. No other independent backup was supplied or verified.
- Between `2026-08-26T18:35:53Z` and `18:36:00Z`, Brev CLI `v0.6.326`
  reported `compact-vio-uav-gpu` as instance type `gpu_1x_a10`, `RUNNING`, build
  `COMPLETED`, shell `READY`, and health `HEALTHY`.
- In the same observation window, the catalog row with exact type ID
  `gpu_1x_a10` reported Lambda Labs, 1×A10/24 GB, 30 vCPU, 200 GiB RAM,
  1,400 GB disk, `stoppable=false`, and USD 1.548/hour. The type-ID linkage is
  observed; price, availability, lifecycle flags, and actual billing remain
  volatile and must be refreshed before action. Sanitized evidence is recorded
  in the [A10 inventory](../environments/a10/inventory-2026-08-26.md).
- NVIDIA's official lifecycle documentation establishes that non-stoppable
  instances require termination to halt charges and that termination destroys
  disk state. No termination was attempted.
- Remaining M1 evidence: traceability tests, full local validation, clean commit,
  pushed revision, successful CI, and A10 smoke verification.
- Blocking M2 inputs: project/release/license decision, vault path, independent
  backup, failure-domain record, retained-byte estimate, explicit reserve,
  retention/RPO, spending ceiling, review time, recovery owner, teardown owner,
  and representative restore drill.

## 2026-08-26 — M1 planning traceability and static preflight completed

- Evidence commit: `18d68de8b861ae8aae1f642231dd22ed06092bd6`.
- Added the detailed M0–M14 implementation roadmap, non-normative official-source
  requirements traceability, this dated ledger, ADR pre-acceptance/follow-up
  evidence boundaries, and filesystem-candidate durability preflight.
- Local validation at the evidence commit: 36 unit tests passed; Draft 2020-12
  schema and format checks passed; repository policy passed for 41 intended Git
  files; Ruff lint/format and installed command-line smoke checks passed.
- GitHub Actions Python 3.10/3.12 CI succeeded in
  [run 33002473548](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33002473548).
- The authenticated `brev shell compact-vio-uav-gpu` checkout fast-forwarded
  cleanly to the evidence commit. Python 3.10.12 compiled the sources, all 36
  standard-library tests passed, repository policy passed for 41 files, and the
  blocked-by-design preflight smoke passed. The checkout remained clean.
- No dataset was downloaded, no model was trained, no dependency was installed
  into the A10 global environment, and no stop/reboot/delete/termination action
  was attempted.
- M1 is complete. `artifact_restore_gate_passed` remains false by design; M2
  remains blocked on the decisions and restore evidence listed in the prior
  entry.

## 2026-08-26 — M2 decision-neutral governance scaffolding prepared

- Working-tree state at this entry: uncommitted; an immutable evidence commit
  and CI link remain pending.
- Added strict draft/owner-review input schemas and blank templates for the
  current-scope project/release proposal, rights matrix, phase-scoped artifact
  storage plan, and bounded worker-authorization request.
- Added the governance-record authority rule: templates and schema validity are
  never evidence, ADR acceptance, milestone completion, paid-work approval, or
  general destructive-action approval. The later review refinement represents
  only the proposed exact purpose-created disposable restore-test source-copy
  deletion scope; version 1 permits only live static checks and refuses every
  non-static action without reviewed storage-role linkage, pre-action evidence,
  and a single-use consumption check. Worker lifecycle and retained-copy
  deletion remain outside it.
- Aligned ADR-0001 with current-scope pre-acceptance evidence and per-asset
  follow-up review. Aligned ADR-0005 with a phase-scoped capacity/spend envelope,
  re-estimation triggers, post-export storage evidence, and periodic restore
  follow-up.
- Aligned the artifact policy and lifecycle around immutable run/artifact
  manifests inside the frozen bundle and a separate post-export storage-evidence
  sidecar. The read-only copy audit is only supporting checksum evidence.
- Validation at that scaffolding checkpoint: 48 standard-library unit tests
  passed; the pinned Draft 2020-12 harness validated seven schemas and five
  matching draft records; an explicit positive/negative contract check
  confirmed that only an `owner_approved` worker record can set
  `authorizes_work: true`.
- The subsequent review refinement preserves no general destructive authority
  and keeps worker lifecycle and retained-copy deletion hard false. Its sole
  narrowly represented exception is the exact purpose-created disposable
  source-copy deletion described above, and execution remains blocked. Final
  validator counts belong in the next evidence entry after integrated
  validation completes.
- No project purpose, user group, distribution surface, release lane, license,
  provider, storage location, retention duration, budget, or owner was selected.
- No external storage was accessed, no copy or restore drill was performed, no
  paid-worker activity was authorized, and no stop, reboot, delete, termination,
  or other destructive action was attempted by this governance work.
- `artifact_restore_gate_passed` remains false. ADR-0001 and ADR-0005 remain
  unresolved, and M2 remains blocked.

## 2026-08-26 — M2 contract implementation locally validated

- Working-tree state at this entry: uncommitted; the evidence commit and remote
  CI run are intentionally deferred to the next append-only entry.
- Implemented strict canonical governance-record discovery and cross-record
  validation for project/release scope, rights, storage planning, worker scope,
  immutable run and artifact manifests, and the post-export storage-evidence
  sidecar. Added a read-only two-copy content-audit command whose successful
  evidence uses opaque copy references and never claims a restore-gate pass.
- The validator binds exact raw-byte hashes, record identifiers, canonical paths,
  storage roles, action/access scopes, capacity and cost envelopes, artifact
  inventory, and strict chronology. It rejects equality across copy verification,
  disposable-source deletion, absence verification, restore, representative
  load/open, storage review, and final assessment.
- Local validation commands and results:
  - `uv run --with "jsonschema[format-nongpl]==4.26.0" python
    scripts/validate_schemas.py`: passed for seven schemas, five draft templates,
    and zero real governance records; every authority, execution, and restore-gate
    truth flag remained false.
  - `uv run --with "jsonschema[format-nongpl]==4.26.0" python -m unittest
    discover -s tests -v`: 52 tests passed.
  - `uv run --with "ruff==0.16.4" ruff check .` and `ruff format --check .`:
    passed for 37 Python files.
  - `.venv/bin/python -m compact_vio.repository_policy .`: passed for 54
    intended repository files with zero violations.
  - `.venv/bin/python -m compileall -q src tests scripts` and
    `git diff --check`: passed.
- An independent read-only adversarial review reported no remaining P0, P1, or
  P2 defect in this frozen implementation. That review does not authenticate an
  owner, approve a record, or establish an external storage fact.
- No real governance record was created, no storage candidate was selected, no
  dataset or external vault was accessed, no paid worker action was run, and no
  deletion or Brev lifecycle action was attempted. Version 1 live-scope checking
  permits only exact `static_checks`; all non-static actions remain blocked.
- M2 remains blocked on owner-reviewed ADR-0001/ADR-0005 inputs, verified external
  capacity and failure-domain evidence, an authenticated single-use execution
  ledger, the representative two-copy restore drill, and its accepted evidence.
  `artifact_restore_gate_passed` remains false.

## 2026-08-26 — M2 contract evidence commit verified remotely

- Evidence commit: `9dcb52546eae562a928f7e56c3ccc58a1c5782f8` on branch `main`.
- GitHub Actions run
  [33015547062](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33015547062)
  completed successfully for both Python 3.10 and Python 3.12.
- Each matrix job compiled the source/tests, built and installed the package,
  passed all 52 unit tests, exercised the installed command-line tools, checked
  root-anchored scratch exclusions, passed repository policy and Ruff
  lint/format, and passed the seven-schema/five-template contract harness.
- The evidence commit contains schemas, blank non-authoritative templates,
  validators, tests, policies, and supporting read-only audit tooling. It contains
  zero real governance records and does not contain an owner approval, a license
  choice, storage-provider choice, paid-work approval, dataset, checkpoint, or
  restore-drill result.
- The A10 was not used for this evidence slice because the validated live
  authorization interface permits only exact local/static checks and no
  authenticated owner-approved non-static execution record exists. No Brev
  lifecycle action was attempted.
- M2 remains blocked; ADR-0001 and ADR-0005 remain unresolved and
  `artifact_restore_gate_passed` remains false.

## 2026-08-26 — M4 causal replay slice implemented locally

- Working-tree state at this entry: uncommitted; remote commit and CI evidence
  are pending.
- The owner clarified the project as publicly readable, research-only, and
  non-commercial. The core direction is causal metric-scale local VIO with no
  loop closure in the primary comparison; PX4 retains flight-control authority.
- Corrected the roadmap so M2 gates long or irreplaceable paid A10 work, not
  ordinary local implementation or short reproducible smoke checks.
- Added a standard-library causal replay primitive with separate sensor
  measurement and estimator-availability timestamps, one declared clock,
  deterministic same-time ordering, exactly-once emission, monotonic watermarks,
  and explicit delivery of invalid/reset events.
- Added 13 focused replay tests covering boundary and delayed availability,
  future-event exclusion, ordering, duplicate identities, mixed clocks,
  malformed timestamps, backward watermarks, reset/invalid delivery, and empty
  input. The complete local suite passed 65 tests.
- Ruff lint and format passed for 39 Python files; repository policy passed for
  56 files; source/test/script compilation, `git diff --check`, and the existing
  seven-schema/five-template harness passed.
- Recorded ADR-0001 and ADR-0002 as accepted owner decisions; exact licensing,
  estimator-interface details, datasets, hardware, and thresholds remain later
  decisions.
- No dataset was downloaded, no model or estimator was implemented, and the A10
  was not accessed in this local slice. M3, M4, M5, and M7 are in progress;
  none is complete. M2 remains blocked for important paid GPU work.

## 2026-08-26 — M4 causal replay slice verified remotely

- Evidence commit: `5da148bc1d125f897ed79c30e0d5d0bf7cceb652` on branch
  `main`.
- GitHub Actions run
  [33018452275](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33018452275)
  completed successfully for Python 3.10 and Python 3.12.
- The running `compact-vio-uav-gpu` checkout fast-forwarded cleanly to the exact
  evidence commit. Its standard-library suite passed all 65 tests and repository
  policy passed for 56 files; the checkout remained clean.
- The remote smoke installed no dependency, downloaded no dataset, trained no
  model, and produced no retained artifact. No Brev lifecycle action was taken.
- The next implementation slice is the remaining estimator interface, canonical
  sensor records, synthetic geometry fixtures, and evaluator core. M4 and M7
  remain in progress rather than complete.

## 2026-08-26 — Training architecture and lean execution plan documented

- Working-tree state at this entry: documentation changes are uncommitted on top
  of commit `7d52bfe0027b8e2e24d465ba22c801a90ed6a255`; a remote evidence commit and CI
  run are not yet recorded.
- Refactored the reader-facing architecture around one common causal
  data/replay/evaluation substrate and three explicit candidate lanes: native
  classical VIO, a direct learned control, and a physically anchored hybrid.
  PyTorch is documented as the proposed learned framework pending ADR-0004, not
  as an installed or accepted dependency.
- Added a current/planned/conditional technology table and repository tree so
  existing infrastructure cannot be confused with future estimator, training,
  export, or deployment code. Planned paths are created only with their first
  tested behavior; no empty framework was added.
- Made model production explicit: frozen training membership produces causal
  training samples and checkpoints; validation applies a frozen selection rule;
  final-test data is inference-only; every selected candidate returns through
  the same common evaluator.
- Recorded that classical execution bypasses learned-training frameworks, MLflow is optional and
  non-authoritative, and ONNX/TensorRT/Jetson/ROS 2/PX4 remain conditional after
  scientific selection and later deployment decisions.
- Added the lean delivery rule: one reviewable behavior and one verification
  boundary per implementation slice. Longer dataset transfer or model-training
  runtime is planned, launched, monitored, reviewed, and exported as separate
  bounded tasks rather than counted as planning time.
- The project owner reported that the previous A10 was terminated. A fresh
  read-only `brev --no-check-latest list --json` observation at
  `2026-08-27T03:36:30Z` returned `{"workspaces": null}`. Earlier running-worker
  entries remain valid historical observations; no live GPU worker, current
  billing state, or future capacity is inferred beyond this CLI result.
- Any future GPU provisioning or use now requires fresh owner confirmation for
  that exact bounded task. Previous access or approval does not carry forward,
  and a new worker requires a new inventory.
- The exact source licence, mono/stereo sensor choice, dataset roles/splits,
  model topology, objective, hyperparameters, confirmatory thresholds, artifact
  stores, target hardware, and integration scope remain unresolved. No default
  was invented for them.
- Local validation: 65 unit tests passed; repository policy passed for 56 files;
  the seven-schema/five-template harness passed with zero real governance
  records and every authority/restore-gate truth flag false; Ruff lint passed
  and 39 Python files were already formatted; `git diff --check` passed.
- No implementation code or dependency changed, no dataset was downloaded, no
  model was trained, no checkpoint was created, and no GPU lifecycle or paid
  execution action was performed during this documentation slice.

## 2026-08-27 — M3 estimator-contract envelope implemented and A10-smoked

- Implementation evidence commit:
  `4f34e0b6a4f07604224aaf437c7fc51b5e005d41` on branch `main`.
- Added the first framework-neutral estimator boundary in
  `src/compact_vio/estimator.py` with focused tests in
  `tests/test_estimator.py`.
- The boundary accepts existing causal replay events without conversion and
  requires every output envelope to declare its clock, estimate and
  availability times, reset generation, validity, health code, frame IDs,
  transform direction, translation/rotation units, and rotation
  representation. Concrete values are required from a future selected profile;
  none was chosen by this slice.
- The state payload remains opaque. The code does not select the state vector,
  concrete frames, transform convention, output rate, health vocabulary,
  covariance representation, initialization policy, mono/stereo configuration,
  sensor profile, numerical backend, model, training framework, dataset, or
  deployment target.
- Local verification on the implementation commit: 75 unit tests passed; Ruff
  lint passed; all 42 Python files were formatted; repository policy passed for
  59 files; and `git diff --check` passed.
- The new `compact-vio-uav-gpu` worker was used only for a clean-checkout smoke.
  Its checkout resolved to the exact implementation commit, all 75
  standard-library tests passed, and repository policy passed for 59 files.
  No dependency or dataset was downloaded, no estimator algorithm or model was
  trained, and no checkpoint or retained experiment artifact was created.
- M3 remains in progress. The exact estimator state/time/reset interface still
  requires a later decision, and ADR-0003/ADR-0004 remain unresolved. No Brev
  stop or termination action was taken; the project owner retains lifecycle
  control.

## 2026-08-27 — M4 typed sensor-record envelope implemented and A10-smoked

- Implementation evidence commit:
  `048f7772f82bce9b50c6f4824f92759bade3fdd6` on branch `main`.
- Added framework-neutral camera and IMU payload records, explicit time
  intervals, quantity/unit/axis declarations, per-stream modality/frame
  bindings, and a versioned opaque calibration-identity envelope in
  `src/compact_vio/contracts/sensors.py`. Added 14 focused synthetic tests in
  `tests/test_sensor_records.py`.
- The existing `ReplayEvent` remains the only event identity, stream, clock,
  measurement/availability timestamp, validity, and reset envelope. The sensor
  records do not duplicate or override those fields.
- Valid camera records require opaque image data. Valid IMU records require at
  least one explicitly described gyro or accelerometer measurement, permitting
  paired or independently sampled layouts. Invalid records may preserve partial
  or missing raw measurements and remain observable.
- Calibration binding now matches the exact stream, camera/IMU modality, frame,
  clock, profile ID, calibration ID, and revision. The calibration payload
  remains opaque and schema-identified; this is not the complete calibration
  profile required for real-data acceptance.
- No mono/stereo count, encoding, unit vocabulary, axis convention, timestamp
  convention, shutter model, rate, intrinsics/distortion model, extrinsic,
  temporal offset, IMU noise model, sensor hardware, dataset, numerical backend,
  model, or training framework was selected.
- Local verification: 89 unit tests passed; Ruff lint passed; all 45 Python
  files were formatted; repository policy passed for 62 files; and
  `git diff --check` passed.
- The clean Brev checkout resolved to the exact implementation commit; all 89
  tests passed there and repository policy passed for 62 files. A fresh
  read-only status observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. No dependency or dataset was downloaded, no model was trained,
  and no retained experiment artifact was created.
- M4 remains in progress and ADR-0003 remains unresolved. The next M4 slice is
  the complete versioned calibration-profile schema and synthetic negative
  fixtures. No Brev stop or termination action was taken.

## 2026-08-27 — M4 calibration profile and review contract completed

- Implementation evidence commit:
  `9120c74c2c7da7ac214d87a9fa48cd90ba0b6bce` on branch `main`.
- Added strict Draft 2020-12 contracts for immutable sensor calibration facts
  and a separate review, revalidation, or invalidation record. The contracts
  cover actual camera/IMU streams, frames, axes, units, intrinsics, distortion,
  camera–IMU transform endpoints and direction, clock mappings and offset-sign
  definitions, IMU noise/bias characterization, gravity, provenance, validity
  conditions, procedure evidence, diagnostics, threshold scope, and decisions.
- The profile maps without defaults into the existing runtime calibration
  identity and stream bindings. Facts never approve themselves: a review binds
  the exact profile identity, revision, raw-file SHA-256, complete configuration
  fingerprint, threshold scope, recomputed criterion results, and required
  checks.
- Added visibly synthetic profile and assessment fixtures. Their names, values,
  units, conventions, models, and evidence references are non-authoritative;
  the assessment is rejected, `approved_for_replay` is false, and it does not
  accept an ADR.
- Added semantic negative fixtures for duplicate or dangling IDs, missing clock
  or transform coverage, absent IMU characterization, wrong hashes/fingerprint,
  incomplete threshold scope, false criterion results, and false approval. Both
  explicit camera→IMU and IMU→camera transform directions are accepted; every
  stream must declare a clock mapping even when its source and replay clock IDs
  match.
- Local verification: 90 standard-library unit tests passed; the pinned schema
  harness passed 9 schemas and 7 templates; Ruff lint passed and all 45 Python
  files were formatted; repository policy passed for 66 files; and
  `git diff --check` passed. Independent review reported PASS after three
  adversarial findings were corrected.
- The clean A10 checkout fast-forwarded to the exact implementation commit; all
  90 tests passed there and repository policy passed for 66 files. A fresh
  read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`, and
  `HEALTHY` before the smoke.
- M4 is complete under its synthetic-contract exit evidence. This does not
  approve a dataset, sensor, calibration, numerical threshold, estimator, or
  model. M3 remains in progress; M6 must create and review an actual profile for
  its selected representative sequence. No dependency or dataset was installed
  on the A10, no model was trained, no retained experiment artifact was created,
  and no Brev stop or termination action was taken.

## 2026-08-27 — M3 explicit estimator-interface slice implemented

- Implementation evidence commit:
  `a0579175fc78907ce014d12eff0182b7bc2adc00` on branch `main`.
- Added an immutable framework-neutral declaration shape requiring a future
  selected estimator profile to name its state schema/variables, metric-scale,
  initialization/reset/recurrence, output-time/schedule, causality,
  algorithmic/processing latency, staleness, and input-gap policies.
- Startup initialization, post-reset initialization, and the relationship
  between validity and initialization are required profile values with no
  library default. Runtime outputs carry an atomic interface-identity and
  initialization pair. The wrapper validates only observable metadata; it does
  not claim that an adapter reset its internal state.
- The prior estimator envelope remains backward compatible in an explicitly
  undeclared mode, which is not evidence of M3 compliance. Mixed initialization
  states in one output batch produce an ambiguous wrapper summary rather than
  assuming that adapter order is lifecycle order.
- No state variables, frame values, scale method, initialization/reset policy,
  output rate, latency formula or ceiling, estimator algorithm, dataset, model,
  numerical backend, research threshold, or scientific contribution was
  selected. M3 and ADR-0004 remain in progress.
- Local verification: all 105 standard-library unit tests passed; repository
  policy passed for 66 files; the pinned schema harness passed 9 schemas and 7
  templates; Ruff lint/format and `git diff --check` passed. Two independent
  focused reviews reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the exact implementation
  commit, all 105 tests passed, repository policy passed for 66 files, and the
  checkout remained clean.
- The A10 smoke installed no dependency, downloaded no dataset, ran no model
  training, and created no checkpoint or retained experiment artifact. No Brev
  stop or termination action was taken.

## 2026-08-27 — M7 exact-pair translation RMSE kernel implemented

- Implementation evidence commit:
  `b81d276bff9fc3926b1b1f3d226331d6b974fc61` on branch `main`.
- Added immutable Cartesian translation trajectories with explicit trajectory,
  sequence, segment, sample, reference/tracked frame, transform direction,
  translation unit, clock, timestamp-semantics, and timestamp identity.
  Distinct samples at one timestamp remain observable and deterministically
  ordered; empty segments remain representable for later failure accounting.
- Added one stable metric kernel for
  `sqrt(mean(||reference_position - estimated_position||^2))` over exact
  pre-paired samples. Every invocation supplies a policy explicitly declaring
  exact association, no interpolation, no alignment, and no scale correction.
- Negative controls prove constant offsets, global rotation, and scale errors
  remain nonzero. Sequence, segment, sample identity/time, frame, direction,
  unit, clock, and time-semantics mismatches fail before computation; empty or
  partial traces are not silently reported as survivors.
- Component-global scaled accumulation handles large and tiny finite residuals
  without intermediate square/norm overflow. Nonexact integer coordinates,
  nonfinite differences, final overflow, and positive-error underflow fail
  explicitly instead of producing a false zero or infinity.
- This kernel is not aligned ATE, RPE, metric-scale proof, coverage/failure
  evidence, or a complete evaluator. It selects no final association/alignment
  protocol, numerical threshold, estimator, sensor, dataset, model, or backend.
  M7 and M3 remain in progress.
- Local verification: all 123 standard-library tests passed; repository policy
  passed for 71 files; the pinned schema harness passed 9 schemas and 7
  templates; Ruff lint/format and `git diff --check` passed. Two focused
  adversarial reviews reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the exact implementation
  commit, all 123 tests passed, repository policy passed for 71 files, and the
  checkout remained clean.
- The A10 smoke installed no dependency, downloaded no dataset, ran no model
  training, and created no checkpoint or retained experiment artifact. No Brev
  stop or termination action was taken.

## 2026-08-27 — M7 explicit output-coverage accounting implemented

- Implementation evidence commit:
  `75d5a3181abace3bb825fe48ea7749f99348bf2d` on branch `main`.
- Added an immutable nonempty expected-opportunity denominator and a separate
  ordered outcome ledger. Outcomes must match every independently declared
  opportunity ID exactly and in order; omitted, extra, duplicate, or reordered
  outcomes fail rather than increasing apparent coverage.
- Each outcome records missing, invalid, or valid output state independently
  from reference availability and explicit usability. A usable outcome requires
  a valid output plus an available reference; every non-usable outcome retains
  one or more unique reason codes under named opportunity, classification, and
  reason-schema identifiers.
- The summary retains the complete ledger and reports exact expected, produced,
  missing, invalid, valid, reference-available/unavailable, usable, and
  non-usable counts plus derived fractions and deterministic multi-label reason
  counts. Public summaries are recomputed against the ledger so forged count
  partitions are rejected.
- This primitive does not infer an output schedule, timestamp association,
  lifecycle completion, initialization/reset behavior, tracking loss,
  estimator failure, position accuracy, or a pass/fail threshold. It prevents
  silent omission inside a declared opportunity set but does not complete
  `R-RI-004`, `R-EVAL-001`, or M7 by itself.
- Local verification: all 137 standard-library tests passed; repository policy
  passed; the pinned schema harness passed 9 schemas and 7 templates; Ruff
  lint/format, compileall, and `git diff --check` passed. Two focused read-only
  reviews reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the exact implementation
  commit, all 137 tests passed, repository policy passed for 73 files, and the
  checkout remained clean.
- The A10 smoke installed no dependency, downloaded no dataset, ran no model
  training, and created no checkpoint or retained experiment artifact. No Brev
  stop or termination action was taken.

## 2026-08-27 — M7 replay/output coverage binding implemented

- Implementation evidence commit:
  `3c4d48a10ae2333ed05abe8e0000681efa93b51b` on branch `main`.
- Added immutable retained event/output batches and exact output-envelope slots.
  Every declared opportunity identifies its triggering replay event; valid and
  invalid outcomes bind to a precise zero-based position in that event's raw
  output tuple, while a missing outcome explicitly binds to no output ordinal.
- The binding requires all expected opportunities in ledger order and every
  observed output envelope exactly once. Unknown events, wrong sequence indexes,
  out-of-range or reused ordinals, missing/extra/reordered slots, output-validity
  mismatches, and unbound overproduction fail visibly.
- Retained batch events are reconstructed through the canonical `CausalReplay`
  validator, preserving unique event/index identity, one clock, availability
  order, and strictly increasing measurement time within each stream. Output
  clocks and availability relative to their triggering event are rechecked.
- Binding is by event identity and tuple ordinal, never timestamp proximity or
  output value. Zero and multiple outputs per event, equal-valued envelopes,
  invalid input events, reset events, and unrelated zero-output events remain
  observable without assuming an output rate or failure classification.
- Caller-supplied batches do not prove they came from `EstimatorSession`; full
  execution recording, adapter-internal reset proof, lifecycle completion, and
  failure policy remain open. This slice does not complete M7.
- Local verification: all 152 standard-library tests passed; repository policy
  passed for 75 files; the pinned schema harness passed 9 schemas and 7
  templates; Ruff lint/format, compileall, and `git diff --check` passed. Two
  focused adversarial reviews reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the exact implementation
  commit, all 152 tests passed, repository policy passed for 75 files, and the
  checkout remained clean.
- The A10 smoke installed no dependency, downloaded no dataset, ran no model
  training, and created no checkpoint or retained experiment artifact. No Brev
  stop or termination action was taken.

## 2026-08-27 — M7 causal replay-to-estimator execution recorder implemented

- Implementation evidence commit:
  `a16c81baa71da5c249414b584e515ea6a341ab94` on branch `main`.
- Added a direct recorder that constructs and privately retains one fresh,
  clock-matched causal replay and estimator session. Replay releases at most one
  event before each estimator delivery, so an estimator failure cannot consume
  the later event suffix.
- Successful evidence retains only complete, validated event/output batches.
  The first consumed event affected by release, delivery, output validation, or
  batch retention failure is recorded separately with its exception type and
  exact session-delivery/reset-transition progress. Ordinary processing failure
  is terminal; process-control exceptions terminalize the recorder and are
  re-raised.
- Structurally frozen in-memory snapshots bind the complete planned event tuple,
  exact attempted prefix, watermark, replay/session counts, exhaustion state,
  and reset generation. They reject coherent count/state forgeries, impossible
  reset ordering, hidden output containers, and forged domain-record types.
  Generic payloads are not deep-copied and no persistent full-run trace exists
  yet.
- Added fault-injection controls for interruption inside replay cursor/watermark
  update, immediately after event release, before session delivery, between reset
  transition and delivery recording, and during batch retention. These cases
  either roll back an uncommitted release or retain an auditable terminal failure
  without silently losing the later replay suffix.
- Local verification: all 179 standard-library tests passed; repository policy
  passed for 77 files; the pinned schema harness passed 9 schemas and 7
  templates; Ruff lint/format, compileall, and `git diff --check` passed. Three
  focused read-only/adversarial reviews reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the exact implementation
  commit, all 179 tests passed, repository policy passed for 77 files, and the
  checkout remained clean.
- The A10 smoke installed no dependency, downloaded no dataset, executed no VIO
  algorithm or model training, and created no checkpoint or retained experiment
  artifact. No Brev stop, reboot, deletion, or termination action was taken.
- This slice closes the caller-supplied-batch provenance gap only for the
  recorder path. Persistent trace serialization, expected-opportunity creation,
  failed-trigger coverage integration, complete lifecycle/failure policy,
  adapter-internal lineage/reset proof, resource timing, ATE/RPE, and scientific
  success criteria remain open. M7 remains in progress.

## 2026-08-27 — M7 exact-pair signed translation residuals implemented

- Implementation evidence commit:
  `cab6e566e084868c1d975c3fe7051b20485abad8` on branch `main`.
- Added an ordered, frozen residual series that retains signed
  estimated-minus-reference Cartesian translation components for every exact
  sample pair. It reuses the existing explicit exact-association,
  no-interpolation, no-alignment, and no-scale-correction policy.
- The residual and RMSE operations now share one exact-pair validator. Empty,
  partial, reordered, convention-mismatched, non-finite, or numerically
  unrepresentable differences fail visibly; the stable RMSE accumulator remains
  unchanged.
- Added focused controls for signed direction, equal-time sample ordering,
  offsets, rotations, scale errors, finite extremes, public-record forgery, and
  integer-difference precision. M7 remains in progress: this is not ATE/RPE,
  coverage/completion evidence, frame-correctness proof, or a real-data result.
- Local verification: all 191 standard-library tests passed; repository policy
  passed for 78 files; the pinned schema harness passed 9 schemas and 7
  templates; Ruff lint/format, compileall, and `git diff --check` passed. A
  focused adversarial review reported no remaining P0/P1 findings.
- A read-only Brev observation found `compact-vio-uav-gpu` `RUNNING`, `READY`,
  and `HEALTHY`. Its clean checkout fast-forwarded to the implementation commit;
  all 191 tests and the 78-file repository-policy check passed there.
- The A10 smoke installed no dependency, downloaded no dataset, executed no VIO
  algorithm or model training, and created no checkpoint or retained experiment
  artifact. No Brev stop, reboot, deletion, or termination action was taken.

## 2026-08-27 — Modular refactor proposed and terminal execution coverage added

- Working-tree evidence only at this review: the changes are not yet committed,
  pushed, or backed by a new remote CI run.
- Replaced the obsolete training-first ADR-0004 working direction with a
  review-ready reliability-aware modular local-VIO proposal. Its status is
  `Proposed`, not `Accepted`; ADR-0002 remains authoritative until explicit
  owner acceptance.
- Aligned README, architecture, roadmap, research protocol, requirements, and
  ADR index around a separate native reference and internal
  A/B/C/D-monitor/D configurations. Added explicit research-scope versus later
  confirmatory freezes, ground-truth separation with Version 1 evaluation use
  and a conditional training-membership-label exception, same-backend fairness,
  Version 1 no-project-training proposal, discovery failure atlas, and
  conditional targeted training.
- Preserved the existing repository structure. No empty `data/`, `backend/`,
  `inertial/`, `vision/`, `fusion/`, `health/`, `estimators/`, or `learning/`
  scaffold was created; those paths appear only with their first accepted,
  tested behavior.
- Added `compact_vio.evaluation.bind_recorded_output_coverage`. It accepts an
  exact terminal recorder snapshot plus caller-declared coverage/slots, binds
  every successful output envelope exactly once, and allows explicit missing
  slots for the failed event and unattempted suffix. It creates no opportunity,
  reason, failure taxonomy, threshold, completion, or success decision.
- Revalidated nested replay events, failures, output conventions, coverage
  ledgers/outcomes/reason counts, and event/output batches so forged inner
  records cannot bypass either coverage-binding boundary.
- Local verification: all 207 standard-library tests passed; repository policy
  passed for 80 files; the pinned schema harness passed 9 schemas and 7
  templates; compileall, Ruff lint/format, and `git diff --check` passed. One
  behavior-preserving `isinstance` union-style update was applied to the
  existing sensor contract so repository-wide Ruff 0.12.12 remains clean.
- Exact local validation commands:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -q
  PYTHONPATH=src python3 -m compact_vio.repository_policy .
  uv run --no-project --with 'jsonschema[format-nongpl]==4.26.0' python scripts/validate_schemas.py
  PYTHONPATH=src python3 -m compileall -q src tests
  uv run --no-project --with ruff==0.12.12 ruff check .
  uv run --no-project --with ruff==0.12.12 ruff format --check .
  git diff --check
  ```

- Remaining milestone blockers: M3 still needs owner acceptance of the
  research-scope proposal and concrete estimator-interface values; M6 still
  needs that accepted scope plus one exact rights-approved dataset unit/role;
  M7 still needs the remaining lifecycle/evaluator semantics and real-data
  validation; M8 still needs M5–M7 evidence, frozen feasibility criteria, and
  dependency-rights review, followed by a future Accepted backend-selection ADR
  before M9 can begin.
- Protocol deviation: none. This slice changed only the proposed documentation
  direction and framework-neutral evidence contracts; it did not execute a
  dataset-, backend-, model-, training-, deployment-, or worker-specific step.
- No dataset or sequence was approved or downloaded. No mono/stereo choice,
  backend, visual method, learned component/weights, framework, health signal,
  reliability action/threshold, numerical confirmation threshold, training,
  checkpoint, export, deployment target, or licence was selected.
- No Brev/A10 command, paid-worker action, model training, stop, deletion, or
  termination occurred.

## 2026-08-27 — M7 recorder lifecycle-policy declaration implemented

- The preceding modular refactor and terminal execution-coverage slice were
  committed as `2fa6cdc` and pushed to `origin/main` before this slice began.
- Added the immutable, no-default `ExecutionLifecyclePolicyDeclaration` to the
  causal recorder boundary. It requires caller-supplied versioned IDs for replay
  exhaustion, ordinary processing exceptions, process-control exceptions, and
  the unattempted replay suffix; the recorder and every snapshot retain and
  structurally revalidate the exact declaration.
- The declaration records semantic identity only. It does not select a failure
  taxonomy, threshold, output schedule, completion rule, run-success rule, or
  scientific acceptance criterion. M7 remains in progress.
- Migrated the terminal recorder-coverage tests to the typed declaration and
  added focused no-default, wrong-type, immutability, raw-string, nested-forgery,
  and active/completed/failed retention controls.
- Working-tree evidence at this entry: 210 standard-library tests passed;
  repository policy passed for 80 files; the pinned schema harness passed 9
  schemas and 7 templates; compileall, Ruff 0.12.12 lint/format, and
  `git diff --check` passed. The immutable implementation commit and remote
  push are recorded in the next append-only evidence entry.
- No dataset or sequence was approved or downloaded. No backend, model,
  learned weights, framework, threshold, training job, checkpoint, deployment
  target, or estimator policy meaning was selected. No Brev/A10 command or
  lifecycle action occurred.

## 2026-08-27 — M7 terminal recorder-envelope representation implemented

- Lifecycle-policy implementation evidence commit `76c2061` was pushed to
  `origin/main`. It retained the immutable typed lifecycle declaration and all
  210 tests passed before this envelope slice began.
- Added `compact_vio.execution_trace`, a one-way terminal snapshot projection
  with a strict structural Draft 2020-12 schema. It emits deterministic sorted
  UTF-8 JSON containing the full planned-event envelope order, successful
  output-envelope order, lifecycle-policy IDs, progress counts, and
  first-failure metadata.
- Event and estimator payloads are selected out manually. The encoder derives no
  field by traversing, representing, typing, hashing, or serializing them;
  cyclic, secret-bearing, and representation-raising payload controls pass.
  Different payloads with equal envelope metadata intentionally produce equal
  bytes.
- This is not a full trace or serialized `RecorderSnapshot`. There is no
  deserializer, filesystem writer, or run-manifest integration, and the envelope
  does not establish payload identity, reconstruction, replayability, dataset
  provenance, adapter lineage, coverage semantics, lifecycle success, or
  scientific acceptance. M7 remains in progress.
- Schema validity alone does not authenticate recorder origin or prove every
  cross-array count/reference in arbitrary external JSON. The trusted path is
  encoder output from a validated terminal snapshot.
- Working-tree verification: all 218 standard-library tests passed; repository
  policy passed for 83 files; the pinned schema harness passed 10 schemas and 7
  templates; generated-envelope positive and payload/state negative schema
  controls passed; compileall, Ruff 0.12.12 lint/format, and `git diff --check`
  passed.
- No dataset/sequence, backend, estimator algorithm, model/weights, framework,
  threshold, training job, checkpoint, deployment target, or lifecycle-policy
  meaning was selected. No Brev/A10, paid-worker, download, training, stop,
  deletion, or termination action occurred.

## 2026-08-27 — M7 lifecycle and envelope commits verified remotely

- Typed lifecycle-policy implementation commit
  `76c2061bf716fbf0eefd0ca986d12353b6a074d0` passed GitHub Actions CI in
  [run 33136293781](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33136293781).
- Terminal recorder-envelope implementation commit
  `76ffd7da08448cd1588421f2aa00e2342d1c617f` passed GitHub Actions CI in
  [run 33137181405](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33137181405).
- `origin/main` and the local branch both resolved to the envelope implementation
  commit when these remote results were recorded. No dataset, training, GPU, or
  lifecycle action was part of either CI run.

## 2026-08-27 — ADR-0004 owner-review decision brief prepared

- Added a non-authoritative, source-backed decision brief under
  `docs/adr/evidence/`. It recommends one bounded target phenomenon/population,
  a full-run failure-aware endpoint family, parent acquisition groups as the
  inferential unit, paired C/D/D-monitor comparisons, a same-backend fairness
  contract, falsification rule, and claim/control matrices.
- Linked the brief from ADR-0004, the ADR index, and the immediate execution
  queue. ADR-0004 remains `Proposed`; the brief is review input and records no
  owner approval or decision date.
- The brief selects no dataset or sequence, mono/stereo setup, backend, visual
  method, learned component, action, reliability signal, numerical threshold,
  trial count, statistical test, training framework, compute budget,
  deployment target, or flight scope.
- Local verification: all 218 standard-library tests passed; repository policy
  passed for 84 files; the pinned schema harness passed 10 schemas and 7
  templates; compileall, Ruff 0.12.12 lint/format, and `git diff --check`
  passed.
- Exact local validation commands:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -q
  PYTHONPATH=src python3 -m compact_vio.repository_policy .
  uv run --no-project --with 'jsonschema[format-nongpl]==4.26.0' python scripts/validate_schemas.py
  PYTHONPATH=src python3 -m compileall -q src tests
  uv run --no-project --with ruff==0.12.12 ruff check .
  uv run --no-project --with ruff==0.12.12 ruff format --check .
  git diff --check
  ```

- Remaining authority gate: the project owner must accept or reject the seven
  ADR-0004 checklist items and record the date. M6 then still requires separate
  owner approval of one exact dataset scope and a rights review; M7/M8 retain
  their documented evaluator and feasibility gates.
- Protocol deviation: none. No dataset download, Brev/A10 command, paid-worker
  action, training, checkpoint, worker stop, deletion, or termination occurred.

## 2026-08-27 — ADR-0004 decision brief verified remotely

- Owner-review package commit
  `946381caea7f3d2b5a6d0fa5558a53a6b13cb6c4` was pushed to `origin/main`.
- GitHub Actions CI passed for Python 3.10 and 3.12 in
  [run 33138277337](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33138277337).
- An independent adversarial documentation review reported no remaining
  P0/P1/P2 finding after verifying the degraded primary population, separate
  nominal guardrail population, acquisition-level inferential unit,
  A/B/C/D-monitor/D fairness contract, source limits, and `Proposed` authority
  boundary.
- No owner decision was inferred from the passing checks. No dataset, training,
  GPU, paid-worker, or lifecycle action was part of this evidence slice.

## 2026-08-27 — Representative dataset candidates screened from official sources

- Added the non-authoritative
  `governance/datasets/evidence/representative-unit-candidate-brief.md` and
  linked it from the dataset policy, candidate registry, and immediate execution
  queue. Every registry entry remains `candidate` with an unresolved project
  role; ADR-0004 remains `Proposed`; M6 remains blocked.
- The brief records EuRoC as the provisional technical review lead for one
  future real-MAV integration-unit review, UZH-FPV as the provisional
  high-motion stress review lead, TUM VI as handheld calibration/evaluator
  support, and TartanAir/Mid-Air as synthetic discovery candidates. These are
  evidence-screening descriptions, not selections or approved project roles.
- Blackbird remains on hold because its repository software license does not
  establish dataset-file rights. The ETH illumination dataset remains on hold
  because its advertised DOI resolved to an unrelated record and no
  authenticated archive/rights record was established. VIODE was screened out
  as a non-candidate for the proposed blur/illumination scope.
- Two independent adversarial reviews reported no remaining P0/P1/P2 findings
  after checking official-source claims, rights labels, ground-truth coverage,
  domain distinctions, leakage grouping, links, and approval boundaries.
- Local verification: all 218 standard-library tests passed; repository policy
  passed for 85 files; the pinned schema harness passed 10 schemas and 7
  templates; registry YAML parsing, compileall, Ruff 0.12.12 lint/format, and
  `git diff --check` passed.
- Exact local validation commands:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -q
  PYTHONPATH=src python3 -m compact_vio.repository_policy .
  uv run --no-project --with 'jsonschema[format-nongpl]==4.26.0' python scripts/validate_schemas.py
  ruby -e 'require "yaml"; YAML.safe_load_file("governance/datasets/registry.yaml", permitted_classes: [], aliases: false); puts "registry YAML: PASS"'
  PYTHONPATH=src python3 -m compileall -q src tests
  uv run --no-project --with ruff==0.12.12 ruff check .
  uv run --no-project --with ruff==0.12.12 ruff format --check .
  git diff --check
  ```

- Remaining authority gates: a dated owner decision on ADR-0004; then separate
  project-owner approval of one exact dataset release/unit/modalities/role/split
  and acquisition location plus dataset-file rights review, exact size/hash,
  calibration/timestamp/GT evidence, and storage authority.
- Protocol deviation: none. No dataset byte was downloaded or inspected; no
  sequence, modality, role, split, location, backend, model, framework,
  threshold, or training action was selected. No Brev/A10, paid-worker,
  lifecycle, deletion, or termination action occurred.

## 2026-08-27 — Dataset candidate brief verified remotely

- Candidate-screening commit
  `cdb5cff36df5585c88cfdaf4c7786fe30e2fea52` was pushed to `origin/main`.
- GitHub Actions CI passed for Python 3.10 and 3.12 in
  [run 33139733430](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33139733430).
- The remote checks compiled, built, and installed the package; exercised the
  command-line tools; ran the unit suite; checked scratch exclusions; ran Ruff;
  and validated schemas and contract fixtures.
- No dataset approval, acquisition, download, inspection, role/split assignment,
  training, GPU, paid-worker, or lifecycle action was part of the CI run.

## 2026-08-28 — EuRoC-to-checkpoint prototype executed on the A10

- Training-first implementation commit
  `9199d1507a2a76c522ca265afd8527ef9bd07225` was pushed before GPU execution.
  GitHub Actions passed for Python 3.10 and 3.12 in
  [run 33143004849](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33143004849).
  Local validation ran 256 tests with 5 dependency-gated skips; all 256 tests
  passed on the A10 with PyTorch installed. Repository policy passed for 108
  files, the schema harness passed 10 schemas and 7 templates, and Ruff lint,
  Ruff format, and `git diff --check` passed.
- The official EuRoC Vicon Room 1 and Room 2 archives matched their configured
  byte counts, ETH MD5 values, and SHA-256 values. The six extracted `cam0`
  frame counts were 2,912 (`V1_01_easy`), 1,710 (`V1_02_medium`), 2,149
  (`V1_03_difficult`), 2,280 (`V2_01_easy`), 2,348 (`V2_02_medium`), and 1,922
  (`V2_03_difficult`). Exact identities, rights, modalities, roles, and hashes
  are recorded in `configs/data/euroc_vicon_v1.json` and
  `governance/datasets/evidence/euroc-vicon-acquisition-2026-08-28.md`.
- A bounded smoke run completed in 12.43485 seconds at
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v1-smoke-9199d15`; its
  checkpoint SHA-256 was
  `f3f58e55de225d1a06d8d68f687b6f5909bca53eda97a1e1cc268131a32930d9`.
- The full NVIDIA A10 / PyTorch 2.7.0 run completed all 30 configured epochs in
  225.2446 seconds. The compact model has 2,989,766 parameters. It used 6,217
  training pairs, 2,093 validation pairs, and 1,889 held-out test pairs. Epoch
  7 was selected with validation pair RMSE of 0.0375253 m translation and
  0.00818984 rad rotation.
- On held-out `V2_03_difficult`, pair RMSE was 0.0537358 m translation and
  0.0201182 rad rotation. Raw exact-pair, no-alignment trajectory evaluation
  reported 6.62533 m translation ATE, 6.82426 m final translation drift, and
  42.0964 m predicted path length versus 85.9893 m reference path length.
- This is a successful end-to-end execution result, not a model-quality pass.
  Pair translation only narrowly improved on the zero-motion value of
  0.0564645 m, while raw trajectory ATE was worse than the zero-motion value of
  2.05572 m because scale and directional errors accumulated. No superiority,
  deployment, onboard-runtime, or flight claim is supported.
- The full result remains at worker path
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v1-full-9199d15` and was
  copied to ignored local path
  `outputs/euroc-compact-vio-v1-full-9199d15`. Checkpoint SHA-256
  `d11fabf7fc36c0a16719f7a3f73202b5888869f0efb252ba354a86ef28931738`
  and artifact-manifest SHA-256
  `143cad6b475af1fe204196e9b0d571c98ed1cf62ffbb9169ff1886ce8e4e659a`
  matched on the worker and local copy. This verification does not by itself
  satisfy the independent recovery-copy requirement in M2.
- M6 and M8 are complete. M7 remains in progress. M9 is now in progress because
  held-out inference ran, but a versioned baseline, inference latency/memory,
  complete coverage/failure evidence, and model improvement remain. The worker
  was intentionally left running; no stop, deletion, or termination action was
  taken.

## 2026-08-28 — Exploratory stride-augmented v2 run completed on the A10

- Commit `92aa3294002a9da5861961a314fe74e2bb1ada05` added a versioned
  exploratory configuration with training frame strides 1 and 2. The model and
  native stride-1 evaluation path were otherwise retained. The full A10 run
  completed in 422.111738068 seconds, used 12,431 training pairs and 4,185
  validation pairs, and selected epoch 28.
- Native stride-1 evaluation produced all 1,889 of 1,889 eligible/selected
  `V2_03_difficult` pairs. Pair RMSE was 0.0499360933 m translation and
  0.00516902818 rad rotation. Raw exact-pair, no-alignment evaluation reported
  6.33804218 m translation ATE, 6.23185397 m final translation drift, and
  54.9195732 m predicted path length versus 85.9893305 m reference path length,
  a predicted/reference ratio of 0.6386789.
- The recorded zero-motion reference had 0.0564645414 m pair translation RMSE,
  0.0482671721 rad pair rotation RMSE, 2.05571752 m raw translation ATE, and
  2.22648942 m final translation drift. Relative to v1, v2 reduced overall pair
  translation RMSE by 7.071%, pair rotation RMSE by 74.307%, raw ATE by 4.336%,
  and final drift by 8.681%. In the pair-interval diagnostic, 0.05-second
  translation worsened by 1.442% while rotation improved by 45.313%; at 0.10
  seconds, translation improved by 13.517% and rotation by 80.834%.
- The inference measurement covered exactly
  `predict-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
  It reported 5,482.75 pairs/s, batch-latency p50/p95 of 8.215/14.078 ms, CUDA
  peak allocated memory of 267,884,544 bytes, and peak reserved memory of
  322,961,408 bytes. No dedicated warmup batch was run, so this is an
  exploratory worker measurement, not a target-runtime benchmark.
- The retained checkpoint SHA-256 is
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`; the
  artifact-manifest SHA-256 is
  `fb0e04398af590e3ca2d708bc7bcae74ed8afc7834a6b9b329677fe869d998c8`.
  The bundle is present at worker path
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v2-stride-full-92aa329` and
  ignored local path `outputs/euroc-compact-vio-v2-stride-full-92aa329`.
- This run is exploratory, not a fresh held-out or confirmatory result: the v1
  `V2_03_difficult` outcome informed the stride augmentation. Although v2
  improved every overall learned metric, raw ATE and drift remain substantially
  worse than zero motion. No model-quality, superiority, deployment,
  onboard-runtime, or flight claim is supported. M7 and M9 remain in progress.
  The worker remains running; no stop, deletion, or termination action was
  taken.

## 2026-08-28 — Exploratory stateful v3 run completed on the A10

- Commit `336e88c7e80f6841c7d25b7da311172b40f5a3ba` added eight-pair causal
  recurrent training unroll, explicit state input/output, and state carry only
  across contiguous chunks of the same evaluation chain. GitHub Actions
  [run 33146072746](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33146072746)
  succeeded, and all 273 tests passed on the A10 with PyTorch installed.
- The full deterministic AMP run completed 30 epochs in 443.290710302 seconds,
  used 12,431 training pairs and 4,185 validation pairs, and selected epoch 26.
  Its selected validation result was 0.0524893811 m translation RMSE,
  0.0100984845 rad rotation RMSE, and 0.000476185769 total loss.
- Native stride-1 evaluation produced all 1,889 of 1,889 eligible, selected,
  and produced `V2_03_difficult` pairs. The evaluation used 128-pair chunks,
  carried state only across contiguous same-chain chunks, and recorded one
  state reset for the complete sequence.
- Pair RMSE was 0.0490458270 m translation and 0.00951882642 rad rotation. Raw
  exact-pair, no-alignment evaluation reported 5.03624842 m translation ATE,
  5.99848752 m final translation drift, and 47.6075271 m predicted path length
  versus 85.9893305 m reference path length, a ratio of 0.553644584.
- Relative to v2, v3 reduced overall pair translation RMSE by 1.782811%, raw
  ATE by 20.539367%, and final drift by 3.744736%. Pair rotation RMSE worsened
  by 84.151181%, and the path ratio moved farther from 1.0. For the 1,482
  approximately 0.05-second pairs, translation improved by 3.910307% and
  rotation worsened by 81.751270%; for the 407 exact 0.10-second pairs,
  translation worsened by 0.220455% and rotation worsened by 86.573980%.
- The zero-motion control remained better on integrated trajectory measures:
  2.05571752 m raw ATE and 2.22648942 m final drift. V3 remained better than
  zero motion on local pair translation and rotation RMSE. The stateful result
  is therefore mixed rather than an across-the-board improvement.
- The declared inference scope was
  `predict-sequence-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
  Across 15 batches it reported 1,732.648988 pairs/s, 1.090238 seconds total,
  batch-latency p50/p95 of 67.417437/151.718379 ms, and CUDA peak
  allocated/reserved memory of 456,700,928/543,162,368 bytes. No dedicated
  warmup batch was run; this remains an A10 worker measurement, not an
  embedded-target benchmark.
- The retained checkpoint SHA-256 is
  `40d18a9a3a04131d04e06a4ab313279613d1dc2339d1758f99777ecb70de8c37`.
  The artifact-manifest SHA-256 is
  `4244c8841eb3498b150628c3c8126efbf6af90d544c85c9e22e9a79f4e15801f`,
  independently identical for worker path
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v3-stateful-full-336e88c`
  and ignored local path
  `outputs/euroc-compact-vio-v3-stateful-full-336e88c`.
- Earlier `V2_03_difficult` evidence motivated recurrent unroll, so this is
  exploratory development evidence, not fresh held-out confirmation. It makes
  no superiority, generalization, deployment, onboard-resource, safety, or
  flight-readiness claim. M7 and M9 remain in progress. The worker remains
  running; no stop, deletion, or termination action was taken.

## 2026-08-28 — Exploratory translation-state v4 run completed on the A10

- Commit `94d834a82bddb2e6185fb70ec289fd45017c325c` introduced one
  controlled routing change to v3: translation retained the carried recurrent
  fusion state, while rotation used a zero-initialized current-pair fusion
  state. Parameter shapes, data and split, optimizer, seed, loss, strides,
  unroll, evaluation state-carry policy, and 30-epoch schedule were retained.
  The training-config SHA-256 was
  `ca8d95e9502383897e78b81274dc375b219a7b29cad0e42c71ac8c5bdc0ce85a`.
  GitHub Actions
  [run 33147863994](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33147863994)
  succeeded, and all 282 tests passed on the A10 with PyTorch installed.
- The full deterministic AMP run completed 30 epochs in 489.976979739 seconds,
  used 12,431 training pairs and 4,185 validation pairs, and selected epoch 30.
  Its selected validation result was 0.05176842235 m translation RMSE,
  0.007315933953 rad rotation RMSE, and 0.0004555820835 total loss.
- Native stride-1 evaluation produced all 1,889 of 1,889 eligible, selected,
  and produced `V2_03_difficult` pairs. It carried state only across contiguous
  same-chain chunks and recorded one reset for the complete sequence.
- Pair RMSE was 0.04750855571 m translation and 0.006040955812 rad rotation.
  Raw exact-pair, no-alignment evaluation reported 4.008623564 m translation
  ATE, 4.499084473 m final translation drift, and 43.910657836 m predicted path
  length versus 85.989330474 m reference path length, a ratio of 0.5106523983.
- Relative to v3, v4 reduced overall pair translation RMSE by 3.134357%, pair
  rotation RMSE by 36.536758%, raw ATE by 20.404570%, and final drift by
  24.996352%. Its path ratio nevertheless moved farther from 1.0, from
  0.553645 to 0.510652. For the 1,482 approximately 0.05-second pairs,
  translation improved by 4.618060% and rotation by 37.118336%; for the 407
  exact 0.10-second pairs, translation improved by 1.841451% and rotation by
  35.977304%.
- The frozen replacement rule required lower pair translation RMSE and lower
  raw ATE than v3, plus pair rotation RMSE no worse than v2. V4 passed the
  translation and ATE gates but failed rotation: its rotation RMSE was
  16.868309% worse than v2. It was therefore rejected as the replacement
  candidate. Zero motion also remained better on raw ATE and final drift.
- The declared inference scope was
  `predict-sequence-batch-model-placement-eval-host-to-device-forward-and-device-to-host`.
  Across 15 batches it reported 1,058.729410 pairs/s, 1.784214155 seconds
  total, batch-latency p50/p95 of 114.579536/200.278403 ms, and CUDA peak
  allocated/reserved memory of 456,700,928/543,162,368 bytes. No dedicated
  warmup batch was run; this remains an A10 worker measurement, not an
  embedded-target benchmark.
- The retained checkpoint SHA-256 is
  `e775adb16aa4f9522aa577a32704a54db5c82c53685b0e97fb8d149402bf159d`.
  The artifact-manifest SHA-256 is
  `d28aca790a5c70b6e2763583f9098427e09c967a0774dd49fe07bbca4858489f`,
  independently identical for worker path
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v4-translation-state-full-94d834a`
  and ignored local path
  `outputs/euroc-compact-vio-v4-translation-state-full-94d834a`.
- Earlier `V2_03_difficult` evidence motivated this controlled change, so it is
  exploratory development evidence rather than fresh held-out confirmation.
  It makes no superiority, generalization, deployment, onboard-resource,
  safety, or flight-readiness claim. `V2_03_difficult` is closed to any further
  model or hyperparameter selection; the next quality decision requires a
  fresh, predeclared evaluation unit. M7 and M9 remain in progress. The worker
  remains running; no stop, deletion, or termination action was taken.

## 2026-08-28 — Frozen MH_01 position-only checkpoint evaluation completed

- Evaluation commit `deea10f767dd207c181d09521d47667cc15c8d6d` was on
  `origin/main`. The completed NVIDIA A10 / PyTorch 2.7.0 evaluation ran from
  `2026-08-28T07:45:34.870708Z` to `2026-08-28T07:47:00.566678Z` and recorded
  `85.6959709560033` seconds total duration.
- GitHub Actions succeeded for Python 3.10 and 3.12 in
  [run 33152517547](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33152517547).
  The A10 gate ran all 329 tests successfully, including the new
  dependency-gated PyTorch end-to-end evaluation smoke.
- Evaluation ID `euroc-mh01-frozen-checkpoints-position-v1` used protocol
  `configs/evaluation/euroc_mh01_frozen_checkpoints_position_v1.json`, SHA-256
  `2610644fdcffaf2d44f327f3135de3795cfcaa91f7d9a8491d850035a7073425`.
  It froze exact checkpoint, association, sensor-origin projection, metric, and
  decision identities before predictions were inspected; no model,
  hyperparameter, checkpoint, association, alignment, scale, threshold, or
  rule tuning occurred during evaluation.
- Dataset identity was EuRoC `MH_01_easy`, DOI
  `10.3929/ethz-b-000690084`, under the recorded
  `In Copyright - Non-Commercial Use Permitted` statement. The
  12,683,729,426-byte `machine_hall.zip` archive had MD5
  `363f5c2502b469cdd97ef85997714806` and SHA-256
  `5ed7d07903f8d19b6c8808e2ae8a0872b281f6e34ef5497023b8ac58c3de0f6f`.
  Sensor-source, sensor-calibration, and position-reference SHA-256 values were
  `10dd5e711a8c063c16b65d2fe69baa979e8b39299bcaaf5643c5683f27a6977f`,
  `966b51d7ecd4086f0c7f8ccb6644d8d66447f5eb703c4398c3bf0bde10f16085`,
  and `5ff4628faea7594c21668f6e31b9e92718ce844902da225b2727acc880742ee0`.
- The source contained 3,682 camera frames, 36,820 IMU measurements, and 3,099
  Leica position samples. The frozen linear association retained 3,139 camera
  frames, all interpolated and none exact at a reference timestamp. It allowed
  no extrapolation and at most a 100,000,000 ns reference bracket. The maximum
  observed bracket was 647,000,064 ns; 543 frames were rejected over gaps, none
  outside reference coverage, and 207 contiguous reference segments remained.
  This yielded 2,926 eligible and 755 rejected native pairs.
- V2, v3, and v4 each received all 3,681 sensor pairs, produced all 3,681, and
  scored all 2,926 reference-eligible pairs; 755 produced pairs remained
  explicitly excluded by the reference rule. “Full reference coverage” in the
  decision therefore means every eligible pair was scored, not that the
  reference had no gaps.
- The declared Leica origin in the IMU/prediction frame was
  `[0.0748903, -0.0184772, -0.120209]` m. Predicted rotation affected the
  projected Leica displacement through this lever arm, but there was no
  independent reference orientation endpoint.
- Candidate checkpoint SHA-256 values were v2
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`,
  v3 `40d18a9a3a04131d04e06a4ab313279613d1dc2339d1758f99777ecb70de8c37`,
  and v4
  `e775adb16aa4f9522aa577a32704a54db5c82c53685b0e97fb8d149402bf159d`.
- In the order pair displacement-magnitude RMSE, cumulative scored-distance
  RMSE, predicted scored distance, reference scored distance, distance ratio,
  and total scored-distance error, exact position-only results were: zero
  motion `(0.02649378180034436, 35.44859693185987, 0.0,
  63.4297877162257, 0.0, 63.4297877162257)`; v2
  `(0.017339865612729627, 13.507518956747258, 38.7786801480933,
  63.4297877162257, 0.6113638645865039, 24.651107568132396)`; v3
  `(0.017810416665698072, 9.18286459081829, 46.772033634109,
  63.4297877162257, 0.7373827868281585, 16.657754082116696)`; and v4
  `(0.018905045864944767, 19.676000848537885, 28.49295141000196,
  63.4297877162257, 0.44920458409028075, 34.93683630622374)`, in metres
  except for the dimensionless ratio.
- All three candidates passed the frozen full-eligible-coverage and beat-zero
  gates. The rule selected the minimum pair displacement-magnitude RMSE with no
  tie-break; v2 was therefore selected for this position-only endpoint. V3's
  lower cumulative-distance RMSE was not the frozen selection field.
- The result remained at A10 path
  `/home/ubuntu/compact-vio-runs/euroc-mh01-frozen-position-deea10f` and was
  copied to ignored local path `outputs/euroc-mh01-frozen-position-deea10f`.
  `evaluation-summary.json` SHA-256 was
  `65d37221572c458ca86281ef01c3ae41345fb35b66c99ef632ddfe0f894de5b4`.
  The deterministic seven-file artifact manifest verified successfully at
  both paths with raw SHA-256
  `184d9427ebec373edb4da222bba5ea382146369a61b471b92b30b0e328ce8e76`.
  Metric/prediction hashes were v2
  `3860a222ba5efe2576050fd01d65723c75567bdfc9c17585914a5254586a3726` /
  `e0416e5af3f5fbbefbde148046d7e636213302adf5c24f4db60a435faa87f4d4`,
  v3 `82db78b164ffdec6acb44540f7f7ba3b57aba4e8b9c785fc51712a5bb05213a3` /
  `77447263b74079f7b257f4d2a2c23c66c7e0e306e7d0799e1910a78f3cfc7c6a`,
  and v4
  `c0223dac0e17f9a9d36fd7ba5b6d8847684ea2713c14662d291abbbe2739ce65` /
  `7ce297f9cdd50509fd5da22eee0ef221b8219e74f46d3f16a4d1fdb37cb0fded`.
  Matching content does not by itself satisfy the independent recovery-copy
  restore gate.
- This endpoint scores displacement magnitudes from exact preassociated
  position pairs with the declared lever arm and no internal interpolation,
  alignment, or scale fitting. It does not score displacement direction,
  heading, independent rotation, full pose, or ATE and does not support an
  estimator-wide superiority, generalization, publication, deployment,
  onboard-performance, safety, or flight claim. It does not erase the prior
  `V2_03_difficult` exploratory history. M7 and M9 remain in progress. The
  worker remains running by explicit choice; no stop, deletion, or termination
  action was part of this evaluation.
- Final post-documentation validation passed: 329 local tests with 29
  dependency-gated skips; repository policy checked 129 files with zero
  violations; the pinned schema harness passed 10 schemas and 7 templates
  while leaving every unresolved governance truth flag false; Ruff lint and
  format passed for all 100 Python files; compileall and `git diff --check`
  passed; and artifact verification reported `ok: true` with no missing,
  unexpected, size-mismatched, or hash-mismatched file. Exact commands:

  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -q
  PYTHONPATH=src python3 -m compact_vio.repository_policy .
  uv run --no-project --with 'jsonschema[format-nongpl]==4.26.0' python scripts/validate_schemas.py
  uv run --no-project --with ruff==0.16.4 ruff check .
  uv run --no-project --with ruff==0.16.4 ruff format --check .
  PYTHONPATH=src python3 -m compileall -q src tests
  git diff --check
  PYTHONPATH=src python3 -m compact_vio.artifacts verify outputs/euroc-mh01-frozen-position-deea10f
  ```

## 2026-08-28 — Controlled v5 implementation prepared locally

- Working-tree state at this entry: uncommitted on base revision
  `4076066875cb93aa44bc5180a00afb04b386669f`. An immutable implementation
  revision, remote CI result, clean execution checkout, and any paid-run
  evidence remain pending.
- Retained v2 remains the control: selected epoch 28, checkpoint SHA-256
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`,
  and independent-zero-state-per-pair inference policy. The local
  `compact-vio-export-inference` slice requires the expected source hash and
  state policy, binds canonical model-state and metadata hashes, retains the
  canonical `TrainingConfig`, provenance, source identity, and selected source
  epoch/metrics lineage, omits optimizer state and full training history,
  writes atomically without overwrite, and remains loadable through the normal
  `load_inference_model` boundary.
- The real selected v2 checkpoint was exported locally to a temporary
  non-repository path and passed bitwise prediction parity. The source
  checkpoint SHA-256 remained
  `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`;
  the temporary inference artifact, canonical metadata, and canonical
  model-state SHA-256 values were
  `4e2281a97a071cd20c16b2e5329a750b681fa74aea53002f110662ebc7fba29e`,
  `63f632912862067c471020d4cda4f2e87772eda0f2d59a29f434fba71a8be321`,
  and `f70693fc2c188773ef8e78779f6e5d1a01b22e14067204cd8cc18ba4691d650d`.
  Selected source epoch 28 and its exact metrics were retained as lineage. This
  temporary output is implementation verification, not a durable retained
  execution artifact.
- The controlled v5 configuration is
  `configs/training/euroc_compact_vio_v5_magnitude.json`, prospective SHA-256
  `7f5e50785ed1907c26f5bbea6766a4fc13fd3df591c8930ef8b15ac9f7d71af0`.
  Relative to v2, it changes only the experiment identity and adds
  `translation_magnitude_loss_weight: 1.0`. The objective is the sum of
  unit-weight Smooth-L1 translation-vector, translation L2-magnitude, and
  rotation losses. A zero default preserves legacy v1–v4 configuration and
  checkpoint behavior; v5 records the magnitude term separately.
- The selected v5 checkpoint is prohibited from inspecting `MH_02_easy` unless
  validation translation RMSE is at most `0.058765891780989885` m and
  validation rotation RMSE is at most `0.0061899144990098035` rad, the exact
  selected-v2 values. Missing, non-finite, or greater values reject v5 before
  the fresh unit.
- `configs/data/euroc_machine_hall_mh02_position_v1.json` prospectively reserves
  `MH_02_easy` from the already identified Machine Hall archive for one
  position-only v2/v5/zero-motion decision. Its prospective SHA-256 is
  `3546ed0ed0721224c156e8b929ba5cf3aba517da381cc0f832162380599ca137`.
  The final evaluation protocol and extracted source/calibration/reference
  identities remain pending. Once candidate results are inspected, this unit
  is consumed and cannot support another model decision.
- Observed local validation for this uncommitted slice: the full suite passed
  351 tests with 42 optional-dependency skips; repository policy checked 136
  files with zero violations; all 10 schemas and 7 templates passed; Ruff
  0.16.4 lint and format checks passed; compileall and `git diff --check`
  passed. The focused tests
  include single-change config identity, legacy compatibility, exact
  magnitude-loss arithmetic, finite gradients, separate metric recording,
  source-hash/overwrite/policy/integrity rejection, and bitwise inference
  parity on deterministic synthetic inputs.
- The controlled position evaluator now hard-codes the exact selected-v2
  validation translation/rotation limits, requires them in the future protocol,
  and preflights every checkpoint hash, inference policy, dataset provenance,
  split exclusion, and selected validation metric before loading the reserved
  sequence or producing a prediction. It also requires identical complete
  v2/v5 coverage and makes the v5-below-zero gate explicit.
- No retained v2 inference package was produced from an immutable revision, no
  v5 smoke or training run was launched, no v5 checkpoint or metric exists, and
  no `MH_02_easy` data or candidate result was inspected in this local slice.
  No worker, dataset, storage, lifecycle, ROS/PX4, or flight action was
  performed. M8's original vertical-slice exit remains complete; M9 remains in
  progress and M12 remains blocked.

## 2026-08-28 — Immutable v5 gate and retained v2 inference transport

- Revision `5c54bb5fe3c67ff93ace9401beae3c06c13b81fa` was pushed to
  `origin/main`; GitHub Actions run 33172588729 completed successfully.
- The clean A10 checkout reproduced that exact revision and passed all 351
  Torch-enabled tests from the checked-out `src` tree.
- The selected v2 training checkpoint was exported on that checkout with
  source SHA-256 `17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605`.
  The exact A10 inference file SHA-256 is
  `521e9813fde80f68cb0734fd474a1cf08e8d4ef767fc8cd53bd2adf08ead2202`;
  canonical metadata/model-state SHA-256 values are
  `63f632912862067c471020d4cda4f2e87772eda0f2d59a29f434fba71a8be321`
  and `f70693fc2c188773ef8e78779f6e5d1a01b22e14067204cd8cc18ba4691d650d`.
  A separate-process A10 repeat produced the same exact file hash.
- The A10 file was copied to ignored local evidence path
  `outputs/inference-exports-5c54bb5/v2-inference.pt`; its one-file artifact
  manifest verifies and has SHA-256
  `17a1b73abf1223fd8a010391d768849c30830c81914e2c30e7c383d61d095723`.
- Cross-runtime inspection proved that the local `4e2281a...` and A10
  `521e9813...` files have the same 43 ZIP members except PyTorch's internal
  `archive/.data/serialization_id`; canonical metadata, all tensor storages,
  model-state identity, and predictions match. The contract therefore treats
  the outer file SHA only as exact-file transport integrity and the canonical
  metadata/model-state hashes as cross-runtime model identity.
- No v5 smoke/full run or `MH_02_easy` extraction/prediction occurred in this
  slice. The transport-scope correction must be committed and pass CI before
  the paid run proceeds; there was no model, dataset, or decision-rule change.

## 2026-08-28 — Controlled v5 completed and rejected at the validation gate

- Execution revision `6c46b2f8ef719a7007eef72eebe13b34575aea93` was on
  `origin/main`; GitHub Actions
  [run 33173750012](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33173750012)
  succeeded, and the exact A10 checkout passed all 351 tests.
- The structural smoke at
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v5-magnitude-smoke-6c46b2f`
  ran two epochs over 128 training and 64 validation examples, selected and
  produced 64 of 1,889 eligible configured test pairs, and completed in
  `16.68084` seconds. Its checkpoint SHA-256 was
  `56d307755a1203a2e3d2798dee02d07dc7a9d8c85b478dd04f15ba6a84db309e`.
  It was a structural gate, not quality evidence.
- The single authorized full run used experiment
  `euroc-compact-vio-v5-magnitude`, config SHA-256
  `7f5e50785ed1907c26f5bbea6766a4fc13fd3df591c8930ef8b15ac9f7d71af0`,
  and split-manifest SHA-256
  `96d609aca0877b8b37f78498df01cf28f66ba9458a7b9849c1e8cad035b789a0`.
  It ran on one NVIDIA A10 with PyTorch 2.7.0 from
  `2026-08-28T13:05:56.866718Z` to `2026-08-28T13:13:04.921466Z`,
  recorded `428.054755853` seconds, completed all 30 epochs, and selected
  epoch 29.
- The frozen pre-`MH_02_easy` translation limit was
  `0.058765891780989885` m; v5 measured `0.05985308049522323` m and failed.
  The rotation limit was `0.0061899144990098035` rad; v5 measured
  `0.007484109588922632` rad and failed. A completed training process is not
  an accepted candidate: the predeclared outcome is **reject v5**.
- The configured `V2_03_difficult` development diagnostics retained complete
  1,889/1,889/1,889 eligible/selected/produced coverage, pair translation RMSE
  `0.05030155673706295` m, pair rotation RMSE
  `0.0059332330310097135` rad, raw no-alignment ATE RMSE
  `9.837654824915393` m, final drift `15.275065744781154` m, and predicted
  path `63.33375191024651` m versus `85.98933047434808` m reference. Zero
  motion had raw ATE `2.0557175228736244` m and drift
  `2.2264894226373304` m. These are seen-sequence diagnostics and cannot
  override the validation gate or support fresh confirmation.
- The retained checkpoint SHA-256 is
  `f26267f2cb55962ba236257acda0a7ac97ad87f93ae0ecdcb585026fa21f0741`.
  The original five-file trainer output at worker path
  `/home/ubuntu/compact-vio-runs/euroc-compact-vio-v5-magnitude-full-6c46b2f`
  and ignored local path
  `outputs/euroc-compact-vio-v5-magnitude-full-6c46b2f` independently passed
  manifest verification with immutable inner artifact-manifest SHA-256
  `9628a7b93da229700b07aa9bb43c07e8b31f68bd4e9ee764b4d7ad06ac63b2f9`.
  It was then preserved unchanged inside a governed wrapper that adds a
  schema-valid run manifest, resolved configuration, environment, execution,
  split, acquisition, and registry records. The wrapper run-manifest SHA-256 is
  `aeeb4f573d7dcf590f4f0aaf3fd49e922498ec5e2c465fd87e7c00aabf272af4`;
  its outer artifact-manifest SHA-256 is
  `548fd52ffd0d89e4a7d347c78a8e9c4ba799c84dd74f7e0a6f3a365f0ba3b91e`.
  Governed-bundle validation returned `ok: true` for 14 payload files totaling
  37,075,047 bytes, 13 declared artifacts, and five nested trainer payloads.
  The canonical governed-v2 wrapper verifies locally. The original trainer
  bundle independently verifies at its worker and local paths, but the
  canonical wrapper has not been copied to or verified on the worker. Small
  records are mirrored in Git; matching content remains copy-integrity
  evidence, not the unresolved independent-vault, backup, or restore gate.
- `MH_02_easy` was never extracted, opened, or used for inference; no retry,
  loss/threshold repair, fresh v5 evaluation, inference export, deployment, or
  model-promotion action occurred. V5 is rejected from those paths.
- The next safe plan is to retain this failed evidence and, before any new
  model work, independently select a rights-compatible full-pose evaluation
  unit and freeze its source roles, reference capabilities, candidates and
  controls, native classical backend, fairness/metric/coverage/resource rules,
  thresholds, tie handling, and stop rule. No exact unit or backend is selected
  by this entry.

## 2026-08-28 — M9 TUM VI `room4` full-pose candidate identity recorded

- The preceding failed-v5 evidence and governance hardening were committed as
  revision `26bd9faffd1ed30f2e8555f54a32988dd412480f` and pushed to
  `origin/main`; GitHub Actions run
  [33178215376](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33178215376)
  completed successfully.
- Closeout validation at that immutable revision passed all 367 tests in the
  PyTorch 2.13.0 project environment, the
  `jsonschema[format-nongpl]==4.26.0` harness for 10 schemas and 7 templates,
  repository policy for 151 files with zero violations, Ruff lint and format
  checks with 109 Python files already formatted, and the governed-bundle
  validator with `ok: true`.
- Candidate-only records now identify the official TUM VI `room4` EuRoC/DSO
  512x512 16-bit archive. A read-only `HEAD` observation bound the official
  `cdn3` request, its `302` redirect to `cdn2`, redirected `200` response,
  observed `1,356,206,080`-byte `Content-Length`, and
  `Tue, 17 Apr 2018 22:54:49 GMT` `Last-Modified`. A separate `GET` of the
  official 59-byte MD5 sidecar observed a `302` from `cdn3` at
  `2026-08-28T14:11:43Z`, then `200` from the exact allowed `cdn2` final URL at
  `2026-08-28T14:11:44Z`, `Last-Modified: Tue, 17 Apr 2018 22:54:52 GMT`, and
  exact body
  `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c  dataset-room4_512_16.tar` followed by
  one LF byte. Archive and sidecar redirects are restricted to their exact
  recorded final URLs and the `https://cdn2.vision.in.tum.de` origin. No
  archive bytes were downloaded and no SHA-256 was inferred.
- The official source describes hardware-synchronized stereo monochrome
  cameras and a 200 Hz IMU, processed timestamps/scaling/axes, poses in the IMU
  frame, and full-trajectory MoCap poses for room sequences. The data licence
  is CC BY 4.0 and accompanying code licence is BSD-2-Clause. DOI
  `10.1109/IROS.2018.8593419` is recorded only as the benchmark-publication DOI,
  not a dataset DOI.
- This is not unit selection or execution authority. Exact received-byte
  SHA-256/layout, calibration identities, ground-truth schema/conventions,
  16-bit preprocessing, adapter compatibility, source-group/leakage review,
  membership role, full-pose protocol, backend, candidates, metrics, and
  thresholds remain unresolved. The proposed lane is external full-pose
  generalization only; handheld TUM VI evidence cannot confirm the UAV domain.
  No selection, approval, extraction, inference, training, or evaluation
  occurred. The candidate JSON has identity state `published_identity_only`.
  Its strict exact-field loader and focused tests are implemented, but
  successful structural loading does not grant acquisition authority.

## 2026-08-28 — M9 archive trust boundary implemented; no transfer

- `src/compact_vio/data/archive.py` now loads the non-executable candidate and
  separately loads exact identity/destination-scoped acquisition records.
  Candidate records and direct construction cannot invoke the mutating
  downloader. The implementation validates every HTTPS redirect hop, supports
  bounded resume or safe full restart, holds a crash-safe POSIX advisory lock,
  stages into a single-link `.part`, and rehashes the held file descriptor
  before and after atomic no-overwrite publication.
- Read-only TAR inventory requires a pinned SHA-256 and uncompressed `r:`
  parsing. It rejects unsafe paths, normalization/topology collisions, links,
  devices, FIFOs, sparse/unknown members, and declared expansion beyond
  explicit limits before any write. The separate allowlisted extraction
  primitive uses same-filesystem staging, per-file SHA-256 receipts, a mandatory
  semantic validator, and atomic no-overwrite publication.
- Focused archive tests cover exact candidate/authorization parsing, redirect
  policy, resume semantics, concurrency and mutation races, hard-linked
  partials, checksums, hostile TAR members, limits, staging validation, and
  atomic publication. All 34 focused archive tests and all 401 repository tests
  passed. Ruff 0.16.4 lint/format passed for 112 Python files; the schema
  harness passed 10 schemas and 7 templates; repository policy checked 155
  files with zero violations; compilation and `git diff --check` passed.
- No network transfer, archive extraction, image decoding, checkpoint loading,
  inference, training, evaluation, unit selection, or dataset approval occurred.
  A complete one-use acquisition controller still needs candidate/tool hash
  binding, expiry, capacity reserve, time/cost bounds, retention, immutable
  claim/receipt behavior, and trusted review anchoring before the real archive
  may be transferred.

## 2026-08-29 — M9 one-use TUM VI operational transfer boundary prepared; no transfer

- `src/compact_vio/data/acquisition.py` adds a strict controller and
  `compact-vio-acquire-archive` CLI for one committed authorization. It accepts
  only the closed operational scope
  `operational_byte_transfer_and_read_only_inventory_only`; loading a candidate
  or authorization performs no network access.
- The separate authorization at
  `governance/datasets/acquisitions/tumvi-room4-512-16-transfer-2026-08-29.authorization.json`
  is based on the active workspace user's instruction to continue the immediate
  production execution plan. Its authority source explicitly records
  `identity_authentication: not_independently_authenticated`. That caveat and
  the user's instruction are operational provenance, not independent identity
  assurance, dataset-use approval, or third-party review.
- The authorization is limited to one execution during one exact 24-hour
  window, requires a clean worktree and exact tracked-`HEAD` bytes for itself,
  the historical candidate, and both controller modules, and binds the exact
  official source identity and ignored quarantine archive path. It requires at
  least 3,773,173,760 free bytes before the claim: the 1,356,206,080-byte
  archive, a retained 2,147,483,648-byte post-transfer reserve, at most
  268,435,456 bytes for inventory evidence, and at most 1,048,576 bytes for the
  receipt. Paid-compute cost is fixed to zero.
- The only permitted operations are writing the claim, download, received-size
  and published-MD5 verification, SHA-256 computation, read-only TAR-header
  inventory, and writing the inventory and receipt. Extraction, image decoding,
  dataset-sample loading,
  scientific selection or membership, checkpoint loading, training, inference,
  evaluation, publication approval, archive deletion, and overwrite are
  outside the authority.
- Before network access, the controller checks the validity window, tracked
  inputs, exact hashes, clean repository, absent archive/partial/evidence paths,
  Git-ignore boundaries, real non-symlink quarantine ancestry, and free-space
  gate, then creates an exclusive claim. A claimed failure consumes this
  authorization and cannot be retried by deleting the claim. On success, the
  controller writes the ignored canonical inventory and publishes the tracked
  receipt last, after rechecking expiry, reserve, repository revision, tracked
  inputs, archive/inventory identities, and bounded evidence sizes.
- Controller checkpoint `674082bb63447a3c5752345dc187474aae9342ee`
  passed GitHub Actions run `33275106056` on Python 3.10 and 3.12. The complete
  authorization-preparation tree then passed 56 focused acquisition/archive
  tests and all 423 repository tests; Ruff 0.16.4 lint/format passed for 115
  Python files; the schema harness passed 10 schemas and 7 templates;
  repository policy checked 159 files with zero violations; compilation and
  `git diff --check` passed.
- This entry records implementation and authorization preparation only. No
  TUM VI archive request, claim, partial, archive, inventory, receipt,
  extraction, decoding, checkpoint load, inference, training, evaluation,
  scientific unit selection, membership assignment, publication approval, or
  deletion occurred. The candidate JSON and its historical evidence remain
  unchanged.

## 2026-08-29 — M9 TUM VI transfer verified bytes; strict inventory failed closed

- GitHub Actions run `33275290330` passed for authorization revision
  `04097e6aa1906c0ea8bc5f53158f452b87d70f78` on Python 3.10 and 3.12 before
  execution. Preflight observed exact repository runtime modules, a clean
  worktree, all archive/partial/claim/inventory/receipt paths absent,
  96,691,183,616 free bytes against the 3,773,173,760-byte minimum, and an
  active authorization expiring at `2026-08-30T21:05:00Z`.
- The one-use claim began at `2026-08-29T21:09:25Z`; claim SHA-256 is
  `1c6b9d54e763a9ec2c899461e7701f8652f550bf9a19bb03367b1555edc3abc0`.
  The retained archive is exactly 1,356,206,080 bytes, matches publisher MD5
  `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c`, and has received SHA-256
  `2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`.
- Strict read-only inventory failed closed with `AcquisitionError` because TAR
  member `dataset-room4_512_16/dso/cam1/images` is a symbolic link. The archive
  remains in ignored quarantine; the partial is absent. No inventory or success
  receipt was published. The authorization is consumed, claim deletion is not
  authorized, and no retry will occur under it.
- The exact negative evidence is retained in
  `governance/datasets/acquisitions/tumvi-room4-512-16-transfer-2026-08-29.failure.json`.
  Its SHA-256 is
  `51979c3749e8a10187191ef43a355b72ebe456828d309703c22e0c6fccb0c75f`.
  This is received-byte and incompatibility evidence only: no extraction,
  decoding, sample loading, calibration/ground-truth validation, model or
  checkpoint access, training, inference, evaluation, scientific selection,
  membership assignment, publication, deletion, UAV-domain, deployment, or
  superiority claim occurred.
- Next safe work is code and policy only: design a bounded read-only structural
  audit that can record explicitly classified non-regular members without
  following or extracting them. It must pass adversarial tests and receive a
  separate exact authorization before it touches the retained archive.

## 2026-08-29 — M9 inert TAR structural-audit primitive implemented; not executed

- `compact_vio.data.archive.audit_tar_structure` verifies an exact pinned
  archive SHA-256 through a stable held descriptor, parses only uncompressed TAR
  headers, preserves canonical path/topology/member/size bounds, and records
  file, directory, symlink, hardlink, device, FIFO, sparse, and unknown
  non-regular kinds as inert metadata. Link targets are recorded but never
  followed; no member payload is extracted or decoded.
- The existing `inventory_tar` and allowlisted extractor remain strict and
  continue to reject every non-regular member. A structural-audit result with
  any non-regular member explicitly reports
  `strict_extraction_compatible: false`; it cannot authorize extraction or
  scientific use.
- Synthetic tests cover inert symlink/hardlink recording, strict-inventory
  rejection of the same archive, traversal/topology/hash/member-limit failures,
  no filesystem writes, and malformed public records. All 59 focused
  archive/acquisition tests and all 426 repository tests passed; Ruff 0.16.4,
  repository policy (160 files, zero violations), compilation, and
  `git diff --check` passed.
- This entry is implementation evidence only. The primitive has not inspected
  the retained TUM VI archive. A separate exact, tracked, one-use structural
  audit controller/authorization and success/failure evidence contract remain
  required before that read-only operation.

## 2026-08-29 — M9 one-use structural-audit controller implemented; no real audit

- `src/compact_vio/data/archive_audit.py` and the
  `compact-vio-audit-archive-structure` CLI implement a distinct controller for
  an already retained archive. Its exact authorization schema binds the
  historical candidate and failed-attempt evidence, received size/MD5/SHA-256,
  all three runtime modules, ignored archive/claim/audit paths, tracked receipt
  path, a one-hour ceiling, zero paid-service authority, 2 GiB retained reserve,
  bounded audit bytes, retention review, and one execution.
- The closed permitted set is claim writing, size/MD5/SHA verification, inert
  TAR-header audit, audit writing, and receipt writing. Download, archive
  modification, extraction, decoding, sample loading, checkpoint/model access,
  training, inference, evaluation, dataset selection/membership, publication,
  and deletion are exact prohibited operations. The controller re-verifies the
  unchanged archive and all tracked inputs before publishing its receipt last.
- Eight synthetic controller tests cover exact no-access loading, real
  header-audit execution with an inert symlink, zero extraction calls,
  archive-byte preservation, frozen schema/operation sets, runtime-source
  mismatch, wrong received SHA, post-audit archive mutation, output collision,
  and structured CLI failure. All 67 focused acquisition/archive/audit tests
  and all 434 repository tests passed; Ruff 0.16.4 passed for 117 Python files;
  repository policy checked 162 files with zero violations; the schema harness
  passed 10 schemas and 7 templates; compilation and `git diff --check` passed.
- This controller has not touched the retained TUM VI archive. Its exact code
  must first be committed/pushed and pass CI; only then may a separate active
  authorization bind those immutable hashes. Strict extraction compatibility
  remains false unless a complete observed audit proves otherwise, and even a
  completed audit would not authorize extraction or scientific use.

## 2026-08-29 — M9 structural-audit authorization frozen; not executed

- Controller commit `354967901deff93aa241a5ec06294224ca17ab4f`
  passed GitHub Actions run `33276318236` on Python 3.10 and 3.12. The separate
  authorization at
  `governance/datasets/acquisitions/tumvi-room4-512-16-structural-audit-2026-08-29.authorization.json`
  binds controller SHA-256 `18ba5f76…d535d6`, acquisition-helper SHA-256
  `33bb9b47…7047e1`, archive-layer SHA-256 `dd6823b3…a13884`, candidate SHA-256
  `0de94267…23740`, failed-transfer evidence SHA-256 `51979c37…c0c75f`, and
  retained archive SHA-256 `2c363340…9f2e68`.
- The authorization is active from `2026-08-29T21:33:00Z` through
  `2026-08-30T21:33:00Z`, permits one execution with a one-hour hard ceiling and
  zero paid-service authority, and requires at least 2,416,967,680 free bytes.
  Its canonical record SHA-256 is
  `cff468e9fd2702fb9c62176067e23db6a0d32b66502d5e92e37a42ea8324fbb8`.
- The real record and all frozen inputs are covered by the focused loader test.
  All 68 focused acquisition/archive/audit tests and all 435 repository tests
  passed before execution. This entry records authorization only: no new claim,
  audit, receipt, archive modification, extraction, decoding, sample/model
  access, training, inference, evaluation, selection, publication, or deletion
  occurred.

## 2026-08-29 — M9 retained TUM VI structural audit completed without extraction

- Authorization revision
  `9709a101b28f291de23826ac8c9abec6a6eb9846` passed GitHub Actions run
  [33276534039](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33276534039)
  on Python 3.10 and 3.12 before execution. The one-use audit began at
  `2026-08-29T21:38:08Z`, completed in `5.107158124999842` seconds, incurred
  zero controller-initiated paid-service cost, and published its tracked
  receipt last.
- The controller reverified the retained 1,356,206,080-byte archive at SHA-256
  `2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`
  before and after the audit. The ignored 744,267-byte audit has SHA-256
  `a75734de25567168eeb90a4b165361eb7df340ade2da5ed0382b6e9b228e6399`;
  the consumed ignored claim has SHA-256
  `c997ebdd4ff90aaee4044a17088c4de78ccf3dfa48c9089c300a01e70414a244`.
- The inert header audit classified 4,485 members: 4,472 regular files, 11
  directories, and two symbolic links. Declared expanded regular-file content
  totals 1,352,747,205 bytes. The links are
  `dataset-room4_512_16/dso/cam1/images` to `../../mav0/cam1/data` and
  `dataset-room4_512_16/dso/cam0/images` to `../../mav0/cam0/data`. Neither was
  followed. The recorded `mav0` tree contains 2,231 `cam0` entries, 2,231
  `cam1` entries, two `imu0` entries, and two `mocap0` entries; the separate
  `dso` tree contains 17 entries.
- Because the archive contains two non-regular members, the audit records
  `strict_extraction_compatible: false`; the existing strict inventory and
  extraction policy remains unchanged. The tracked 3,273-byte receipt at
  `governance/datasets/acquisitions/tumvi-room4-512-16-structural-audit-2026-08-29.receipt.json`
  has SHA-256
  `1e3216a7bf789ef3a6d5425fa64f5a7cfa0a712c905460f5b444b65f5e323a92`.
  The focused archive/acquisition/audit suite passed all 69 tests after the
  receipt fixture was added.
- The [reviewed report](../reports/tumvi-room4-512-16-structural-audit-2026-08-29.md)
  records the evidence and interpretation. The operation performed no download,
  archive modification, extraction, image decoding, sample loading,
  checkpoint/model access, training, inference, evaluation, dataset selection,
  membership assignment, publication, or deletion. Its scientific authority is
  `none`.
- Next is a new review and one-use authorization for an exact regular-file
  allowlist under the required `mav0` tree only. It must exclude `dso` and all
  links, and it remains operational preparation rather than dataset selection.
  Scientific selection, source membership, adapter/calibration/ground-truth
  acceptance, and the full-pose protocol remain separate gates before model or
  evaluation work.

## 2026-08-29 — M9 exact TUM VI compatibility-slice implementation locally verified; not authorized

- Added a distinct audit-bound regular-file extraction primitive and the
  `compact-vio-extract-regular-slice` controller/CLI. The original strict TAR
  inventory and extractor remain unchanged and continue to reject the official
  symlinks. The new path fresh-compares all 4,485 live TAR headers to the frozen
  structural audit, follows no link, copies only exact authorized regular
  members, verifies an exact single-link output tree, publishes without
  replacement, and writes its tracked receipt last.
- The checked allowlist
  `configs/data/tumvi_room4_512_16_compatibility_slice_v1.json` contains four
  complete `mav0` CSV members and the lexicographically earliest two common
  regular PNG basenames from each camera: 8 files totaling 5,043,300 bytes.
  This deterministic operational sample does not establish CSV membership,
  camera synchronization, payload semantics, calibration compatibility,
  scientific dataset selection, or protocol membership.
- Adversarial coverage includes complete-audit equality, inert unselected link
  handling, no link resolution, DSO/special-member rejection, staging and
  published-root identity checks, exact file/link-count verification,
  one-use claim and output collisions, source/archive/receipt truth gates,
  bounded capacity/deadline behavior, and exact post-publication Git state.
  The final local gate passed 57 focused archive/controller tests and all 456
  repository tests; Ruff 0.16.4 lint and format checked 120 files, repository
  policy checked 168 files with zero violations, the schema harness passed 10
  schemas and 7 templates, and compilation, CLI help, and `git diff --check`
  passed.
- No real compatibility slice, claim, destination, receipt, payload parsing or
  decoding, model/checkpoint access, training, inference, evaluation, dataset
  selection, membership assignment, scientific publication, or source
  deletion occurred. Commit/push and green CI are required before a separate
  exact one-use authorization can be frozen.

## 2026-08-29 — M9 compatibility-slice controller CI green; one-use authorization frozen, not executed

- Implementation commit `9ca97e04848fe08d14841470a7a7bf39b5edd725`
  passed GitHub Actions run
  [33279450649](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33279450649)
  on Python 3.10 and 3.12. The earlier run `33279337811` exposed a Python
  3.10-only mock-isolation defect in one no-archive-access test; the production
  controller passed, the test double was narrowed, and the replacement matrix
  passed completely.
- The authorization at
  `governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.authorization.json`
  has canonical SHA-256
  `f39ba7598eac1a0301ced5b13d835231c79757b26e096219145737a139f79e81`.
  It binds the exact archive, candidate, failed transfer evidence, structural
  audit/claim/authorization/receipt, eight-file allowlist, and committed hashes
  of the controller, acquisition helper, and archive primitive. It permits one
  execution from `2026-08-29T22:49:00Z` through
  `2026-08-30T22:49:00Z`, with a one-hour total controller bound, zero
  paid-service authority, and an exact 2,154,624,100-byte free-space floor.
- The authorization permits only evidence verification, complete live-header
  comparison, exact regular-member copying, hashing, staging validation,
  no-replace publication, receipt publication, and narrowly scoped rollback of
  this run's exact new receipt if a final truth gate fails. It prohibits
  network download, link following, DSO/unlisted copying, TAR extraction APIs,
  payload parsing/decoding, sample/model/checkpoint access, training, inference,
  evaluation, dataset selection/membership, scientific publication, and source
  deletion. Scientific authority remains `none`.
- The authorization fixture raised the focused controller count to 16 and the
  complete repository count to 457; Ruff checked 120 files, repository policy
  checked 169 files with zero violations, the schema harness passed 10 schemas
  and 7 templates, and compilation, formatting, and diff checks passed. This
  entry records the frozen authorization only: no compatibility claim,
  destination, receipt, payload access, or scientific operation has occurred.

## Recording rule for the next entry

Append—do not rewrite prior observations—with:

- The completed milestone or evidence slice.
- Immutable Git commit and remote CI run.
- Exact validation commands and result counts.
- New evidence paths/manifests.
- Remaining blockers and any protocol deviation.

Do not record percentages of project completion or silently convert a proposed
recommendation into a decision.

## 2026-08-29 — M9 exact TUM VI regular-file compatibility slice completed operationally

- Authorization/execution revision
  `cfe863890ad040684ac837c1b5d7f346bc0159cc` passed GitHub Actions run
  [33279713875](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33279713875)
  before execution. The controller implementation had already passed at commit
  `9ca97e04848fe08d14841470a7a7bf39b5edd725` in run `33279450649`; the
  superseded run `33279337811` failed only the Python 3.10 isolation of one test
  double, not the production controller.
- The one-use authorization executed once. It created ignored claim SHA-256
  `8e4e8a8ad8c58c96e10535600caacaed51776c173c3b6babec557c3f973c4271`,
  compared all 4,485 live TAR headers with the frozen audit, copied only the
  eight exact allowlisted regular members, and atomically published the ignored
  5,043,300-byte output tree. It followed no link and copied no `dso`, special,
  or unlisted member.
- The controller started and prepared its claim at `2026-08-29T22:55:17Z`,
  prepared the receipt at `2026-08-29T22:55:25Z`, and recorded elapsed time
  `8.26419195800554` seconds and controller-initiated paid-service cost USD 0.
  Initial free space was 94,954,934,272 bytes; the pre-receipt observation was
  94,949,638,144 bytes against the exact 2,154,624,100-byte authorized minimum
  and 2,147,483,648-byte retained reserve.
- The new 7,106-byte receipt at
  `governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json`
  has SHA-256
  `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`.
  It binds the unchanged 1,356,206,080-byte archive at MD5
  `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c` and SHA-256
  `2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`,
  the consumed claim, complete source-evidence chain, allowlist, tool hashes,
  capacity observations, and every selected file size/SHA-256.
- A separate read-only raw-byte walk at `2026-08-29T22:57:26Z` found exactly
  eight directories below the destination, eight regular files, 5,043,300
  bytes, no symbolic link or special file, no `dso` entry, and link count one
  for every file; all paths, sizes, and SHA-256 values matched the receipt. A
  read-only archive check completed by `2026-08-29T22:58:36Z` and reconfirmed
  its size, MD5, and SHA-256. Independent post-run review found no P0, P1, or
  P2 issue.
- The [reviewed execution report](../reports/tumvi-room4-512-16-compatibility-slice-2026-08-29.md)
  records the exact files, hashes, timing, capacity, CI, method, and limitations.
  No CSV was parsed and no PNG was decoded. No format, timestamp,
  synchronization, calibration, ground-truth, preprocessing, adapter,
  scientific-selection, membership, model, training, inference, evaluation,
  publication, or UAV-domain claim was established. Scientific authority is
  `none`, and the ignored claim and tree have no independent recovery copy
  recorded here.
- Protocol deviation: none. This completed only the authorized operational
  extraction boundary. Any payload-semantic compatibility check, unit
  selection, leakage/membership decision, and full-pose protocol remains a
  separate future gate before model or evaluation access.

## 2026-08-29 — M9 TUM VI bounded format inspection completed; current EuRoC adapter rejected

- The bounded format inspector was implemented at commit
  `b83eebf3cc24cfada57d2d76da4a19672ef8267a`; GitHub Actions run
  [33282946955](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33282946955)
  passed before authorization. The one-use authorization and execution revision
  `7dfe85b8c7a3de04a1c789a79a139fa90ad5d5a4` passed GitHub Actions run
  [33283206142](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33283206142)
  before the permanent claim was created.
- The exact 24-hour, single-execution authorization had SHA-256
  `be49077af024e301dcada292384d19309adb8d5d08ea3ae4bb62be7c86a25d9f`.
  It bound checked-spec SHA-256
  `e8dd0bc98c7be85fed6d92d319bafec75c9f658584ea83d17ac93c6f47bdf1a7`,
  compatibility-slice receipt SHA-256
  `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`,
  exact tracked source/tool bytes, eight files, 5,043,300 source bytes, a
  600-second deadline, capacity limits, and zero paid-service authority.
- The authorization executed once. The controller started at
  `2026-08-30T00:24:14Z`, prepared its receipt at `2026-08-30T00:24:15Z`,
  and recorded 0.2793292919814121 seconds at receipt preparation and USD 0
  controller-initiated paid-service cost. Consumed ignored claim SHA-256 is
  `cfec13978853239e5517d0c06d298191adebbe5d4d954d9604b51ef2ddb379ff`.
  Initial free space was 94,684,848,128 bytes and the pre-receipt observation
  was 94,684,831,744 bytes, above the 2,149,580,800-byte authorized minimum and
  2,147,483,648-byte retained reserve.
- The immutable 16,879-byte receipt at
  `governance/datasets/acquisitions/tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json`
  has SHA-256
  `30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846`.
  It records `execution_outcome: completed` and
  `format_comparison_outcome: does_not_conform`; adapter, calibration, and
  ground-truth readiness are false and scientific authority is `none`.
- Seven of ten frozen operational gates passed: camera and IMU headers, exact
  camera-index equality, exact-once selected-name membership, filename-stem
  timestamp equality, common selected names, and equality of the four PNG IHDR
  tuples. Three gates failed: the observed eight-column mocap header matches
  neither current 17-column EuRoC full-state target; the first selected camera
  timestamp precedes the first observed IMU timestamp by 3,273,404 ns; and it
  precedes the first observed mocap timestamp by 27,431,374 ns. This count is
  an operational predicate summary, not a scientific or dataset-quality score.
- The method streamed four bounded CSV structures without retaining sensor rows
  and interpreted exactly 33 bytes from each of four PNGs. It observed headers,
  arities, row counts, timestamp boundaries and gaps, BOM flags, bounded issue
  counts, selected-name membership, opaque hashes, and four 512x512, 16-bit
  PNG IHDR records. It did not establish units, frames, synchronization cause,
  calibration, ground-truth semantics, whole-file PNG validity or decodability,
  complete indexed-image existence, dataset quality, selection, membership, or
  any model result.
- The current EuRoC adapter must not be reused and no model/checkpoint work is
  authorized. The next falsifiable gate is a separately reviewed
  TUM-VI-specific adapter contract with exact accepted grammars, bounded parser
  behavior, synthetic negative fixtures, and an explicit interval policy. Only
  if that contract proves a calibration dependency necessary may a separate
  one-use authorization inspect exact minimal calibration metadata. Unit
  selection, leakage/membership review, and full-pose protocol freeze remain
  later independent gates.
- The [production result report](../reports/tumvi-room4-512-16-format-inspection-2026-08-29.md)
  and its evidence graph record the receipt-backed methodology, exact observed
  facts, limitations, decision, and next gates. Protocol deviation: none.
- Documentation validation passed: `git diff --check`; repository policy over
  180 files with zero violations; the schema harness with 10 schemas and 7
  templates; YAML parsing of the dataset registry; XML parsing and raster
  rendering of the SVG evidence graph; unchanged receipt SHA-256; and 74 local
  Markdown targets across the edited documents with zero broken links.

## 2026-08-29 — M9 TUM-VI adapter-contract Gate 1 implemented and locally verified

- A strict non-executable contract is now frozen at
  `configs/data/tumvi_room4_512_16_adapter_contract_v1.json`, SHA-256
  `4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5`.
  It binds the candidate, compatibility-slice receipt, format-inspection
  specification/receipt/report, and rejected EuRoC adapter by exact tracked
  path and SHA-256.
- The strict loader at `src/compact_vio/data/tumvi_adapter_contract.py`,
  SHA-256
  `26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20`,
  exposes only `TumviAdapterContract`, `TumviAdapterContractError`, and
  `load_tumvi_adapter_contract`. It seals construction to the canonical
  contract at exact tracked `HEAD`, rechecks worktree bytes and evidence
  hashes, and rejects duplicate/missing/extra/wrong-type fields, noncanonical
  evidence path values, alternate contract locations, links, changed evidence,
  and `HEAD` movement.
- The contract freezes exact LF-only, unquoted raw CSV grammars; per-column
  lexeme-to-source-labelled-output mappings; minimum row counts; timestamp,
  filename, stereo-index, and bounded-resource policies; and an eight-column
  source-labelled pose-row shape distinct from EuRoC full state. Numeric values
  remain original ASCII lexemes. Pose units, frames, transform direction, and
  reference role remain unverified or unassigned.
- The interval is only a prospective closed intersection of source-labelled
  integer timestamp-token ranges. It makes no clock-equivalence claim. Clock
  offset, gap limits, segment rule, pose association/interpolation, decoder,
  dtype/range/channel mapping, normalization, and preprocessing remain null or
  blocked. Timestamp shift, clock correction, extrapolation, resampling, and
  monocular fallback are prohibited.
- The loader reads only the contract and six exact tracked evidence files. It
  opened no ignored dataset payload, calibration, PNG, learning, or model path.
  No real-payload parser, adapter, segment, pose association, image decode,
  preprocessing, selection, membership, model access, training, inference, or
  evaluation was implemented or executed. Every readiness flag is false and
  scientific authority is `none`.
- The focused test file SHA-256 is
  `612ed53ff3ed1dbe2d7a51e9c69d99b83a60ea19eeeb922ed2da2a1f813a7a3c`.
  Focused tests passed 22/22 and the full repository suite passed 517/517.
  Ruff lint/format, compilation, schema, repository-policy, JSON, and diff
  checks passed. Independent adversarial review replayed the prior attack cases
  and reported no P0 or P1 finding.
- The [Gate 1 technical report](../reports/tumvi-room4-512-16-adapter-contract-v1-2026-08-29.md)
  records the exact contract boundary, validation evidence, limitations, and
  next gate. The immutable implementation revision and GitHub Actions result
  are pending until this source/documentation slice is committed and pushed;
  they must be recorded in a later append-only entry.
- The immediate next gate is pure synthetic parsing with positive and
  adversarial negative fixtures. It must preserve source lexemes and source
  labels, fail closed at the frozen grammar/resource boundary, and keep real
  payload, calibration, images, segment construction, dataset selection,
  membership, and model work closed.

## 2026-08-29 — M9 TUM-VI adapter-contract Gate 1 pushed and CI green

- The exact Gate 1 implementation/documentation slice was committed as
  `bc71dd5ebfdc636994a384a0a5dd2fd22184720d` and pushed to `origin/main`.
  This closes the immutable-revision field that remained pending in the prior
  append-only local-validation entry; that entry remains unchanged as the
  pre-commit evidence state.
- GitHub Actions
  [run 33286985057](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33286985057)
  was created and started at `2026-08-30T02:01:16Z` and reached terminal
  `success` at `2026-08-30T02:01:47Z`. Python 3.12 job `99191772715` passed
  from `02:01:20Z` through `02:01:44Z`; Python 3.10 job `99191772864` passed
  from `02:01:20Z` through `02:01:46Z`.
- The committed source identities remain contract SHA-256
  `4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5`,
  strict-loader SHA-256
  `26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20`,
  and focused-test SHA-256
  `612ed53ff3ed1dbe2d7a51e9c69d99b83a60ea19eeeb922ed2da2a1f813a7a3c`.
  The focused suite passed 22/22 and the full suite passed 517/517 before the
  push; the successful two-version CI run independently closed the remote gate.
- This closeout changes no scientific or operational boundary. Gate 1 remains
  a strict contract loader, not a TUM-VI payload parser or adapter. It grants no
  real payload, calibration, image, segment, dataset-membership, model,
  training, inference, evaluation, or publication authority. Every readiness
  flag remains false and scientific authority remains `none`.
- The immediate next gate remains pure synthetic parsing with positive and
  adversarial negative fixtures. Real payloads, calibration, decoding,
  preprocessing, segment construction, dataset selection/membership, and all
  model work remain closed.

## 2026-08-29 — M9 TUM-VI synthetic parser Gate 2 pushed and CI green

- Gate 2 was implemented at commit
  `3379060f83801230e5fe8c52e7bd0c3c288e5253` and pushed to `origin/main`.
  Parser SHA-256 is
  `4d5186a9559a4c111edda6df3d49a1484952ab6028a9269904ce4577efdc99e1`;
  focused-test SHA-256 is
  `9ba2ca8157af4a9e83a44d4e57e6737d272de845b6932bf6e84db0d8371cb69c`.
- GitHub Actions
  [run 33289072534](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33289072534)
  was created and started at `2026-08-30T02:54:50Z` and reached terminal
  `success` at `2026-08-30T02:55:20Z`. Python 3.10 job `99197374254` passed
  from `02:54:54Z` through `02:55:14Z`; Python 3.12 job `99197374357` passed
  from `02:54:54Z` through `02:55:19Z`.
- Focused tests passed 20/20. The full suite reported `OK` across 537 tests with
  54 declared optional-capability skips. Ruff lint passed, and Ruff format
  checked 131 supported source/document files; compilation, the
  10-schema/7-template harness, repository policy over 186 intended files with
  zero violations, and `git diff --check` passed. Two
  independent adversarial reviews reported no P0 or P1 finding.
- The new parsers accept exact open `io.BytesIO` fixtures at byte zero for
  camera indexes, IMU rows, eight-column source-labelled pose rows, and
  byte-identical stereo indexes. They preserve numeric source lexemes, bind the
  exact Gate 1 contract/accounting policy, enforce exact headers/order/identity
  and resource limits, consume successful streams through EOF without closing
  them, and seal immutable row/source/batch outputs.
- Gate 2 opened no real data. The module has no filesystem loader or CLI, is not
  exported from `compact_vio.data`, and imports no calibration, image, EuRoC,
  learning/model, or segment module. The exact known inspected camera, IMU, and
  mocap CSV SHA-256 identities are denied before any read.
- The parser assigns the fixed
  `synthetic-fixture-only-origin-not-authenticated/v1` source-scope label to
  caller-supplied bytes; it is not authenticated provenance. Claimed
  size/SHA-256 is recomputed over supplied bytes, but otherwise unknown bytes'
  external origin cannot be proven. Successful parsing therefore grants no
  real-source, adapter, dataset, or scientific authority.
- The [Gate 2 technical report](../reports/tumvi-room4-512-16-synthetic-parser-gate2-2026-08-29.md)
  and [status graph](../reports/assets/tumvi-gate2-parser-status.svg) record two
  verified engineering gates—Gate 1 contract and Gate 2 synthetic parser—and
  five blocked gates: real-payload parser, calibration metadata, image decode,
  segment construction, and model access. Graph SHA-256 is
  `7de56ac3e38ab9e70be85b4e746640bbafbcc75c77242f9d25c2ca6648568e48`.
  The count is not a scientific score or dataset-quality claim.
- Every operational readiness flag remains false and scientific authority
  remains `none`. Gate 3 is a separate reviewed design decision between
  calibration-metadata evidence and a one-use real-payload adapter probe. This
  closeout does not rank, select, or authorize either alternative; the decision
  may be that neither is justified.
- Closeout documentation validation passed: `git diff --check`; all 15
  foundation/link tests; repository policy over 188 intended files with zero
  violations; the 10-schema/7-template harness; registry YAML parsing; SVG XML
  parsing; and SVG raster rendering at 1200x660. Protocol deviation: none.
