# Configuration registry

This directory will hold versioned, human-reviewable configuration for approved
baselines, model candidates, and experiments. It intentionally contains no
default estimator, sensor, dataset split, loss, or deployment target: those
values remain blocked by the decision gates in `docs/`.

When a track is approved, add its configuration below one of these namespaces:

- `baselines/` for classical reference implementations;
- `models/` for learned or hybrid candidate definitions;
- `experiments/` for resolved run configurations that reference frozen dataset
  and split manifests.

Every claim-supporting run must preserve the fully resolved configuration in its
experiment bundle. Configuration files must contain no credentials, machine-
local absolute paths, or unversioned dataset aliases.
