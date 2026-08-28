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

## Recording rule for the next entry

Append—do not rewrite prior observations—with:

- The completed milestone or evidence slice.
- Immutable Git commit and remote CI run.
- Exact validation commands and result counts.
- New evidence paths/manifests.
- Remaining blockers and any protocol deviation.

Do not record percentages of project completion or silently convert a proposed
recommendation into a decision.
