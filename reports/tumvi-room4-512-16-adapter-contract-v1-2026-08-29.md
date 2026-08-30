# TUM VI room4 512x512 adapter-contract Gate 1

Review date: 2026-08-29

Status: Strict contract and loader implemented, pushed, and CI-green on Python
3.10 and 3.12; no real payload access; every readiness flag false; scientific
authority none

## Technical summary

Gate 1 is complete at the immutable source-and-CI boundary. The project now has
an exact TUM-VI-specific grammar and source-labelled output-policy contract plus
a sealed loader that accepts only the canonical tracked record and its six
exact tracked evidence inputs. Focused tests passed 22/22 and the full repository
suite passed 517/517. Lint, format, compilation, schema, repository-policy, JSON,
and diff checks also passed, and independent adversarial review reported no P0
or P1 finding.

This result does **not** implement a TUM-VI payload parser or adapter. It opened
no ignored dataset payload, calibration file, PNG payload, learning code, or
model path. The contract deliberately leaves clock mapping, gap thresholds,
segment construction, pose association/interpolation, image decoding, and
preprocessing null or blocked. Every readiness flag is false and scientific
authority is `none`.

The immediate next gate is pure synthetic parsing against the frozen grammar.
No real-payload or calibration read is implied by this result.

## Exact implementation identity and validation

| Artifact or gate | Exact result |
|---|---|
| [Canonical contract](../configs/data/tumvi_room4_512_16_adapter_contract_v1.json) | SHA-256 `4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5` |
| [Strict loader](../src/compact_vio/data/tumvi_adapter_contract.py) | SHA-256 `26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20` |
| [Focused tests](../tests/test_tumvi_adapter_contract.py) | SHA-256 `612ed53ff3ed1dbe2d7a51e9c69d99b83a60ea19eeeb922ed2da2a1f813a7a3c`; 22/22 passed |
| Full repository tests | 517/517 passed |
| Ruff lint and format | passed |
| Python compilation | passed |
| Schema harness | passed |
| Repository policy | passed with zero violations |
| Strict JSON parse and formatting | passed |
| `git diff --check` | passed |
| Independent adversarial review | final pass; no P0 or P1 finding |
| Immutable implementation revision | `bc71dd5ebfdc636994a384a0a5dd2fd22184720d`, pushed to `origin/main` |
| GitHub Actions | [run 33286985057](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33286985057), success |
| Python 3.12 CI job | `99191772715`, success, `2026-08-30T02:01:20Z`–`02:01:44Z` |
| Python 3.10 CI job | `99191772864`, success, `2026-08-30T02:01:20Z`–`02:01:46Z` |

The workflow run was created and started at `2026-08-30T02:01:16Z`, reached
terminal success at `2026-08-30T02:01:47Z`, and passed both supported Python
jobs. These observed remote results close the Gate 1 implementation/CI evidence
boundary without expanding the contract's authority.

## The contract freezes syntax without claiming semantics

The contract binds four source layouts—`cam0`, `cam1`, `imu0`, and `mocap0`—as
policy strings only. The loader does not resolve or open those layout paths.
The `dso` prefix remains excluded, calibration access is `not_authorized`, and
real payload access is `not_authorized_by_contract`.

The common CSV grammar requires UTF-8 without BOM, LF-only records, a final LF,
comma delimiters, no quoting or escaping, no carriage returns, NUL bytes,
embedded newlines, blank rows, comment data rows, or field-whitespace
normalization. Headers are compared as exact raw cells.

Each accepted column has one exact source header, lexeme grammar, and
source-labelled output field. Every stream requires at least one data row.

| Stream shape | Frozen arity | Contract output boundary |
|---|---:|---|
| Camera index (`cam0`, `cam1`) | 2 | stream role, exact timestamp token value, and safe filename source lexeme |
| IMU row | 7 | timestamp plus six original numeric source lexemes |
| Source-labelled pose row | 8 | timestamp plus three position-labelled and four quaternion-labelled original numeric lexemes |

Timestamps are exact nonnegative integer lexemes bounded by signed-int64 maximum
and represented without rounding. Numeric sensor/reference tokens are preserved
as their original finite ASCII lexemes; the contract chooses no floating-point
conversion. Camera filenames must be safe ASCII basenames of the form
`<canonical nonnegative integer>.png`, with the stem equal to the row timestamp
and no duplicate filename.

The eight-column pose shape is named `TumviSourceLabeledPoseRow`. Its fields
preserve observed header labels only. The contract does not establish physical
units, coordinate frames, transform direction, quaternion normalization, or
ground-truth meaning. Reference role is unassigned. Velocity and IMU-bias fields
are absent and are not fabricated from the 17-column EuRoC full-state shape.

## Stereo, interval, and image decisions fail closed

The stereo policy requires exact camera-index byte identity, exact ordered
timestamp/filename rows, and one occurrence of every filename in each index.
It allows no monocular fallback. Full indexed-image existence must be proven
before any real execution, but it is not proven by this gate.

The prospective coverage interval is the closed intersection of
source-labelled timestamp-token ranges. Comparisons mean integer-token ordering
only and make **no clock-equivalence claim**. A camera token outside that
intersection is prospectively excluded without shift, clamp, extrapolation,
correction, or resampling, but that rule is non-executable here. The nominal IMU
window is `(previous_camera_timestamp,current_camera_timestamp]` and must be
nonempty, yet segment construction remains blocked.

The following decisions remain deliberately unset or prohibited:

- clock offset and camera, IMU, and pose maximum-gap thresholds are null;
- segment rule and minimum structural-segment length are null;
- pose-at-camera-time association and interpolation are blocked;
- quaternion norm, normalization, interpolation, and bracket policies are null;
- timestamp shift, clock correction, extrapolation, and resampling are false;
- full image existence, whole-file PNG validity, and decodability are false;
- decoder, decoded dtype, sample-range mapping, channel policy, normalization,
  and preprocessing are null; and
- authorized image bytes are zero.

The four prior 33-byte PNG IHDR observations—512x512, bit depth 16, and color
type 0—remain bound evidence only. They do not establish full-file validity,
decodability, channel semantics, pixel values, preprocessing, or the complete
image population.

## Loader trust boundary and failure behavior

The public API is intentionally limited to:

- `TumviAdapterContract`;
- `TumviAdapterContractError`; and
- `load_tumvi_adapter_contract(path, *, repo_root)`.

Construction is sealed to the strict loader. A successful return requires the
canonical contract path inside the exact Git worktree, a captured 40-character
`HEAD`, and regular single-link contract/evidence files whose worktree bytes
equal the blobs at that revision. The loader rechecks the revision and all
bytes before returning an immutable typed contract.

It fails closed on duplicate JSON keys; missing, extra, wrong-type, or
non-exact values; list-order changes; noncanonical evidence path values or
forbidden evidence paths; alternate contract locations; untracked or changed
contract/evidence bytes; hash
mismatch; symbolic or hard links; ancestor replacement; and `HEAD` movement.
Boolean fields cannot be smuggled through integer values, and public immutable
records reject forged authority/readiness mutations.

The loader reads only the contract and these six tracked evidence files:

| Evidence | Bound SHA-256 |
|---|---|
| [Candidate identity](../configs/data/tumvi_room4_512_16_candidate_v1.json) | `0de942674afcadd2f768385a82c52b8cb65eea14d5e8c4d17dc9e48262023740` |
| [Compatibility-slice receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json) | `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820` |
| [Format-inspection specification](../configs/data/tumvi_room4_512_16_format_inspection_v1.json) | `e8dd0bc98c7be85fed6d92d319bafec75c9f658584ea83d17ac93c6f47bdf1a7` |
| [Format-inspection receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json) | `30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846` |
| [Format-inspection report](tumvi-room4-512-16-format-inspection-2026-08-29.md) | `8048a399d611051e807c9824cdb141a5e6db1bcf77f9bd197483223fe887ef30` |
| [Rejected EuRoC adapter](../src/compact_vio/data/euroc.py) | `bfcddb06e7516d148253e8db38a7247ce51064ef13c28b934cdbb3980fc238fd` |

## Readiness remains uniformly false

The contract records `false` for real-payload execution authorization, adapter
implementation/readiness, calibration, clock mapping, pose semantics, ground
truth, PNG decoding, preprocessing, full image population, segment
construction, dataset selection, membership, and model access. Scientific
authority is `none`.

Therefore this gate establishes only that one exact policy record can be loaded
and defended. It establishes none of the following:

- acceptance of any real TUM-VI row or image;
- a shared physical clock or a valid synchronization correction;
- a calibrated camera/IMU/pose relationship;
- a usable pose reference or ground truth;
- image decoding or 16-bit preprocessing behavior;
- a replayable segment or canonical VIO sensor record;
- dataset quality, selection, source grouping, leakage review, or membership;
- model/checkpoint compatibility, training, inference, or evaluation; or
- publication, deployment, or UAV-domain authority.

## Immediate Gate 2 plan

Gate 2 may implement pure parsers against synthetic byte fixtures only:

1. accept exact synthetic camera-index, IMU, and eight-column source-labelled
   pose rows under the frozen lexical, arity, ordering, and resource limits;
2. emit only the frozen source-labelled record shapes, preserving original
   numeric lexemes and camera stream role;
3. reject BOM, CRLF, whitespace normalization, quotes, blank/comment/ragged
   rows, unsafe or duplicate filenames, timestamp disorder/duplicates,
   nonfinite or oversized tokens, resource overruns, and EuRoC full-state
   conflation;
4. prove that parser tests never open the ignored TUM-VI tree, calibration,
   images, learning code, or model paths; and
5. keep segment construction, pose association, decoding, preprocessing,
   readiness, and scientific authority unchanged and blocked.

Only after that synthetic gate passes may the project review whether a later
bounded real-payload read is necessary. Any such read requires its own exact
authorization. Minimal calibration metadata remains a still-later independent
gate and may be opened only if the reviewed dependency is explicit.

## Further questions

- Which pure parser API best exposes byte limits and fail-closed error locations
  without implying semantic conversion?
- Which adversarial fixtures are required to prove that exact TUM-VI
  source-labelled rows cannot be conflated with EuRoC full-state records?
- After synthetic parsing, what smallest real-payload read—if any—is necessary
  to evaluate the frozen grammar without broadening into calibration, image
  decoding, or adapter readiness?
