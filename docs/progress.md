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

## Recording rule for the next entry

Append—do not rewrite prior observations—with:

- The completed milestone or evidence slice.
- Immutable Git commit and remote CI run.
- Exact validation commands and result counts.
- New evidence paths/manifests.
- Remaining blockers and any protocol deviation.

Do not record percentages of project completion or silently convert a proposed
recommendation into a decision.
