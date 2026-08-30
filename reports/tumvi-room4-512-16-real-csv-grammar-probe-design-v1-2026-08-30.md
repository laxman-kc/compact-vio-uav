# TUM VI room4 512x512 real-CSV grammar probe design v1

Review date: 2026-08-30

Status: Inert specification and future-authorization controller implemented,
pushed, and CI-green on Python 3.10 and 3.12; no authorization, claim, receipt,
real-payload access, or grammar result; every readiness flag false; scientific
authority none

## Technical summary

Gate 3B is complete at the immutable implementation-and-CI boundary. Pushed
commit `d5bb14be25634f79ef9595cb04e629473338a2c2` freezes an inert
specification plus future-authorization controller, and GitHub Actions
[run 33294450083](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33294450083)
passed on Python 3.10 and 3.12. The specification binds four prior
receipt-bound CSV identities, the exact Gate 1 grammar, aggregate-only outputs,
resource ceilings, and prohibited operations. The controller can execute that
design only after a future exact one-use authorization exists. Its public
execution path durably publishes a claim before opening the first payload
descriptor, then performs one constant-memory pass that hashes and checks the
four exact files. Its bounded scanner uses transient line, cell, and
previous-timestamp state, but no source row contents or lexemes are persisted or
emitted.

The frozen bytes passed focused tests 43/43, a full repository run reporting
`OK` across 580 tests with 54 declared optional-capability skips, and a
240/240-case deterministic differential against the unchanged Gate 2 grammar.
An independent reviewer reproduced the focused and full results, bracketed the
full run with unchanged artifact hashes, and issued a hash-bound final PASS with
no P0 or P1 finding.

This is **not a real-data result**. No Gate 3B authorization exists. No claim or
receipt exists, and no real payload path was opened, read, or hashed. Therefore
there is no observed Gate 3B grammar acceptance or rejection, no adapter or
calibration evidence, no readiness, and no scientific authority. The immutable
commit and CI result close only the controller implementation boundary.

## Frozen implementation evidence is immutable and CI-green

| Artifact or gate | Exact result |
|---|---|
| [Inert probe specification](../configs/data/tumvi_room4_512_16_real_csv_grammar_probe_v1.json) | SHA-256 `e65ecc449ca878f9294dcb11accd6eb555232af284ad38f608cfc35c4642f790` |
| [Future-authorization controller](../src/compact_vio/data/tumvi_real_csv_grammar_probe.py) | SHA-256 `677197c4d0bc6573a2102495fa0491289a356ae655b21da364e8f701d4603a93` |
| [Synthetic/adversarial tests](../tests/test_tumvi_real_csv_grammar_probe.py) | SHA-256 `5fd1c544af84dcd90727a466e420d9aac104f9fafea73f93376f74b6b62e7281` |
| Implementation revision | `d5bb14be25634f79ef9595cb04e629473338a2c2`, pushed to `origin/main` |
| GitHub Actions | [run 33294450083](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33294450083), success |
| Python 3.12 CI job | `99211605353`, success, `2026-08-30T05:19:55Z`–`05:20:30Z` |
| Python 3.10 CI job | `99211605487`, success, `2026-08-30T05:19:55Z`–`05:20:38Z` |
| Focused suite, implementation owner | 43/43 passed in 30.183 seconds |
| Focused suite, independent reviewer | 43/43 passed in 29.411 seconds |
| Full suite, implementation owner | `OK` across 580 tests with 54 declared optional-capability skips in 52.667 seconds |
| Hash-bracketed full suite, independent reviewer | `OK` across 580 tests with 54 declared optional-capability skips in 62.041 seconds; all three hashes unchanged |
| Gate 2 deterministic differential | 240/240 mutation cases matched the frozen Gate 2 oracle |
| Ruff 0.16.4 | lint passed; format check reported 2 files already formatted |
| Python compilation | passed |
| Strict JSON parse | `python -m json.tool` passed for the inert specification |
| Frozen evidence identities | all 9 specification evidence paths matched their exact tracked `HEAD` and worktree hashes |
| Future output absence | exact authorization, claim, and receipt paths were absent |
| Independent adversarial review | final hash-bound PASS; no P0 or P1 finding |

The workflow was created and started at `2026-08-30T05:19:51Z` and reached
terminal `success` at `2026-08-30T05:20:39Z`. The committed specification,
controller, and tests retain the exact independently reviewed hashes above. Any
future byte change requires a new review; this run closes only the immutable
implementation-and-CI boundary.

## The design freezes four prior identities without reading them

The specification names exactly four CSV inputs under the retained,
Git-ignored compatibility-slice root. These sizes and hashes come from earlier
tracked receipt evidence; Gate 3B did not re-open or re-hash them.

| Role | Receipt-bound size | Prior receipt-bound SHA-256 |
|---|---:|---|
| `cam0` | 98,057 bytes | `feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67` |
| `cam1` | 98,057 bytes | `feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67` |
| `imu` | 2,232,296 bytes | `4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be` |
| `pose` | 1,481,244 bytes | `073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a` |

The total frozen source size is 3,909,654 bytes. The source-scope label states
that these are compatibility-slice-receipt-bound real CSV bytes without
independent origin authentication. A future identity match would establish only
that the opened bytes match those prior receipt identities; it would not
authenticate an external publisher origin or establish scientific semantics.

The inert specification binds nine tracked evidence identities:

| Bound evidence | SHA-256 |
|---|---|
| [Compatibility-slice receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json) | `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820` |
| [Format-inspection specification](../configs/data/tumvi_room4_512_16_format_inspection_v1.json) | `e8dd0bc98c7be85fed6d92d319bafec75c9f658584ea83d17ac93c6f47bdf1a7` |
| [Format-inspection receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json) | `30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846` |
| [Format-inspection report](tumvi-room4-512-16-format-inspection-2026-08-29.md) | `8048a399d611051e807c9824cdb141a5e6db1bcf77f9bd197483223fe887ef30` |
| [Gate 1 contract](../configs/data/tumvi_room4_512_16_adapter_contract_v1.json) | `4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5` |
| [Gate 1 contract loader](../src/compact_vio/data/tumvi_adapter_contract.py) | `26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20` |
| [Gate 2 synthetic parser](../src/compact_vio/data/tumvi_adapter_parser.py) | `4d5186a9559a4c111edda6df3d49a1484952ab6028a9269904ce4577efdc99e1` |
| [Gate 2 technical report](tumvi-room4-512-16-synthetic-parser-gate2-2026-08-29.md) | `04418a55c97d7ad71d7545129004f3760c62d818a81be3ffb97c0ee7b73ee6c8` |
| [Data-package boundary](../src/compact_vio/data/__init__.py) | `c3a6a55891323874481b1877fd703ec401cd601d0dd340b72c16d2a0463c8fa5` |

The unchanged data-package identity means Gate 3B adds no package-level export.
The Gate 1 loader, Gate 2 parser, its real-hash denylist, and the Gate 2 report
remain unchanged.

## Claim-before-open makes any future execution explicit and one-use

The checked specification and the specification, authorization, and receipt
loaders do not open payload paths. Only
`run_authorized_real_csv_grammar_probe` can reach the four source descriptors,
and only after all pre-claim gates pass and an exact durable claim is published:

`inert spec -> separate committed authorization -> clean exact revision -> durable claim -> four no-follow descriptors -> one-pass hash/grammar scan -> aggregate receipt -> final truth gates`

A future authorization must be a separately tracked record at the exact
controller-bound path. It must be active for exactly 24 hours, allow one
execution, bind the exact spec/evidence/tool identities, require a clean
worktree, fix a 600-second elapsed bound and controller-initiated paid cost at
USD 0, and preserve the exact permitted/prohibited operation lists. The elapsed
bound is checked before claim publication and hard-enforced from claim
preparation through receipt publication and the final truth gates; preclaim Git
and filesystem calls are not individually interrupted by that hard timer. The
authorization's authority basis remains an active workspace-user instruction
whose identity is not independently authenticated. None of those requirements
is satisfied by this implementation report because the authorization file does
not exist.

Before the first payload descriptor open, the controller additionally verifies
tracked `HEAD`/worktree truth, ignored source-root placement, trackable output
paths, source/output capacity, authorization lifetime, and absence of both the
claim and receipt. It atomically publishes and revalidates the claim. Once that
claim exists, the authorization is consumed with no retry even if later
identity, resource, deadline, I/O, or truth checks fail.

Source traversal retains no-follow descriptors for the bound path chain and
requires regular single-link files with exact size, identity, and stability.
The scanner reads every descriptor once through EOF in 65,536-byte chunks,
computes its exact SHA-256 during that pass, applies the strict Gate 1 grammar,
and compares the camera indexes in raw-byte lockstep through simultaneous EOF.
Memory is bounded independently of row count.

## Outputs are aggregate-only and grammar rejection is not an operational failure

The future terminal receipt's source-derived observations are limited to
per-stream aggregate counts, check states, grammar state, and the first
violation code plus physical line number. It also binds frozen source
identities/path metadata and controller execution/capacity metadata. It cannot
persist or emit source row contents or source lexemes. The fixed resource
boundary is:

| Limit | Exact value |
|---|---:|
| Source files | 4 |
| Total receipt-bound source bytes | 3,909,654 |
| Maximum CSV rows per file | 1,000,000 |
| Maximum physical-line bytes | 1,048,576 |
| Maximum CSV columns | 8 |
| Maximum claim bytes | 1,048,576 |
| Maximum receipt bytes | 1,048,576 |
| Required post-probe reserve | 2,147,483,648 bytes |

If all four streams accept the frozen Gate 1 grammar, the completed receipt's
grammar outcome is `accepts_frozen_gate1_grammar`. If any stream rejects it, the
controller still completes with an aggregate receipt whose outcome is
`rejects_frozen_gate1_grammar`. Rejection is a bounded grammar observation, not
an operational controller failure and not a dataset-quality or semantic claim.

An operational failure before claim publication opens no payload and consumes
nothing. An operational failure after claim publication preserves the claim,
produces no canonical receipt, and permits no retry. If a newly published
controller-owned receipt later fails a final truth gate, the controller retracts
that exact owned receipt while preserving the claim; it never removes a foreign
or changed receipt. Publication and rollback use retained descriptors, atomic
creation, filesystem synchronization, ownership identity, and bounded signal
masking.

The declared entry points are:

- `load_real_csv_grammar_probe_spec`;
- `load_real_csv_grammar_probe_authorization`;
- `load_real_csv_grammar_probe_receipt`;
- `run_authorized_real_csv_grammar_probe`; and
- `main`, exposed through
  `python -m compact_vio.data.tumvi_real_csv_grammar_probe --authorization PATH`.

The CLI emits one canonical aggregate JSON document on success or failure. It
does not emit source values.

## Synthetic adversarial coverage closes the implementation boundary only

The 43 focused tests use synthetic temporary files. They cover strict spec and
future-authorization loading without payload access; exact grammar acceptance
and a closed rejection corpus; constant-memory accounting; single-pass reads;
raw stereo lockstep and simultaneous EOF; exact size, digest, and source
stability; no-follow traversal; symlink, hardlink, FIFO, directory, ancestor,
and replacement races; clean-revision and evidence gates; preclaim zero-read
failures; irreversible claim consumption; deadline and authorization expiry;
atomic claim/receipt publication; receipt ownership and rollback under signals;
aggregate-forgery rejection; checked receipt loading without payload access; and
single-document CLI output.

The 240-case differential uses synthetic mutations only and matched Gate 2's
frozen grammar decisions exactly. It never passes a known real payload into the
Gate 2 synthetic API. Gate 2's three known-real-hash denials and its module hash
remain unchanged.

These tests establish implementation behavior under synthetic fixtures and
adversarial state changes. They do not establish that any real TUM-VI source
accepts or rejects the grammar.

## Limitations and authority remain unchanged

No authorized Gate 3B real-payload probe execution evidence exists. In
particular, this implementation does not establish:

- a real-source grammar outcome, source completeness, or dataset quality;
- independently authenticated origin for the prior receipt-bound identities;
- physical units, frames, transform direction, pose-reference meaning, or
  ground-truth role;
- clock equivalence, synchronization correction, association, interpolation,
  gap policy, or segment construction;
- PNG existence, validity, decoding, channel meaning, range mapping,
  normalization, or preprocessing;
- calibration access or a camera/IMU/pose calibration relationship;
- adapter implementation/readiness or a reusable real-payload parser boundary;
- dataset selection, source grouping, leakage review, or membership;
- model/checkpoint access, training, inference, evaluation, publication,
  deployment, or UAV-domain generalization.

Every readiness field remains false and scientific authority is `none`.
Calibration, image, segment, dataset-membership, learning, and model paths stay
closed.

## The next gate is only a separate one-use authorization decision

1. Separately decide whether one execution is still justified. This report and
   the successful implementation CI run do not authorize it.
2. If the decision is affirmative, create and independently review the exact
   one-use authorization as a new committed record.
3. Require that authorization revision itself to be pushed and CI-green without
   changing the frozen implementation identities.
4. Only after those authorization gates close may the exact CLI be invoked once.
   The controller must publish the durable claim before the first payload
   descriptor open.
5. Record only the resulting claim and, on completed execution, aggregate
   receipt. Review the receipt before considering any later calibration,
   adapter, segment, dataset-membership, or model gate.

No step here authorizes execution automatically. A future decision may decline
the real-payload probe entirely. Calibration access remains prohibited and is
not part of this immediate authorization gate.

## Further questions

- Is a one-use real-payload grammar observation decision-useful enough to
  justify a new authorization now that the implementation/CI boundary is closed?
- What exact reviewer and active-user evidence must the future authorization
  bind before the controller may publish its claim?
- If a future aggregate receipt records grammar rejection, what independent
  design review would be required before changing Gate 1 rather than broadening
  the probe?
- If it records acceptance, what additional calibration and semantic evidence
  would still be required before any adapter-readiness claim?
