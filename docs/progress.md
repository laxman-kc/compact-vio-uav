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

## Recording rule for the next entry

Append—do not rewrite prior observations—with:

- The completed milestone or evidence slice.
- Immutable Git commit and remote CI run.
- Exact validation commands and result counts.
- New evidence paths/manifests.
- Remaining blockers and any protocol deviation.

Do not record percentages of project completion or silently convert a proposed
recommendation into a decision.
