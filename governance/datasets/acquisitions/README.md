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

The current `room4` authorization is based on the active workspace user's
instruction to continue the immediate production execution plan. The record
states that the user's identity was not independently authenticated; it must
not be presented as independent identity assurance or third-party approval.

Current records:

- `tumvi-room4-512-16-transfer-2026-08-29.authorization.json` — one bounded TUM
  VI `room4` 512x512 archive transfer and read-only inventory. Its one execution
  retained verified archive bytes but failed strict inventory; it is consumed.
- `tumvi-room4-512-16-transfer-2026-08-29.failure.json` — post-failure local
  audit binding the claim, retained archive identity, exact rejected symlink,
  absent inventory/receipt, and no-retry/no-scientific-authority boundary.
- `tumvi-room4-512-16-transfer-2026-08-29.receipt.json` — reserved success
  receipt path. It does not exist because every success gate did not pass.
