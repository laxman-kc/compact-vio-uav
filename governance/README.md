# Governance

`governance/` records the policies, rights, authority, and receipts that limit
what project operations and results may claim. It is not the user guide, model
card, configuration registry, or experiment-result directory.

## Directory map

| Area | Contents |
|---|---|
| [`artifacts/`](artifacts/policy.md) | Retention, backup, restore, and release policy |
| [`datasets/`](datasets/policy.md) | Dataset admissibility, rights, registry, and source evidence |
| [`datasets/acquisitions/`](datasets/acquisitions/README.md) | Bounded authorizations, claims, receipts, and failures for exact operations |
| [`records/`](records/README.md) | Governance record lifecycle and draft templates |
| [`schemas/`](schemas/project-release-scope.schema.json) | Strict structures for release, rights, storage, and worker authority records |

The canonical dataset registry is
[`datasets/registry.yaml`](datasets/registry.yaml). A registry entry or source
brief records identity and admissibility facts; it does not prove that a model
used the data correctly or passed an evaluation.

## Relationship to neighboring directories

| Directory | Owns |
|---|---|
| [`configs/`](../configs/README.md) | Machine-readable inputs that change a run |
| `governance/` | Permission, rights, policy, authority, and operation receipts |
| [`reports/`](../reports/README.md) | Human-readable interpretation of measured outcomes |
| [`experiments/`](../experiments/README.md) | Run and artifact evidence schemas |

For example, a TUM-VI data configuration can define a bounded candidate or
comparison. A governance authorization can permit one exact archive operation.
A receipt can prove that operation completed. A report can explain the observed
result. None substitutes for the others.

## Authority rules

- Draft templates are not approvals.
- An accepted ADR decides project direction; a plan or progress entry cannot
  accept an ADR.
- A completed download or extraction does not assign scientific dataset
  membership.
- Schema validity does not authenticate a record or approve its contents.
- Earlier worker, storage, or data authority does not automatically carry into
  a new operation.
- Dataset terms, dependency terms, source-code licensing, and model-artifact
  release rights are separate reviews.

The project remains publicly readable without a selected source license.
[ADR-0001](../docs/adr/0001-project-and-release-scope.md) therefore prohibits
presenting the repository as OSI open source or assuming redistribution rights.

## Contributor guidance

Do not edit an authorization, claim, receipt, or failure record to describe a
later event. Add a new exact record under the applicable schema and preserve the
historical identity. Never add credentials, signed private URLs, private
recordings, or unrestricted machine-local paths.

Start with:

- [Repository layout](../docs/repository-layout.md)
- [Requirements index](../docs/requirements.md)
- [Architecture decisions](../docs/adr/README.md)
- [Research protocol](../docs/protocols/research-protocol.md)
- [Security policy](../SECURITY.md)
