# ADR-0001: Project and release scope

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

The repository is public, but public visibility does not decide whether the work is research-only, commercially usable, or intended for redistributed model/runtime releases. No project license has been selected. GitHub's Terms grant platform-specific viewing and forking rights, but they do not create a general reuse or redistribution license. Dataset and dependency rights differ and may require separate artifact lanes.

## Decision required

Choose and document:

1. Research-only, commercially eligible, or parallel separated lanes.
2. Project source-code license.
3. Whether model weights, calibration, containers, and reports are released.
4. The dependency-license policy, including treatment of reciprocal licenses.
5. Attribution, NOTICE, data-statement, and model-card requirements.

## Evidence required before acceptance

- A non-template project/release scope record conforming to the
  [project/release scope schema](../../governance/schemas/project-release-scope.schema.json),
  with intended purpose, users, distribution surfaces, release dispositions,
  proposed source-license terms, dependency policy, and a named decision owner.
- A non-template [rights matrix](../../governance/schemas/rights-matrix.schema.json)
  covering every dependency, dataset, model, calibration, container, and report
  selected or proposed by its declared scope cutoff. Assets not yet selected
  are not guessed to make this ADR appear complete.
- Cross-record validation that the scope links the exact rights-matrix bytes by
  canonical path, ID, and SHA-256; both scope cutoffs match; and every intended
  asset lane exists in the proposed release scope.
- Authoritative terms evidence for every inventoried asset and legal review
  wherever commercial eligibility is claimed or the terms remain ambiguous.
- Evidence that assets assigned to different lanes can be kept separate.

## Follow-up evidence

- Add and review each dependency at M5, dataset at M6, baseline at M8, selected
  model/container/report at M11, and release asset at M14 before that asset is
  adopted or distributed.
- Re-review authoritative terms when a version, source, intended use,
  distribution surface, or derived-artifact plan changes.
- Reopen or supersede this ADR if later evidence invalidates the accepted
  purpose, license, release disposition, lane boundary, or dependency policy.

## Consequences not yet accepted

Until this ADR is accepted, the project must not claim commercial eligibility,
publish model weights, or infer a general reuse or redistribution license from
the public repository. This does not negate GitHub's platform-specific viewing
and forking permissions.
