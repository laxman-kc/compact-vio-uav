# compact-vio-uav

> **Current focus:** finish the [offline model completion sprint](docs/model-completion-sprint.md):
> full-trajectory evaluation, a selected checkpoint, recording inference,
> ONNX parity, and a local demo. ROS/PX4 and physical hardware are later work.

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

Commit `deea10f767dd207c181d09521d47667cc15c8d6d` then froze v2, v3,
and v4 checkpoint identities plus a position-only `MH_01_easy` endpoint before
execution. Under protocol SHA-256
`2610644fdcffaf2d44f327f3135de3795cfcaa91f7d9a8491d850035a7073425`,
all candidates produced 3,681 sensor pairs and scored all 2,926
reference-eligible pairs; 755 pairs remained visibly excluded by the frozen
reference-gap rule. V2's pair displacement-magnitude RMSE of
`0.017339865612729627` m was the rule's minimum and beat the zero-motion value
of `0.02649378180034436` m, so v2 was selected for this endpoint without tuning.
The [reviewed report](reports/euroc-mh01-frozen-position-evaluation-2026-08-28.md)
records the association, 207 retained reference segments, declared Leica lever
arm, all metrics, and exact hashes. This position-only decision is not a
full-pose/rotation result, ATE, deployment approval, or publication-grade
confirmation.

The one controlled v5 experiment has completed; it was not an open tuning
loop. V2 remains the exact control. The
`compact-vio-export-inference` path produces an optimizer-free PyTorch
checkpoint that retains canonical `TrainingConfig`, provenance, inference
policy, and selected source epoch/metrics lineage, but not optimizer state or
full training history. Canonical metadata/model-state hashes and bitwise
prediction parity define model identity. The outer PyTorch-file SHA is a
transport-integrity identity for one exact file and can differ across runtimes
because of container bookkeeping. A local verification export had file SHA-256
`4e2281a97a071cd20c16b2e5329a750b681fa74aea53002f110662ebc7fba29e`;
the immutable A10 export has file SHA-256
`521e9813fde80f68cb0734fd474a1cf08e8d4ef767fc8cd53bd2adf08ead2202`.
Both share canonical metadata SHA-256
`63f632912862067c471020d4cda4f2e87772eda0f2d59a29f434fba71a8be321`
and model-state SHA-256
`f70693fc2c188773ef8e78779f6e5d1a01b22e14067204cd8cc18ba4691d650d`.
The A10 file is retained locally with artifact-manifest SHA-256
`17a1b73abf1223fd8a010391d768849c30830c81914e2c30e7c383d61d095723`.
V5 kept v2's architecture, data/split, frame strides, seed, optimizer,
independent-pair state policy, checkpoint rule, and 30-epoch schedule; its only
declared behavioral change was an explicit unit-weight Smooth-L1
translation-magnitude loss, configured by
`translation_magnitude_loss_weight: 1.0` in
`configs/training/euroc_compact_vio_v5_magnitude.json`.

The single full run at revision
`6c46b2f8ef719a7007eef72eebe13b34575aea93` completed all 30 epochs and
selected epoch 29. Its selected validation translation RMSE was
`0.05985308049522323` m, above the frozen v2 limit of
`0.058765891780989885` m; rotation RMSE was `0.007484109588922632` rad,
above the limit of `0.0061899144990098035` rad. Both predeclared guardrails
failed. V5 was therefore rejected before fresh evaluation, inference export,
deployment work, or any `MH_02_easy` access. There was no retry or tuning.
The [prospective control record](reports/euroc-compact-vio-v5-magnitude-loss-plan-2026-08-28.md)
preserves the rule declared before execution; the
[reviewed result](reports/euroc-compact-vio-v5-magnitude-result-2026-08-28.md)
records the observed run and mechanical rejection.

`V2_03_difficult` and `MH_01_easy` have already informed development, so neither
can be presented as untouched v5 confirmation. The completed full run still
emitted its configured `V2_03_difficult` development diagnostics, but those
results did not and cannot override the validation guardrail. `MH_02_easy` was
never extracted, opened, or used for inference and remains unconsumed by v5.
The next safe scientific step is to select and freeze a new full-pose
evaluation unit and protocol independently before any new model work. Exact
dataset membership, reference capabilities, controls, native classical
backend, metrics, thresholds, and tie rule must be recorded before execution;
none is silently selected here.

The next full-pose lane now has a non-executable TUM VI `room4` 512x512
candidate identity plus production archive primitives. The candidate and
acquisition records bind the official request/redirect observation, observed
byte length, exact MD5 sidecar, later received-byte SHA-256, and lack of
scientific authority. The downloader
and TAR layer provide closed redirect validation, bounded resume, crash-safe
single-writer locking, held-descriptor digest verification, SHA-pinned
read-only inventory, hostile-member rejection, and atomic allowlisted
extraction. The one-use TUM VI transfer executed once: the received archive
passed the official size and MD5 checks and was retained under SHA-256
`2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`,
but strict TAR inventory rejected an official `dso/cam1/images` symbolic-link
member. No inventory or success receipt was published, no extraction occurred,
and that authorization is consumed. The controller requires clean
tracked `HEAD` inputs, an ignored quarantine destination, a pre-network
single-use claim, fixed capacity/time/cost limits, and an immutable success
receipt. The failed transfer grants no extraction, dataset selection,
checkpoint loading, inference, evaluation, or publication authority; a revised
read-only archive policy and later selection/protocol freeze remain required.
A separate header-only structural audit then completed once from authorization
revision `9709a101b28f291de23826ac8c9abec6a6eb9846`, after GitHub Actions run
`33276534039` passed. It recorded 4,485 TAR members: 4,472 regular files, 11
directories, and two inert DSO-tree symbolic links to the corresponding
`mav0` camera data directories. It followed no link, extracted nothing, and
reverified the unchanged archive SHA-256 before publishing its tracked receipt.
The result is explicitly `strict_extraction_compatible: false`; the original
strict inventory/extractor still rejects the archive. A separate audit-bound
regular-slice controller and exact allowlist are now implemented and locally
verified. They select only four complete `mav0` CSV members and the earliest
two common regular PNG names from each camera: eight regular files totaling
5,043,300 bytes. The controller compares every live TAR header with the frozen
4,485-member audit, follows no link, excludes `dso`, publishes a new exact tree
atomically, and writes its receipt last. Implementation commit
`9ca97e04848fe08d14841470a7a7bf39b5edd725` passed GitHub Actions run
`33279450649`. The separate one-use authorization revision
`cfe863890ad040684ac837c1b5d7f346bc0159cc` then passed GitHub Actions run
[`33279713875`](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33279713875)
and executed once. It published the exact eight-file, 5,043,300-byte ignored
tree and a 7,106-byte tracked receipt with SHA-256
`a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`.
The controller ran for `8.26419195800554` seconds at zero paid-service cost.
A read-only post-run walk reconfirmed eight directories below the destination,
eight single-link regular files, no special files, and every receipt-recorded
size and SHA-256 without parsing CSVs or decoding PNGs. The retained archive
still has size 1,356,206,080 bytes, MD5
`8e2ec2c35ee40a54c9aaa5bc2b3c9d8c`, and SHA-256
`2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`.
The
[reviewed structural-audit report](reports/tumvi-room4-512-16-structural-audit-2026-08-29.md)
records the source layout, and the
[reviewed compatibility-slice report](reports/tumvi-room4-512-16-compatibility-slice-2026-08-29.md)
records the exact execution and output identities. The slice grants no
dataset selection, membership, payload interpretation, model, inference,
evaluation, or publication authority. A separately authorized bounded format
inspection was then implemented at commit
`b83eebf3cc24cfada57d2d76da4a19672ef8267a` after GitHub Actions run
`33282946955` passed and executed once from revision
`7dfe85b8c7a3de04a1c789a79a139fa90ad5d5a4` after run `33283206142`
passed. Its 16,879-byte receipt has SHA-256
`30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846`
and records `completed` / `does_not_conform`: seven of ten frozen operational
gates passed, while the eight-column mocap header and two first-camera
timestamp range checks failed. Adapter, calibration, and ground-truth readiness
remain false; scientific authority is `none`. The current EuRoC adapter must
not be reused and no model work follows. Gate 1 of the replacement path is now
implemented at pushed commit
`bc71dd5ebfdc636994a384a0a5dd2fd22184720d`; GitHub Actions
[run 33286985057](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33286985057)
passed its Python 3.10 and 3.12 jobs. The strict TUM-VI-specific adapter
**contract** and loader freeze exact source-lexeme grammars, source-labelled
output shapes, stereo-index identity requirements, resource ceilings, and an
integer-token interval policy that makes no clock-equivalence claim. The
loader reads only the canonical contract and six exact tracked evidence files;
it opens no real dataset payload, calibration, image, learning, or model path.
It is not a payload parser or adapter. All operational readiness flags remain
false and scientific authority remains `none`. Gate 2 is now implemented at
pushed commit `3379060f83801230e5fe8c52e7bd0c3c288e5253`; GitHub Actions
[run 33289072534](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33289072534)
passed on Python 3.10 and 3.12. Its bounded parsers accept exact in-memory
synthetic camera, IMU, source-labelled pose, and stereo CSV fixtures under the
Gate 1 contract. They opened no real data, deny the known inspected real CSV
hashes before reading, and have no filesystem loader, CLI, package-level data
export, calibration/image/EuRoC bridge, learning/model dependency, or segment
constructor. The parser-assigned synthetic-only scope labels caller-supplied
bytes but does not authenticate their origin, so successful parsing grants no
real-source or scientific authority. Gate 3B is now implemented at pushed commit
`d5bb14be25634f79ef9595cb04e629473338a2c2`; GitHub Actions
[run 33294450083](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33294450083)
passed on Python 3.10 and 3.12. Its independently reviewed inert specification
and one-use controller bind an exact four-file aggregate real-CSV grammar probe.
Focused tests passed 43/43, the full suite reported `OK` across 580 tests with 54
declared optional-capability skips, and 240/240 synthetic differential cases
matched the unchanged Gate 2 grammar. The first reviewed authorization was
consumed when an auditor preflight published claim SHA-256
`f63263fd0b9f086075b7002c4b4e5dd2ca30112587a7c1b31966e9557afae490`;
a wholly mocked binder then stopped execution before any payload descriptor
open. No receipt exists and no retry is permitted for that authorization. After
recovery commit `abd7af3d77c12637144b324465ab462752629872` passed CI, a
separate authorization-only revision
`47daabc1891b71e53a6d3f4f5a070d69bbbe5c78` passed GitHub Actions
[run 33297367015](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33297367015)
and executed once. Its 1,012-byte claim has SHA-256
`beba4617be76bf63870ff0957c0d4b187abe2caf7fcc6f0b336bf2b6fcc53403`;
its 8,259-byte checked receipt has SHA-256
`7ea8720fc013504de8db22396a5eb4d8bf8f25f33cd00ab2e6798bd42d42c958`
and records `completed` / `rejects_frozen_gate1_grammar`. Both camera indexes
accepted 2,228/2,228 rows and passed raw lockstep; IMU accepted 22,212/22,212;
pose rejected at `exact_header_mismatch` on physical line 1 with 13,075 data
lines and zero validated. No source row contents or lexemes were persisted or
emitted. The negative aggregate result does not authorize a grammar change,
payload parser, adapter, calibration, segment, dataset selection/membership, or
model work. The immediate next gate is a separate reviewed contract-mismatch
reconciliation decision; any source re-access requires new exact one-use
authority. Every readiness flag is false and scientific authority is `none`.

All five training result bundles were copied to ignored local paths and
checksum-verified against the worker copies. The original v5 trainer output is
preserved unchanged inside a governed wrapper at
`outputs/euroc-compact-vio-v5-magnitude-governed-v2-6c46b2f` with checkpoint SHA-256
`f26267f2cb55962ba236257acda0a7ac97ad87f93ae0ecdcb585026fa21f0741`
and outer artifact-manifest SHA-256
`548fd52ffd0d89e4a7d347c78a8e9c4ba799c84dd74f7e0a6f3a365f0ba3b91e`.
The wrapper adds a schema-valid run manifest, resolved configuration,
environment, and execution record without mutating the original inner manifest
`9628a7b93da229700b07aa9bb43c07e8b31f68bd4e9ee764b4d7ad06ac63b2f9`;
its run-manifest SHA-256 is
`aeeb4f573d7dcf590f4f0aaf3fd49e922498ec5e2c465fd87e7c00aabf272af4`.
Verification passed for the canonical local wrapper. The original trainer
bundle remains independently verified at its worker and local paths; the
canonical governed-v2 wrapper has not been copied to or verified on the
worker. A superseded draft wrapper is not the evidence target. Small immutable
records are mirrored under `reports/evidence/`. This is not the
still-unresolved independent-vault, backup, or restore gate. The MH_01
evaluation artifacts at
`/home/ubuntu/compact-vio-runs/euroc-mh01-frozen-position-deea10f` were copied to
ignored local path `outputs/euroc-mh01-frozen-position-deea10f`; their
seven-file artifact manifest verified at both locations with SHA-256
`184d9427ebec373edb4da222bba5ea382146369a61b471b92b30b0e328ce8e76`.
At the last recorded execution observation, the worker was left running by
explicit choice and was not stopped or terminated. Its present lifecycle state
has not been re-established in this closeout because the Brev session is no
longer authenticated. Worker storage is never treated as durable.

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
- [Controlled v5 magnitude-loss result](reports/euroc-compact-vio-v5-magnitude-result-2026-08-28.md)
- [Controlled v5 magnitude-loss experiment](reports/euroc-compact-vio-v5-magnitude-loss-plan-2026-08-28.md)
- [TUM VI bounded format-inspection result](reports/tumvi-room4-512-16-format-inspection-2026-08-29.md)
- [TUM VI adapter-contract Gate 1 report](reports/tumvi-room4-512-16-adapter-contract-v1-2026-08-29.md)
- [TUM VI synthetic parser Gate 2 report](reports/tumvi-room4-512-16-synthetic-parser-gate2-2026-08-29.md)
- [TUM VI real-CSV grammar-probe Gate 3B result](reports/tumvi-room4-512-16-real-csv-grammar-probe-result-2026-08-30.md)
- [TUM VI real-CSV grammar-probe Gate 3B implementation report](reports/tumvi-room4-512-16-real-csv-grammar-probe-design-v1-2026-08-30.md)
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
