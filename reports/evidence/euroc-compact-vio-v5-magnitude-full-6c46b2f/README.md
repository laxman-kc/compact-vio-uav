# V5 governed-run evidence mirror

This directory commits selected small immutable records from the governed
wrapper for run `euroc-compact-vio-v5-magnitude-full-6c46b2f`.

- `run-manifest.json` SHA-256:
  `aeeb4f573d7dcf590f4f0aaf3fd49e922498ec5e2c465fd87e7c00aabf272af4`
- outer `artifact-manifest.json` SHA-256:
  `548fd52ffd0d89e4a7d347c78a8e9c4ba799c84dd74f7e0a6f3a365f0ba3b91e`
- `environment.json` SHA-256:
  `12a280c9dd1759d20a41e93f06a0935e7f62f7ecee8cc08d3f7e3f5056fbfc11`
- canonical `resolved-config.json` SHA-256:
  `228e48f0cce2882a7f4b066bb6eda0293d6cd5a4a7dfd478c4cbaf7413aebd93`
- checked-in source training configuration SHA-256 retained by the trainer
  summary:
  `7f5e50785ed1907c26f5bbea6766a4fc13fd3df591c8930ef8b15ac9f7d71af0`
- resolved evaluation configuration SHA-256:
  `ea3589b4434f35a1ce9306e9d43818b95bf8e174a74eaed9a69fcc45ac4edacd`
- preserved inner trainer-output manifest SHA-256:
  `9628a7b93da229700b07aa9bb43c07e8b31f68bd4e9ee764b4d7ad06ac63b2f9`

The complete canonical governed-v2 wrapper, including the checkpoint,
predictions, metrics, summary, and history listed by the outer artifact
manifest, is retained outside Git only at the ignored local path recorded in
the reviewed result report. It has not been copied to or verified on the
worker. The original trainer bundle remains verified at its separate worker
and local paths. This Git directory is an intentionally incomplete small-record
mirror, not a complete restorable bundle; running the bundle verifier here is
expected to report the omitted acquisition record and large payloads. The
complete local wrapper validates with `ok: true`: 14 payload files totaling
37,075,047 bytes, 13 declared artifacts, and five nested trainer payloads.

The wrapper repairs the missing run-manifest/configuration/environment metadata
without mutating the original trainer-output manifest. It does not satisfy the
still-unresolved independent artifact-vault, backup, or restore gate.
