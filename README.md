# compact-vio-uav

`compact-vio-uav` is a publicly readable, non-commercial research project for
compact visual-inertial odometry (VIO) on UAVs. The primary scope is causal,
metric-scale local odometry: mapping and loop closure are outside the main
comparison, and PX4 retains stabilization, failsafe, and motor control. Exact
physical sensor hardware, confirmatory-test membership and thresholds,
deployment target, and source licence remain decisions for the milestones that
need them.

## Current status

The repository contains the reproducibility foundation, a deterministic causal
replay boundary, a framework-neutral estimator envelope with an explicit
interface-declaration and initialization/reset contract, and typed camera/IMU
payload records. It also contains immutable translation-trajectory records,
raw exact-pair signed translation-residual and translation-RMSE primitives,
explicit output-coverage accounting, exact replay/output binding, and a causal
execution recorder plus terminal recorder-plan coverage binding and a one-way,
payload-omitted terminal recorder-envelope encoder. The recorder
constructs a fresh replay/session pair,
releases one event at a time, retains only fully validated output batches, and
records the first failed event separately.
The repository also contains a strict persisted calibration-profile contract
and a separate assessment contract, with a visibly synthetic rejected fixture.
These boundaries require explicit frames, transform direction, units, time
semantics, validity, reset, initialization, health, state/policy identifiers,
provenance, and calibration references without selecting project-wide values.
ADR-0004's training-first development slice is now implemented and was executed
from pushed commit `9199d1507a2a76c522ca265afd8527ef9bd07225` on 2026-08-28.
The exact EuRoC Vicon Room source-sequence split, download identity,
preprocessing, model dimensions, losses, optimizer, and 30-epoch schedule are
versioned. A bounded NVIDIA A10 run produced a restorable development checkpoint
and held-out `V2_03_difficult` results. The raw, unaligned trajectory result is
not yet competitive with a zero-motion reference, so this is evidence that the
pipeline works end to end—not a completed estimator, superiority, deployable
runtime, or flight-readiness claim.

An exploratory follow-up at commit `92aa329` augmented training with frame
strides 1 and 2 while retaining native stride-1 evaluation. It improved the v1
pair errors and raw trajectory errors, but its 6.33804 m raw ATE remained worse
than the 2.05572 m zero-motion reference. Because the earlier
`V2_03_difficult` result informed this augmentation, the repeat is a development
diagnostic—not fresh held-out confirmation or a quality/superiority claim.

A second exploratory follow-up at commit
`336e88c7e80f6841c7d25b7da311172b40f5a3ba` added an eight-pair causal
recurrent training unroll and carried state only within the contiguous
held-out sequence. Relative to v2, it lowered pair translation RMSE by 1.783%,
raw ATE by 20.539%, and final drift by 3.745%, but rotation RMSE increased by
84.151% and the predicted/reference path ratio moved from 0.638679 to 0.553645.
Its 5.03625 m raw ATE still remained worse than the 2.05572 m zero-motion
reference. This is mixed exploratory evidence, not a superiority,
generalization, deployment, or flight-readiness result.

The next controlled exploratory follow-up at commit
`94d834a82bddb2e6185fb70ec289fd45017c325c` kept recurrent state for the
translation output while deriving rotation from a zero-initialized,
current-pair fusion state. Relative to v3, it lowered pair translation RMSE by
3.134%, pair rotation RMSE by 36.537%, raw ATE by 20.405%, and final drift by
24.996%. Its predicted/reference path ratio nevertheless fell from 0.553645 to
0.510652, raw ATE remained worse than zero motion, and rotation RMSE remained
16.868% worse than v2. It therefore passed the frozen translation and ATE gates
but failed the rotation gate and was rejected as a replacement candidate.
No further model or hyperparameter selection will use `V2_03_difficult`; the
next quality decision requires a fresh, predeclared evaluation unit.

All four A10 result bundles were copied to ignored local paths and
checksum-verified against the worker copies, including
`outputs/euroc-compact-vio-v4-translation-state-full-94d834a`. The worker remains
running by explicit choice and has not been stopped or terminated. Worker
storage is never treated as durable.

The project follows these invariants:

- Git is the source of truth for versioned code, configuration, decisions, manifests, and small reviewed results.
- Rented GPU machines are disposable execution workers, never the sole copy of important state.
- Important retained artifacts from paid GPU work require verified storage
  outside the worker and an independent recovery copy.
- All estimator comparisons use one causal data/replay contract and one frozen evaluation protocol.
- Dataset rights, provenance, grouping, and split membership are recorded before use.
- Offline results do not authorize ROS/PX4 integration or physical flight.

## Training-first development path

```text
EuRoC Vicon Room source sequences
                  |
          identity/rights record
                  |
         official calibration validation
                  |
       sequence-disjoint split manifest
                  |
       cam0 frame pair + causal IMU window
           |                    |
     compact CNN         GRU/Conv1D encoder
           +--------- gated frame-pair fusion
                          |
             relative translation + rotation
                          |
              PyTorch smoke -> bounded train
                          |
                     checkpoint.pt
                          |
        held-out inference + trajectory integration
                          |
        ATE / RPE / rotation / coverage / resources
```

Ground truth is a label only for training membership and evaluator-only for
validation/test membership; it is never an inference input. The first output is
a trained development prototype, not a publishable superiority claim or a
flight-ready estimator. A/B/C/D reliability experiments and a native classical
reference remain later research ablations. ONNX, TensorRT, edge hardware,
ROS 2, and PX4 remain later conditional work.

## EuRoC training quickstart

Install the real-data/training dependencies, acquire only the selected Vicon
Room archives, and run the bounded smoke before the full configuration:

```bash
python3 -m pip install -e '.[train]'

compact-vio-euroc \
  --plan configs/data/euroc_vicon_v1.json \
  --archive vicon_room1 \
  --raw-dir /data/euroc/raw \
  --data-dir /data/euroc/sequences \
  --sequence V1_01_easy --sequence V1_02_medium --sequence V1_03_difficult

compact-vio-euroc \
  --plan configs/data/euroc_vicon_v1.json \
  --archive vicon_room2 \
  --raw-dir /data/euroc/raw \
  --data-dir /data/euroc/sequences \
  --sequence V2_01_easy --sequence V2_02_medium --sequence V2_03_difficult

compact-vio-train \
  --config configs/training/euroc_compact_vio_v1.json \
  --data-root /data/euroc/sequences \
  --output-dir /runs/euroc-compact-vio-v1-smoke \
  --device cuda --smoke

compact-vio-train \
  --config configs/training/euroc_compact_vio_v1.json \
  --data-root /data/euroc/sequences \
  --output-dir /runs/euroc-compact-vio-v1 \
  --device cuda
```

Both acquisition commands verify the committed byte length, official MD5, and
locally recorded SHA-256 before extraction. The trainer refuses a nonempty
output directory, binds checkpoints to the Git revision, configuration, split,
calibration, and extracted source hashes, and writes held-out predictions plus
raw, unaligned SE(3) metrics. A worker output is temporary until copied away
and verified.

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
- [Recorder snapshot envelope schema](experiments/schemas/recorder-snapshot-envelope.schema.json)
- [Sensor calibration-profile schema](configs/schemas/calibration-profile.schema.json)
- [Calibration review/revalidation schema](configs/schemas/calibration-assessment.schema.json)

## Foundation checks

The installed package runtime is standard-library-only and currently provides a
causal replay primitive, framework-neutral estimator-envelope and declared
interface validation, typed sensor records, strict calibration profile/review
contracts with synthetic negative validation, exact translation-trajectory,
raw signed-residual and RMSE validation, output-coverage accounting,
replay/output binding, terminal recorder-plan coverage binding, direct causal
execution recording, terminal payload-omitted recorder-envelope encoding, bundle
inventory/verification, two-copy content
audit, repository policy check, and read-only durability preflight. The separate
schema/record validator is development tooling and uses the repository's pinned
`jsonschema` dependency.
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

`compact_vio.evaluation.exact_pair_translation_residuals` applies the same
exact-pair policy and returns each raw signed Cartesian residual as estimated
translation minus reference translation. The series is an in-memory record
only. It is not ATE, RPE, coverage or completion evidence, and matching declared
metadata does not prove that source frames or transforms are scientifically
correct.

`compact_vio.evaluation.summarize_output_coverage` counts a retained, nonempty
ledger of caller-declared expected output opportunities. Missing, invalid,
valid, reference-available, and explicitly usable outcomes remain separate,
and every non-usable item retains one or more reason codes under a named
classification policy. The primitive does not infer an output schedule,
timestamp association, run completion, tracking failure, or pass/fail result.

`compact_vio.evaluation.bind_output_coverage` binds that ledger to retained
replay events and the exact estimator-output tuple returned for each event.
Produced outcomes name a zero-based tuple ordinal; missing outcomes explicitly
name no ordinal. Every expected opportunity and every observed output envelope
must be accounted for exactly once. The binding never matches by timestamp or
assumes one output per event.

`compact_vio.evaluation.bind_recorded_output_coverage` extends that exact
binding to a terminal recorder snapshot. It retains the complete planned event
tuple, allows caller-declared missing opportunities on the failed event and
unattempted suffix, and requires every output in every successfully recorded
batch to be bound exactly once. It does not create opportunities, reason codes,
failure labels, thresholds, or a run-success decision.

`compact_vio.execution.CausalEstimatorRecorder` constructs and privately retains
one fresh, clock-matched `CausalReplay` and `EstimatorSession`. It releases one
event at a time, retains a batch only after the complete returned tuple passes
session and batch validation, and leaves later events unconsumed after a
failure. Its structurally frozen in-memory snapshot retains the complete event
plan, watermark, successful batches, first failed event and exception type,
whether session delivery/reset transition occurred, replay counts, and reset
generation. The recorder requires and retains an immutable
`ExecutionLifecyclePolicyDeclaration`: five caller-supplied versioned IDs name
the recorder's replay-exhaustion, processing-exception, process-control-
exception, and unattempted-suffix semantics. The declaration chooses no values,
failure taxonomy, threshold, output schedule, or scientific-success rule.
Generic payload objects are not deep-copied, and the snapshot is not persistent
run evidence. The recorder does not infer expected output opportunities,
missing-output reasons, estimator success, or scientific run acceptance.

`compact_vio.execution_trace.recorder_snapshot_envelope_to_json_bytes` projects
an exact terminal snapshot into deterministic UTF-8 JSON with a strict
structural schema at
`experiments/schemas/recorder-snapshot-envelope.schema.json`. It preserves the
ordered event plan, successful output-envelope metadata, lifecycle-policy IDs,
counts, and first-failure metadata while manually omitting every event and
estimator payload. It supplies neither a deserializer nor a filesystem writer.
The envelope is not a full trace: the encoder adds no dedicated representation,
type, hash, or cryptographic commitment for omitted payloads, so the envelope
alone cannot prove their identity. It also does not prove replayability, dataset
provenance, adapter lineage, coverage, lifecycle success, or scientific acceptance.
Schema validity alone does not authenticate recorder origin or prove count and
batch-to-plan relationships in arbitrary external JSON; trusted envelopes must
come from this encoder's validated `RecorderSnapshot` input.

## State ownership

| State | Authoritative location | Future temporary-worker treatment |
|---|---|---|
| Source, configuration, decisions, manifests | GitHub repository | Clean checkout of an immutable revision |
| Raw/processed datasets and caches | Location recorded by dataset manifest | Disposable working copy |
| Selected checkpoints, trajectories, and reports | Reviewed local/archive location plus independent recovery copy for important retained runs | Temporary until exported and verified |
| Credentials | Approved secret store or local credential mechanism | Never committed; minimum access only |

The artifact destination, recovery copy, retention budget, and cost ceiling are
unresolved. A dated read-only observation on 2026-08-27 found
`compact-vio-uav-gpu` `RUNNING`, `READY`, and `HEALTHY`, and the owner authorized
that bounded clean-checkout implementation smoke only. The record proves
neither current state nor authority for a later paid-worker run. The accepted
ADR authorizes implementation of the development workflow; important or
extended GPU experiments
that can create irreplaceable results must wait for the storage restore gate in the
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
