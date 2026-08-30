# Reports

Only small, reviewed, claim-supporting summaries belong in Git. Raw logs,
checkpoints, complete tracker directories, and generated caches remain outside
normal Git history and are governed by the artifact policy.

Each committed report must identify the exact Git revision, experiment run IDs,
dataset and split manifest hashes, evaluation protocol version, and artifact
manifest for any external evidence it summarizes. A report must distinguish
measured results from literature values and from engineering projections.

A prospective control record may be committed before execution only when it is
labelled `pending execution`, binds every already-existing control by exact
identity, and marks every future revision, run, protocol, artifact, and result
field as pending. It must be updated from observed artifacts after execution;
its presence is not evidence that a run happened or that a hypothesis passed.

## Prospective control records

- [EuRoC compact VIO v5 controlled magnitude-loss experiment](euroc-compact-vio-v5-magnitude-loss-plan-2026-08-28.md)
  — retained as the rule frozen before execution; see the rejected outcome
  below.

## Reviewed reports

- [TUM VI room4 512x512 real-CSV grammar-probe Gate 3B implementation design](tumvi-room4-512-16-real-csv-grammar-probe-design-v1-2026-08-30.md)
  — inert spec and future-authorization controller frozen and independently
  reviewed on synthetic fixtures, pushed, and CI-green on Python 3.10/3.12; no
  authorization, claim, receipt, real-payload access, grammar result, readiness,
  or scientific authority.
- [TUM VI room4 512x512 synthetic parser Gate 2](tumvi-room4-512-16-synthetic-parser-gate2-2026-08-29.md)
  ([gate-status visual](assets/tumvi-gate2-parser-status.svg)) — bounded
  synthetic `BytesIO` parsers pushed and CI-green; no real data opened, the
  parser-assigned scope does not authenticate origin, 2 engineering gates
  verified and 5 blocked, every
  readiness flag false, and scientific authority none.
- [TUM VI room4 512x512 adapter-contract Gate 1](tumvi-room4-512-16-adapter-contract-v1-2026-08-29.md)
  — strict grammar/source-labelled-output policy and loader implemented and
  CI-green on Python 3.10 and 3.12; no payload parser or adapter, every
  readiness flag false, and scientific authority none.
- [TUM VI room4 512x512 bounded format inspection](tumvi-room4-512-16-format-inspection-2026-08-29.md)
  — completed `does_not_conform`: mocap-header and initial timestamp-range
  gates failed; adapter/calibration/ground-truth readiness false and scientific
  authority none.
- [TUM VI room4 512x512 audit-bound regular-file compatibility slice](tumvi-room4-512-16-compatibility-slice-2026-08-29.md)
  — completed exact eight-file operational extraction; payloads uninterpreted
  and scientific authority none.
- [TUM VI room4 512x512 structural archive audit](tumvi-room4-512-16-structural-audit-2026-08-29.md)
  — completed header-only classification of the retained archive; strict
  extraction incompatible and scientific authority none.
- [EuRoC compact VIO v5 controlled magnitude-loss result](euroc-compact-vio-v5-magnitude-result-2026-08-28.md)
  ([visual summary](assets/v5-magnitude-result.svg); [governed run-record
  mirror](evidence/euroc-compact-vio-v5-magnitude-full-6c46b2f/README.md))
- [EuRoC MH_01 frozen position-only evaluation](euroc-mh01-frozen-position-evaluation-2026-08-28.md)
- [EuRoC compact VIO v4 translation-state exploratory result](euroc-compact-vio-v4-translation-state-exploratory-2026-08-28.md)
- [EuRoC compact VIO v3 stateful exploratory result](euroc-compact-vio-v3-stateful-exploratory-2026-08-28.md)
- [EuRoC compact VIO v2 exploratory result](euroc-compact-vio-v2-exploratory-2026-08-28.md)
