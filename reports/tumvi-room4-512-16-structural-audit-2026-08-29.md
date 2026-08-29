# TUM VI room4 512x512 structural archive audit

Review date: 2026-08-29

Status: Completed operational header audit; strict extraction incompatible;
scientific authority none

## Technical summary

The one-use audit completed successfully against the exact retained TUM VI
`room4` 512x512 archive. It classified 4,485 TAR members as 4,472 regular
files, 11 directories, and two symbolic links. The links are confined to the
archive's DSO presentation tree and point toward the corresponding `mav0`
camera-data paths, but the controller did not follow them and this report does
not classify their targets as safe.

The archive remained exactly 1,356,206,080 bytes with SHA-256
`2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`.
The audit therefore resolved the earlier incomplete layout observation without
relaxing the existing security boundary: `strict_extraction_compatible` is
`false`, and the strict inventory/extractor still rejects this archive.

No download, archive modification, extraction, image decoding, dataset-sample
loading, checkpoint/model access, training, inference, evaluation, dataset
selection, publication, or deletion occurred. The next permitted design task
is a separate one-use authorization for an exact allowlist of required regular
files under `dataset-room4_512_16/mav0/` only. This audit receipt does not grant
that authority and does not select TUM VI for scientific use.

## Evidence identity

- Execution revision:
  `9709a101b28f291de23826ac8c9abec6a6eb9846`
- Pre-execution GitHub Actions:
  [run 33276534039](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33276534039),
  successful on Python 3.10 and 3.12
- [Structural-audit authorization](../governance/datasets/acquisitions/tumvi-room4-512-16-structural-audit-2026-08-29.authorization.json),
  SHA-256
  `cff468e9fd2702fb9c62176067e23db6a0d32b66502d5e92e37a42ea8324fbb8`
- [Tracked structural-audit receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-structural-audit-2026-08-29.receipt.json),
  3,273 bytes, SHA-256
  `1e3216a7bf789ef3a6d5425fa64f5a7cfa0a712c905460f5b444b65f5e323a92`
- [Source transfer failure](../governance/datasets/acquisitions/tumvi-room4-512-16-transfer-2026-08-29.failure.json),
  SHA-256
  `51979c3749e8a10187191ef43a355b72ebe456828d309703c22e0c6fccb0c75f`
- Retained archive: `data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar`,
  1,356,206,080 bytes, MD5 `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c`,
  SHA-256
  `2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`
- Ignored structural audit:
  `data/quarantine/tum-vi/room4-512-16/tar-structural-audit.json`, 744,267
  bytes, SHA-256
  `a75734de25567168eeb90a4b165361eb7df340ade2da5ed0382b6e9b228e6399`
- Consumed ignored claim:
  `data/quarantine/tum-vi/room4-512-16/structural-audit.claim.json`, SHA-256
  `c997ebdd4ff90aaee4044a17088c4de78ccf3dfa48c9089c300a01e70414a244`
- Execution window: started `2026-08-29T21:38:08Z`; receipt prepared
  `2026-08-29T21:38:14Z`; controller elapsed time
  `5.107158124999842` seconds
- Controller-initiated paid-service cost: USD `0`

The ignored archive, audit, and claim are local evidence. Their hashes bind
their observed bytes, but the tracked receipt and this report are not an
independent recovery copy of those ignored artifacts.

## Two inert links make strict extraction compatibility false

The audit cohort is every TAR member in the exact archive above. A member count
is a count of TAR headers, not a decoded sample count. Expanded bytes are the
sum of declared sizes for regular-file members; they are not extracted disk
usage or proof that member payloads are valid.

| TAR member class | Count | Interpretation |
|---|---:|---|
| Regular file | 4,472 | Eligible for consideration by a later exact allowlist; not currently authorized for extraction |
| Directory | 11 | Explicit directory headers only |
| Symbolic link | 2 | Recorded as inert metadata; never followed and never extractable by the strict policy |
| Total | 4,485 | All members classified within the authorized audit limits |
| Declared expanded regular-file bytes | 1,352,747,205 | Sum of regular-file header sizes; no extraction occurred |

The two non-regular members are:

| Member | Recorded target | Audit handling |
|---|---|---|
| `dataset-room4_512_16/dso/cam1/images` | `../../mav0/cam1/data` | Recorded only; not followed |
| `dataset-room4_512_16/dso/cam0/images` | `../../mav0/cam0/data` | Recorded only; not followed |

Any non-regular member makes the existing strict policy incompatible. The
negative compatibility result is therefore expected from the frozen rule and
is not evidence that the archive changed or that the audit failed.

## The recorded layout isolates a regular-file-only `mav0` boundary

Counts below include explicit directory headers. They describe archive
topology only and do not establish sensor, calibration, timing, or
ground-truth validity.

| Recorded subtree | Members | Observed structure |
|---|---:|---|
| Archive root | 1 | `dataset-room4_512_16/` directory header |
| `mav0` | 4,467 | One `mav0` directory plus the four child subtrees below |
| `mav0/cam0` | 2,231 | Branch and data directories plus 2,229 regular files |
| `mav0/cam1` | 2,231 | Branch and data directories plus 2,229 regular files |
| `mav0/imu0` | 2 | Branch directory plus one regular file |
| `mav0/mocap0` | 2 | Branch directory plus one regular file |
| `dso` | 17 | Three directory headers including the `dso` root, 12 regular files, and the two symbolic links |

The `mav0` and `dso` rows plus the root row partition all 4,485 members. The
child rows under `mav0` partition its contents after the single `mav0`
directory header. This structure supports designing a narrow allowlist; it does
not itself decide which `mav0` files are scientifically required.

## Method preserved the archive and separated authority

The controller loaded the committed authorization without touching the
archive, verified the clean execution revision and exact tracked source hashes,
checked the active one-use window, destination boundaries, capacity, and
output absence, and then wrote an exclusive ignored claim. It verified the
archive's size, published MD5, and received SHA-256 before invoking the inert
TAR-header audit.

The audit preserved canonical path, topology, member-count, expanded-size, and
serialized-output limits. It classified link metadata but invoked no
extraction and decoded no member. Before writing the receipt last, the
controller reverified the archive identity, audit identity, claim identity,
tracked inputs, repository revision, elapsed-time bound, and retained-capacity
gate. The receipt records outcome `completed` and scientific authority `none`.

The completed operation set was limited to claim writing, size/MD5/SHA-256
verification, TAR-header audit, audit writing, and receipt writing. The receipt
explicitly records that download, archive modification, extraction, image
decoding, dataset-sample loading, dataset selection, training, inference,
evaluation, checkpoint loading, and archive deletion were not performed.

## Limitations remain decision-relevant

- Header classification does not prove that PNGs decode, preserve the expected
  16-bit signal, or share valid timestamps with IMU and reference records.
- No calibration file, ground-truth record, sensor sample, or image payload was
  parsed or semantically validated.
- The relative link targets were recorded, not resolved or certified. A later
  extractor must exclude links entirely rather than follow them.
- The local ignored audit is not an independently durable evidence copy. The
  tracked receipt retains its identity and summary, not its full member list.
- TUM VI remains a handheld-room scientific candidate with unresolved project
  role and source membership. This audit provides no UAV-domain evidence.
- No scientific comparison, model result, baseline, threshold, uncertainty
  estimate, or quality metric was produced by this operation.

## Next controlled step

The next implementation slice is a separately reviewed and committed
regular-file extraction contract and one-use authorization. It must:

1. Bind the exact archive, audit, receipt, code, destination, validity window,
   capacity, time, cost, and output limits.
2. Declare every required member under
   `dataset-room4_512_16/mav0/` by exact path and expected regular-file kind;
   the audit does not justify assuming that every `mav0` member is required.
3. Exclude the complete `dso` tree, both symbolic links, and every non-regular
   member without resolving or following link targets.
4. Preserve per-file hashes and sizes, validate the staged output, and publish
   atomically without mutating or deleting the retained archive or audit
   evidence.
5. Keep download, model/checkpoint access, training, inference, evaluation,
   dataset selection/membership, publication, and deletion prohibited.

Only after that bounded extraction may separate format, 16-bit preprocessing,
timestamp, calibration, ground-truth, and adapter compatibility checks run.
Those checks still cannot select the dataset. Scientific selection, leakage
review, membership freeze, and the complete full-pose evaluation protocol must
precede any model or evaluation access.

## Further questions

- Which exact regular `mav0` members are necessary for the smallest
  compatibility check, and what semantic validator will define success?
- Does the extracted camera/IMU/MoCap content satisfy the project's explicit
  clocks, frames, units, transform direction, 16-bit preprocessing, and
  reference-capability contracts?
- Where will the ignored full audit and retained archive receive independent
  recovery copies if they become required scientific evidence?

Until those questions are answered through their own reviewed gates, the only
supported conclusion is structural: the exact archive was preserved and fully
classified at the TAR-header level, contains two inert symlinks, and is not
compatible with the existing strict whole-archive extraction policy.
