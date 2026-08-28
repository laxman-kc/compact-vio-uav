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

## Reviewed reports

- [EuRoC MH_01 frozen position-only evaluation](euroc-mh01-frozen-position-evaluation-2026-08-28.md)
- [EuRoC compact VIO v4 translation-state exploratory result](euroc-compact-vio-v4-translation-state-exploratory-2026-08-28.md)
- [EuRoC compact VIO v3 stateful exploratory result](euroc-compact-vio-v3-stateful-exploratory-2026-08-28.md)
- [EuRoC compact VIO v2 exploratory result](euroc-compact-vio-v2-exploratory-2026-08-28.md)
