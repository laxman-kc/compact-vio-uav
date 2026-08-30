# Dataset archive acquisition records

Status: Operational dataset-evidence control

This directory holds immutable, machine-readable authorizations, retained
claims, and receipts for bounded dataset archive transfers and later local
evidence inspections. These records are separate from dataset candidate records
so that authorizing network I/O or bounded payload observation cannot silently
select a dataset or revise historical source evidence.

An authorization is executable only when the controller validates all of its
closed fields and runtime gates. The current contract requires one execution,
an exact 24-hour validity window, a clean Git worktree, byte-for-byte agreement
between the tracked `HEAD` versions and the declared candidate/controller/tool
SHA-256 values, absent destination and partial files, an ignored quarantine
destination, sufficient capacity for the archive and bounded evidence plus a
2 GiB retained reserve, zero paid-compute cost, and explicit TAR-inventory
limits.

The controller creates an exclusive ignored claim before network access. That
claim consumes the authorization even if the transfer or inventory later
fails; removing it or retrying requires separate authority. On success, the
controller verifies the received byte count and published MD5, computes
SHA-256, performs a read-only hostile-member-checked TAR inventory, writes the
ignored inventory, and writes the tracked receipt last. It never extracts the
archive.

Operational transfer authority is deliberately not scientific authority. It
does not select a dataset, assign split membership, approve extraction,
decode/load samples, load a checkpoint, train, infer, evaluate, publish, or
delete the archive. A success receipt proves only the exact transfer and
read-only inventory facts it records. Later use remains gated by independent
calibration, schema, preprocessing, adapter, leakage, membership, and frozen
evaluation-protocol review.

The filesystem controls assume the repository and its owner-only quarantine
directories are not being actively modified by another process running as the
same operating-system user. The controller rejects symlink ancestry and
rechecks evidence before its receipt, but path-based operations are not a
defense against a hostile same-user process racing directory entries. Failed
claims and inventories are ignored local evidence; they are not remotely
durable until separately reviewed and retained.

The Gate 3B real-CSV grammar-probe controller uses a narrower tracked-output
contract: its exact claim path is trackable and retained whether the operation
completes or fails after claim publication. It publishes that claim before the
first payload descriptor open. A post-claim operational failure produces no
canonical receipt and permits no retry. A completed grammar acceptance or
rejection produces only an aggregate tracked receipt and grants no scientific
or readiness authority.

The `room4` transfer, structural-audit, compatibility-slice, and
format-inspection authorizations are based on the active workspace user's
instruction to continue the immediate production execution plan. Each record
states that the user's identity was not independently authenticated; it must
not be presented as independent identity assurance or third-party approval.

Current records:

- `tumvi-room4-512-16-transfer-2026-08-29.authorization.json` — one bounded TUM
  VI `room4` 512x512 archive transfer and read-only inventory. Its one execution
  retained verified archive bytes but failed strict inventory; it is consumed.
- `tumvi-room4-512-16-transfer-2026-08-29.failure.json` — post-failure local
  audit binding the claim, retained archive identity, exact rejected symlink,
  absent inventory/receipt, and no-retry/no-scientific-authority boundary.
- `tumvi-room4-512-16-structural-audit-2026-08-29.authorization.json` — one
  header-only audit of the exact retained archive. Its one execution completed
  after the authorization revision passed CI, classified 4,485 members without
  following links, extracting members, or decoding payloads, and consumed the
  authorization.
- `tumvi-room4-512-16-structural-audit-2026-08-29.receipt.json` — tracked
  completed-audit receipt. It binds the unchanged archive SHA-256, ignored audit
  and claim identities, 4,472 regular files, 11 directories, two symbolic
  links, `strict_extraction_compatible: false`, zero paid-service cost, and
  `scientific_authority: none`.
- `tumvi-room4-512-16-compatibility-slice-2026-08-29.authorization.json` — one
  bounded extraction of the exact eight regular `mav0` members in the checked
  compatibility allowlist. Its revision passed CI, its one execution completed,
  and the authorization is consumed.
- `tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json` — tracked
  completed-slice receipt. It binds execution revision
  `cfe863890ad040684ac837c1b5d7f346bc0159cc`, the unchanged archive and source
  evidence, consumed claim, exact eight-file output tree, 5,043,300 selected
  bytes, per-file SHA-256 values, bounded capacity/time, zero paid-service cost,
  and `scientific_authority: none`. Its own SHA-256 is
  `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`.
- `tumvi-room4-512-16-format-inspection-2026-08-29.authorization.json` — one
  bounded observation of the exact compatibility slice: four streamed CSV
  structures and exactly 33 interpreted bytes from each of four PNG files.
  Implementation revision `b83eebf3cc24cfada57d2d76da4a19672ef8267a`
  passed GitHub Actions run `33282946955`; authorization revision
  `7dfe85b8c7a3de04a1c789a79a139fa90ad5d5a4` passed run `33283206142`
  before execution. Its SHA-256 is
  `be49077af024e301dcada292384d19309adb8d5d08ea3ae4bb62be7c86a25d9f`.
- `tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json` — tracked
  completed-inspection receipt with SHA-256
  `30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846`.
  It records `format_comparison_outcome: does_not_conform`: the current EuRoC
  adapter's 17-column full-state reference targets do not match the observed
  eight-column mocap header, and the first selected camera timestamp is outside
  the observed IMU and mocap intervals. Adapter, calibration, and ground-truth
  readiness are false; scientific authority is none.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.authorization.json` —
  first reviewed one-use aggregate grammar-probe authorization, SHA-256
  `9893cc16ce13db037d3179487c9bb37d93ffb0dc068d7b86bdd1480a36b84ef0`.
  Its revision `4390ada9d9f138220fb528162b1a1ecf6e37fb6f` passed GitHub
  Actions run `33296869742`. It is consumed and cannot be retried.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.claim.json` —
  retained 1,012-byte incident claim, SHA-256
  `f63263fd0b9f086075b7002c4b4e5dd2ca30112587a7c1b31966e9557afae490`,
  published at `2026-08-30T06:26:18Z`. An auditor preflight had replaced the
  complete source binder with a mock that raised at entry, so the binder body
  and all four payload descriptor opens were never reached. This
  zero-descriptor fact is auditor-observed runtime evidence; the durable record
  itself states payload access had not started at claim publication.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.receipt.json` —
  reserved incident receipt path. It does not exist. The claim remains, the
  authorization is consumed, no grammar result was produced, and no retry is
  permitted.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.authorization.json` —
  separate superseding one-use authorization, SHA-256
  `5f566515e723a0e51abd09b75cd43b68d6aa61807749d5069a49427aa218126f`.
  Recovery revision `abd7af3d77c12637144b324465ab462752629872` passed run
  `33297224165`; authorization-only execution revision
  `47daabc1891b71e53a6d3f4f5a070d69bbbe5c78` passed run `33297367015`
  before executing once.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.claim.json` —
  1,012-byte canonical durable claim, SHA-256
  `beba4617be76bf63870ff0957c0d4b187abe2caf7fcc6f0b336bf2b6fcc53403`,
  prepared at `2026-08-30T06:39:58Z` before the first payload descriptor open.
- `tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.receipt.json` —
  8,259-byte canonical aggregate receipt, SHA-256
  `7ea8720fc013504de8db22396a5eb4d8bf8f25f33cd00ab2e6798bd42d42c958`.
  Its checked outcome is `completed` / `rejects_frozen_gate1_grammar`: both
  camera indexes and IMU accepted; pose rejected at exact-header mismatch on
  physical line 1. All readiness fields are false and scientific authority is
  none.
- `tumvi-room4-512-16-transfer-2026-08-29.receipt.json` — reserved success
  receipt path. It does not exist because every success gate did not pass.

The exact eight-file compatibility-slice controller is committed and CI-green.
The reviewed one-use authorization revision passed GitHub Actions run
`33279713875` and executed once. The slice is restricted to regular files under
`dataset-room4_512_16/mav0/`, excludes the full `dso` tree and both symbolic
links, and preserves per-file evidence. A post-run raw-byte walk observed eight
directories below the destination, eight single-link regular files, no special
files, and exact agreement with the receipt. The ignored claim and output tree
remain local evidence rather than an independent recovery copy. The completed
slice remains operational preparation only; CSV parsing, PNG decoding, payload
interpretation, format/calibration/ground-truth or adapter acceptance, dataset
selection, membership, model/checkpoint access, training, inference,
evaluation, publication, and source deletion stay outside its authority.

The format inspection is consumed and completed, not failed. Its negative
comparison forbids reuse of the EuRoC adapter and did not authorize a repair,
broader payload access, or model work. Subsequent Gate 1 and Gate 2 work froze a
TUM-VI-specific grammar/output contract and synthetic-only parsers. Gate 3B then
completed one separately authorized aggregate real-CSV grammar observation
after retaining the earlier zero-payload consumed attempt. The checked receipt
rejects the frozen Gate 1 grammar solely at the pose exact-header gate; it does
not persist or emit the observed header or any source row contents or lexemes.

The next safe boundary is a separate reviewed contract-mismatch reconciliation
decision. It may leave the grammar unchanged and stop the TUM-VI candidate
lane. Any additional source observation requires a new one-use authorization
that is independently reviewed, committed, pushed, and CI-green; neither
consumed authorization may be retried. Adapter implementation/readiness,
calibration, clock/pose semantics, image decoding, segment construction,
dataset selection, membership, leakage review, protocol freeze, checkpoint
access, training, inference, and evaluation remain separate closed gates.
