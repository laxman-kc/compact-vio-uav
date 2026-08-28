# Dataset governance policy

Status: Foundation policy
Last reviewed: 2026-08-27

## Principles

- Being publicly downloadable does not grant unrestricted use or redistribution.
- A software-repository license does not automatically license separately hosted dataset files.
- Dataset permission does not establish model safety, product suitability, or permission for every downstream use.
- Candidate status is not approval for download, training, evaluation, redistribution, or publication.
- Dataset files remain outside Git unless an explicit reviewed exception exists.

The [representative dataset-unit candidate brief](evidence/representative-unit-candidate-brief.md)
is supporting evidence for later review. It does not approve acquisition or use.

## Approval record

Before acquisition or use, record:

- Stable dataset ID and version/release.
- Official landing page and authoritative rights source.
- Access date and exact rights label.
- Intended project lane and role.
- Exact sequences/files/modalities/sensor suite.
- Compressed and expanded size estimate.
- Source checksum or generated SHA-256.
- Calibration, timestamps, units, ground-truth, and known-gap status.
- Source-group definition and split membership.
- Redistribution and attribution obligations.
- Reviewer and approval date.

If rights are unclear, mark `rights.status: unresolved`; no commercial/distribution claim may depend on the dataset.

## Source grouping and leakage control

Assign a stable `source_group_id` before creating windows or derivatives. A group must contain all samples sharing information that could make evaluation non-independent, including as applicable:

- One physical trajectory or capture session.
- Synchronized cameras and modalities.
- Renders of the same underlying pose trace.
- Weather, lighting, difficulty, or corruption variants derived from one source.
- Overlapping temporal windows.

Train, validation, final-test, and stress membership are mutually exclusive at the approved grouping level. Store split manifests as versioned small metadata with checksums. Any split revision creates a new protocol version and invalidates direct aggregation with prior results unless explicitly analyzed.

## Acquisition and integrity

1. Approve rights, role, size, and location.
2. Download one representative unit from the official source.
3. Record byte size and SHA-256.
4. Validate archive integrity and safe extraction.
5. Validate timestamps, sample rates, units, axes, gravity, rotations, calibration, sensor-suite consistency, and ground-truth coverage.
6. Estimate expanded size before full acquisition.
7. Acquire only approved modalities and groups.
8. Revalidate and record the resulting manifest.

## Processing provenance

Every processed dataset identifies its raw manifest, transformation configuration and implementation revision. Normalization statistics and learned preprocessing artifacts identify the training split used to create them. A processed cache is disposable unless the cost of exact recreation justifies retention and the transformation remains traceable.

## Publication and deletion

- Publish metadata/manifests only when permitted; do not mirror source data by default.
- Include required attribution and cite the official source.
- Remove local copies when the approved retention period ends.
- Record deletion when rights terms, consent, or owner requests require it.
- Re-review rights before a public model/data release or a change from research to commercial use.
