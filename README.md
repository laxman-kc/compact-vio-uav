# compact-vio-uav

`compact-vio-uav` is a publicly readable, non-commercial research project for
compact visual-inertial odometry (VIO) on UAVs. The primary scope is causal,
metric-scale local odometry: mapping and loop closure are outside the main
comparison, and PX4 retains stabilization, failsafe, and motor control. Exact
sensor hardware, datasets and splits, numerical thresholds, deployment target,
and source licence remain decisions for the milestones that need them.

## Current status

The repository contains the reproducibility foundation, a deterministic causal
replay boundary, a framework-neutral estimator envelope with an explicit
interface-declaration and initialization/reset contract, and typed camera/IMU
payload records. It also contains immutable translation-trajectory records and
one raw exact-pair translation-RMSE primitive, plus a strict persisted
calibration-profile contract and a separate assessment contract, with a
visibly synthetic rejected fixture. These boundaries require explicit frames,
transform direction, units, time semantics, validity, reset, initialization,
health, state/policy identifiers, provenance, and calibration references
without selecting project-wide values.
It does not yet contain an estimator algorithm, a complete evaluator, an
accepted real sensor or dataset calibration profile, a trained model, an
approved dataset split, a deployable runtime, or a flight-ready system.
PyTorch is the proposed framework for future learned-component work, pending
ADR-0004; MLflow is an optional, currently absent observer. Neither is a current
package dependency.

A newly created Brev A10 worker was observed `RUNNING`, `READY`, and `HEALTHY`
on 2026-08-27 and is approved only for the current bounded implementation smoke.
It is not approved for dataset acquisition or model training and is never
treated as durable storage. A later task requires fresh owner confirmation.

The project follows these invariants:

- Git is the source of truth for versioned code, configuration, decisions, manifests, and small reviewed results.
- Rented GPU machines are disposable execution workers, never the sole copy of important state.
- Important retained artifacts from paid GPU work require verified storage
  outside the worker and an independent recovery copy.
- All estimator comparisons use one causal data/replay contract and one frozen evaluation protocol.
- Dataset rights, provenance, grouping, and split membership are recorded before use.
- Offline results do not authorize ROS/PX4 integration or physical flight.

## Planned research and training path

```text
local development -> GitHub -> future temporary GPU worker
                                      |
approved datasets -> canonical data -> frozen source-group splits
                                      |
                  +-------------------+--------------------+
                  |                   |                    |
          classical VIO        direct learned VIO    anchored hybrid VIO
          native execution    proposed framework    proposed framework
                  |                   |                    |
                  +-------------------+--------------------+
                                      |
                    common causal replay and evaluator
                                      |
                         scientific candidate selection
                                      |
             native package or checkpoint -> conditional export
```

Classical VIO is built and evaluated natively; it does not pass through any
neural training framework. PyTorch is the current proposal for learned and
hybrid candidates, not an accepted dependency. MLflow may observe a run, but
versioned configuration, run manifests, artifact hashes, trajectories, and
reports remain the portable source of truth. ONNX, TensorRT, Jetson, ROS 2, and
PX4 work begins only if the selected candidate and a later deployment decision
require it.

## Documentation map

- [Implementation plan](docs/plan.md)
- [Progress evidence](docs/progress.md)
- [Requirements index and official-source traceability](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Project requirements](docs/requirements/project-requirements.md)
- [Architecture decision records](docs/adr/README.md)
- [Research protocol](docs/protocols/research-protocol.md)
- [Experiment lifecycle](docs/protocols/experiment-lifecycle.md)
- [Dataset governance policy](governance/datasets/policy.md)
- [Candidate dataset registry](governance/datasets/registry.yaml)
- [Artifact policy](governance/artifacts/policy.md)
- [Governance-record authority and draft templates](governance/records/README.md)
- [Project/release scope record schema](governance/schemas/project-release-scope.schema.json)
- [Rights-matrix record schema](governance/schemas/rights-matrix.schema.json)
- [Artifact-storage plan schema](governance/schemas/artifact-storage-plan.schema.json)
- [Bounded worker-authorization schema](governance/schemas/worker-authorization.schema.json)
- [Run-manifest JSON Schema](experiments/schemas/run-manifest.schema.json)
- [Bundle-inventory JSON Schema](experiments/schemas/artifact-manifest.schema.json)
- [Post-export artifact-storage evidence schema](experiments/schemas/artifact-storage-evidence.schema.json)
- [Sensor calibration-profile schema](configs/schemas/calibration-profile.schema.json)
- [Calibration review/revalidation schema](configs/schemas/calibration-assessment.schema.json)

## Foundation checks

The installed package runtime is standard-library-only and currently provides a
causal replay primitive, framework-neutral estimator-envelope and declared
interface validation, typed sensor records, strict calibration profile/review
contracts with synthetic negative validation, exact translation-trajectory and
raw RMSE validation, bundle inventory/verification, two-copy content audit,
repository policy check, and read-only durability preflight. The
separate schema/record validator is development tooling and uses the
repository's pinned `jsonschema` dependency.
The inventory records every regular file by canonical relative path, byte size,
and SHA-256, and rejects symbolic links and unsupported filesystem entries.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compact_vio.repository_policy .
uv run --no-project --with 'jsonschema[format-nongpl]==4.26.0' python scripts/validate_schemas.py
PYTHONPATH=src python3 -m compact_vio.preflight
PYTHONPATH=src python3 -m compact_vio.artifacts create /path/to/frozen-run-bundle
PYTHONPATH=src python3 -m compact_vio.artifacts verify /path/to/restored-run-bundle
compact-vio-copy-audit --expected-manifest-sha256 <sha256> --primary /path/to/primary-copy --primary-ref primary-vault-copy --backup /path/to/backup-copy --backup-ref independent-backup-copy
```

The repository-policy command checks cached and non-ignored files for oversized
or forbidden artifacts, unsupported file types, invalid governed text, and a
small set of high-confidence secret formats without printing matched values.
`create` writes a new `artifact-manifest.json` inside the bundle and refuses to
replace any existing entry at that path. `verify` exits `0` for an exact match,
`1` for content differences, and `2` for invalid or unsafe input. These checks
establish file identity; they do not by themselves approve the run, its dataset
rights, or its scientific claims.

`compact-vio-copy-audit` is also read-only. It can compare two accessible bundle
copies against the exact raw SHA-256 of a frozen artifact manifest. Success is a
supporting checksum fragment only: it does not prove copy independence, event
chronology, deletion of a disposable source test copy, restoration into a new
location, representative load/open behavior, or completion of the artifact
restore gate. Successful JSON records only the caller-supplied opaque copy
references; local filesystem paths are deliberately omitted.

The preflight command is intentionally read-only. With no approved storage
inputs it exits `1` and reports the missing decisions. Even with satisfactory
static filesystem inputs it reports only `static_checks_satisfied`; it can never
mark the artifact restore gate passed. A client-visible filesystem identifier
and a caller-supplied record do not prove independent failure domains, storage
outside the worker, successful writes, or restoration. Object stores and other
backends require a provider-specific preflight.

`compact_vio.replay.CausalReplay` separates sensor measurement time from the
time an event becomes available to an estimator. It rejects mixed clocks,
duplicate identities, malformed ordering, backward time advances, and
availability before measurement. Reset and invalid events remain visible rather
than being silently dropped. This is a synthetic contract primitive, not a
dataset adapter or estimator.

`compact_vio.estimator.EstimatorInterfaceDeclaration` requires a selected
estimator profile to name its state schema and variables, metric-scale,
initialization/reset/recurrence, output-time/schedule, causality, latency,
staleness, and input-gap policies. These are opaque identifiers: the repository
has not selected their concrete values. Declared sessions additionally require
each output to report the same interface identity and an explicit initialization
state. Startup state, post-reset state, and whether validity requires
initialization are mandatory profile values, so the wrapper does not choose a
cold- or warm-start policy. It applies the declared post-reset state before the
adapter sees reset; this observable check does not prove the adapter reset its
internal state. The older undeclared session mode remains compatibility-only
and is not M3 evidence.

`compact_vio.evaluation.exact_pair_translation_rmse` compares only trajectories
whose sequence, segment, sample IDs, timestamps, clock, time semantics, frames,
transform direction, and unit already match exactly. Every call supplies a policy that
explicitly permits no interpolation, alignment, or scale correction. This is a
raw translation-error kernel, not aligned ATE, RPE, a metric-scale proof, a
coverage/failure score, or a real-data result.

`compact_vio.evaluation.summarize_output_coverage` counts a retained, nonempty
ledger of caller-declared expected output opportunities. Missing, invalid,
valid, reference-available, and explicitly usable outcomes remain separate,
and every non-usable item retains one or more reason codes under a named
classification policy. The primitive does not infer an output schedule,
timestamp association, run completion, tracking failure, or pass/fail result.

## State ownership

| State | Authoritative location | Future temporary-worker treatment |
|---|---|---|
| Source, configuration, decisions, manifests | GitHub repository | Clean checkout of an immutable revision |
| Raw/processed datasets and caches | Location recorded by dataset manifest | Disposable working copy |
| Selected checkpoints, trajectories, and reports | Reviewed local/archive location plus independent recovery copy for important retained runs | Temporary until exported and verified |
| Credentials | Approved secret store or local credential mechanism | Never committed; minimum access only |

The artifact destination, recovery copy, retention budget, and cost ceiling are
unresolved. A fresh read-only observation on 2026-08-27 found the new
`compact-vio-uav-gpu` worker `RUNNING`, `READY`, and `HEALTHY`; it is approved
only for the current bounded clean-checkout implementation smoke. Dataset
acquisition and model training remain outside that approval. Important or
extended GPU experiments that can create irreplaceable results must wait for
the storage restore gate in the
[artifact policy](governance/artifacts/policy.md). Every paid task still has a
short run plan, time/cost bound, export destination, and teardown owner.

## Decision status

The owner has fixed the project lane as public-source, research-only, and
non-commercial. No exact source licence has been selected, so the repository
does not yet claim OSI open-source status or grant general reproduction,
distribution, or derivative-work rights beyond GitHub's platform terms. That
licence decision gates external reuse and release packaging, not ordinary local
research implementation.

Accepted and open project decisions are listed in the
[ADR index](docs/adr/README.md). An ADR marked `Proposed` or `Unresolved` is not
an accepted implementation choice.

## Safety boundary

This is research software. It is not flight-certified and must not command
motors or authorize free flight. If integration is later approved, VIO is only
a health-gated external odometry measurement source; PX4 retains stabilization,
pilot override, failsafes, and motor authority. Integration must progress through
interface review, replay, software-in-the-loop, hardware-in-the-loop, bench, and
contained-flight gates.
