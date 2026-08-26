# Governance records

Status: Optional structured record support; not the research critical path
Last reviewed: 2026-08-26

This directory holds optional small, credential-free governance records. The JSON
Schemas define record shape only and do not verify that a statement is true,
approve a candidate, accept an ADR, or pass a milestone. A worker record with
`record_status: owner_approved` is an unauthenticated structural authority input,
not a complete execution gate. Its exact action-to-location-access scope must be
active, externally authenticated, unused in the consumption ledger, and paired
with every required pre-action evidence check. It cannot authorize a worker
lifecycle change or deletion of a primary, backup, or other retained copy;
version 1 also refuses standalone execution of every non-static scope. The lean
experiment lifecycle uses an explicitly approved bounded run plan rather than
requiring this optional schema.

## Authority boundary

- Only an `Accepted` ADR records a project decision.
- The implementation plan owns milestone order and exit gates.
- The progress ledger records dated evidence but cannot accept an ADR or change
  a milestone.
- A record with `record_status: ready_for_owner_review` is still only an input
  for explicit owner review.
- Only a worker-authorization record with `record_status: owner_approved`,
  `authorizes_work: true`, a named approver, approval time and statement, and a
  non-template approval-evidence reference can contribute to work authority. At
  use time it must also pass the structural checks below plus external approver
  authentication, non-reuse/consumption, and required pre-action evidence. It
  does not accept ADR-0005 or select a project policy.
- Files ending in `.template.json`, and the
  `artifact-storage-evidence.draft.json` example, are blank drafting aids. They
  are never evidence and must never be linked as ADR or milestone exit evidence.
- A schema-valid record can still contain an incorrect assertion. Human review
  and the evidence named by the governing ADR remain required.

## Record lifecycle

1. Copy the relevant template to a new, non-template filename.
2. Keep `record_status` as `draft` while required facts or evidence are absent.
3. Record only observed or explicitly owner-supplied values. Do not replace
   unresolved fields with implementation defaults.
4. Remove credentials, signed URLs, tokens, private keys, and secret query
   parameters before committing a record.
5. Change the record to `ready_for_owner_review` only when its schema conditions
   are satisfied and every referenced record is non-template evidence.
6. Obtain an explicit project decision in its ADR. For bounded paid-worker
   action authority, preserve the owner approval in an `owner_approved` worker
   record; an informal chat acknowledgement is not a durable approval record.
7. Preserve reviewed records. Correct a material error with a superseding record
   and trace the relationship instead of silently rewriting history.

## Real-record discovery

Templates remain in `governance/records/templates/`. A real governed record has
exactly this path:

```text
governance/records/<record_type>/<record_identifier>.json
```

The permitted directory, root `record_type`, identifier, and schema pairs are:

| Directory | Required `record_type` | Identifier field | Schema |
|---|---|---|---|
| `project_release_scope/` | `project_release_scope` | `record_id` | `project-release-scope.schema.json` |
| `rights_matrix/` | `rights_matrix` | `record_id` | `rights-matrix.schema.json` |
| `artifact_storage_plan/` | `artifact_storage_plan` | `record_id` | `artifact-storage-plan.schema.json` |
| `worker_authorization/` | `worker_authorization` | `record_id` | `worker-authorization.schema.json` |
| `artifact_storage_evidence/` | `artifact_storage_evidence` | `evidence_id` | `artifact-storage-evidence.schema.json` |

Discovery is limited to `*.json` files directly inside those five directories.
The filename without `.json` must equal the identifier field listed above. Files below
`templates/`, files ending in `.template.json` or `.draft.json`, and JSON files
elsewhere are not real governance records and cannot satisfy a record reference.
`record_type` selects a schema; it does not confer authority.

## Semantic validation

JSON Schema validation is necessary but cannot compare values across fields or
evaluate a record at the current time. Real records therefore also require the
repository semantic validator.

Run discovery, schema validation, and built-in cross-record adversarial checks
from the repository root with:

```sh
python scripts/validate_schemas.py
```

Before project-scope owner review, validate the exact two canonical records as
a pair (replace the example identifiers with the actual record IDs):

```sh
python scripts/validate_schemas.py \
  --project-release-scope governance/records/project_release_scope/scope-id.json \
  --rights-matrix governance/records/rights_matrix/rights-id.json
```

The pair succeeds only when both records are review-ready and canonical and the
scope's reference, raw SHA-256, record ID, cutoff, and release lanes agree with
the supplied rights-matrix bytes. A passing result validates record coherence;
it does not authenticate a reviewer, determine rights, or accept ADR-0001.

For an owner-approved worker record it must establish:

- `prepared_at <= approved_at < review_at <= expires_at`;
- the duration measured from approval fits at or before `review_at`;
- for active use, `approved_at <= at_time < review_at` and the full expected
  duration measured from `at_time` still fits at or before `review_at`;
- the requested action is one of the closed `requested_action_ids`, has exactly
  one matching `action_scopes` entry, and the current worker, Git commit, and
  complete action-specific `(location_ref, read|write|delete)` set match the
  record; and
- when `disposable_source_copy_delete` is requested, the named copy is
  purpose-created for the restore test, classified `disposable`, pinned by its
  artifact-manifest SHA-256, and its location is among `named_test_locations`.

The typed M2 write actions separately cover creation of the disposable source,
the primary test copy, and the independent backup test copy. Actions and
location accesses are not independent lists: semantic validation requires one
ordered scope per action, rejects duplicate action scopes, distinguishes read,
write, and delete, and requires `named_test_locations` to equal the location
union of those scopes. Standalone active-use validation accepts only one action
at a time and requires its complete exact location-access set. Free text cannot
expand action scope. Copy creation/writes permit only `write`; content audit and
load/open permit only `read`; restore requires exactly one `read` source and one
distinct `write` destination; and `delete` is forbidden for every action except
the exact disposable source-copy deletion.
`worker_lifecycle_change`, `primary_vault_copy_delete`,
`independent_backup_copy_delete`, and `other_retained_copy_delete` are hard
false in every worker authorization. The exact disposable-copy deletion is the
sole narrowly representable deletion scope. Version 1 refuses every non-static
action in standalone active-use mode because the command does not resolve the
reviewed storage roles or accept the required pre-action evidence and
single-use consumption entry. The executable restore drill remains blocked
until that dedicated interface exists; a structurally valid owner record alone
is insufficient.

An expired or reviewed worker record remains a historical authority input. It
supports a conclusion about past authorization only when combined with
authenticated approval, single-use consumption, required pre-action evidence,
and execution evidence; it cannot authorize another action. Later paid work
always requires a fresh record and the full external checks.

Every worker authorization declares `max_executions: 1`. The current validator
checks record structure, time, worker, revision, action, and location scope, but
it is stateless: it cannot prove that the record is unused or enforce cumulative
duration or spend across repeated invocations. Before real paid work, preserve
an append-only execution/consumption entry and confirm no prior entry uses that
authorization. A structural validation result is not proof of owner identity,
record truth, non-reuse, action execution, or billing.

Version 1 live validation permits only `static_checks`; it is supporting audit
tooling, not the paid-run execution gate. A current structural static
check therefore has no location access (replace the example record, worker,
revision, and time with reviewed values):

```sh
python scripts/validate_schemas.py \
  --worker-authorization governance/records/worker_authorization/auth-id.json \
  --at-time 2026-08-26T12:30:00Z \
  --worker-ref reviewed-worker-id \
  --git-commit 0000000000000000000000000000000000000000 \
  --action-id static_checks
```

Even `active_scope_record_valid=true` retains the explicit false flags for
approver authentication, record truth, use-ledger consumption, execution, and
the artifact restore gate.

Paid research work follows the short bounded run-plan procedure in the
experiment lifecycle. M2 additionally gates long or irreplaceable paid runs.
This optional validator deliberately does not claim to authorize or execute
that work.

For a review-ready storage plan, semantic validation must establish that the
primary and backup candidate IDs and location references differ; the
independence review follows both candidate observations; total required
bytes equal worst-case retained bytes plus reserve; both candidates have at
least that capacity; all validity and retention/cost review times are after
`prepared_at`; expected teardown-transfer seconds are at least total required
bytes divided by measured throughput; and that duration fits before the cost
review time. These checks do not prove failure-domain independence or accept
ADR-0005.

## M2 records

- [Project/release scope template](templates/project-release-scope.template.json)
  prepares the current-scope inputs for ADR-0001.
- [Rights-matrix template](templates/rights-matrix.template.json) inventories
  assets selected or proposed within a declared scope cutoff. Future assets are
  reviewed when selected; they are not guessed during M2.
- [Artifact-storage plan template](templates/artifact-storage-plan.template.json)
  prepares a phase-scoped capacity, retention, recovery, and spend proposal for
  ADR-0005.
- [Worker-authorization template](templates/worker-authorization.template.json)
  prepares a bounded owner-review request. The unchanged template authorizes
  nothing. A completed, durable, structurally active `owner_approved` record can
  contribute to authority for its exact typed scope only when externally
  authenticated, unused/consumed once, and paired with required pre-action
  evidence.

Release-lane IDs and rights-asset IDs must be unique within their records.
JSON Schema `uniqueItems` rejects identical duplicate objects; repository
validation must also reject repeated IDs whose other fields differ.
Before owner review, the project/release scope must link the exact rights-matrix
record by canonical path, record ID, and raw SHA-256. Cross-record validation
must require matching scope cutoffs and reject any asset whose intended lane is
absent from the linked project scope. Independent schema validity is not enough
to establish that the two inputs describe the same proposed release scope.

Post-export copy, checksum, failure-domain, deletion-of-test-copy, restore, and
load/open observations belong in the separately governed
[artifact-storage evidence schema](../../experiments/schemas/artifact-storage-evidence.schema.json)
and its draft example. The immutable run and artifact manifests remain inside
the frozen bundle and are not rewritten with later storage observations. A
paid-worker drill sidecar must identify and hash the historical worker
authorization that covered its actions. A `non_paid_environment` drill records
that execution context without fabricating a worker authorization.
