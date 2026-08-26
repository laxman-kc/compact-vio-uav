# ADR-0001: Project and research-release scope

- Status: Accepted
- Decision owner: Project owner
- Decision date: 2026-08-26

## Context

The repository is public, but public visibility alone does not define permitted
reuse. The owner explicitly fixed the work as research-only and non-commercial.
The exact licence for third-party reuse can be selected later without blocking
ordinary project implementation.

## Decision

- Develop compact causal local VIO for UAV research in a publicly readable
  repository.
- Make no commercial-use or commercial-eligibility claim.
- Publish source, documentation, configurations, manifests, and small reviewed
  results as the research progresses.
- Do not mirror datasets or publish model weights, calibration bundles,
  containers, runtimes, or flight-system packages without a separate review.
- Until an exact licence file is selected, describe the repository as
  public-source research rather than claiming OSI open-source reuse rights.
- Review the licence/terms of each dependency, dataset, and model when it is
  actually selected; do not inventory hypothetical future assets.

## Evidence

- The project owner explicitly stated on 2026-08-26 that the work is public
  research and not commercial.
- The GitHub repository is public and contains the versioned research source and
  documentation.

## Rejected alternatives

- A commercial or commercially eligible lane is rejected for the current
  project scope.
- Parallel commercial/non-commercial release lanes are unnecessary for this
  one-person research project.
- Treating public visibility as a general software licence is rejected.

## Consequences

Local implementation, synthetic tests, rights-checked dataset research,
baseline work, and non-commercial experiments may proceed. External reuse or
redistribution rights must not be claimed until an exact licence is selected.
Every selected third-party asset keeps its own terms and attribution duties.

## Follow-up

- Select and add an exact source licence before inviting third-party reuse or
  presenting the repository as OSI open source.
- Review each dependency at M5, dataset at M6, baseline at M8, selected model or
  report at M11, and release asset at M14 when it is actually adopted.
- Reopen or supersede this ADR if the project later proposes commercial use or a
  broader binary/data release.
