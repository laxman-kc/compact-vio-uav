# Dataset archive acquisition records

Status: Operational transfer control

This directory holds immutable, machine-readable authorizations and receipts
for bounded dataset archive transfers. These records are separate from dataset
candidate records so that authorizing network I/O cannot silently select a
dataset or revise historical source evidence.

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

The `room4` transfer and structural-audit authorizations are based on the active
workspace user's instruction to continue the immediate production execution
plan. Each record
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
- `tumvi-room4-512-16-transfer-2026-08-29.receipt.json` — reserved success
  receipt path. It does not exist because every success gate did not pass.

The next operation is not authorized by any record in this directory. It
requires a separate reviewed, one-use authorization that binds an exact
allowlist of required regular files under `dataset-room4_512_16/mav0/`, excludes
the full `dso` tree and both symbolic links, and preserves per-file evidence.
Such extraction would remain operational preparation only; dataset selection,
membership, model/checkpoint access, training, inference, evaluation,
publication, and deletion stay outside its authority.
