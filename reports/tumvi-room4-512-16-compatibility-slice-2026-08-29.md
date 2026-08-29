# TUM VI room4 512x512 audit-bound regular-file compatibility slice

Review date: 2026-08-29

Status: Completed operational eight-file extraction; payload uninterpreted;
scientific authority none

## Technical summary

The one-use regular-slice controller completed successfully against the exact
retained TUM VI `room4` 512x512 archive. It compared all 4,485 live TAR headers,
in order, with the completed structural audit and copied only eight explicitly
allowlisted regular members under `dataset-room4_512_16/mav0/`. The published
tree contains four CSV member byte streams and two common PNG basenames from
each camera, totaling 5,043,300 bytes.

The controller followed no link, copied no `dso` or unlisted member, invoked no
TAR extraction API, and did not modify the 1,356,206,080-byte source archive.
It published a new exact output tree without replacement and wrote its receipt
last. The receipt has SHA-256
`a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`.

The phrase “compatibility slice” names the bounded operational input. It is not
a finding that the payloads are compatible with a project adapter. No CSV was
parsed, no PNG was decoded, no timestamp or synchronization relationship was
validated, and no calibration, ground-truth, preprocessing, dataset-membership,
or scientific-selection decision was made. No model or checkpoint was loaded;
no training, inference, or evaluation occurred.

## Evidence identity and CI gates

- Implementation commit:
  `9ca97e04848fe08d14841470a7a7bf39b5edd725`
- Implementation GitHub Actions:
  [run 33279450649](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33279450649),
  successful on the Python 3.10 and 3.12 matrix. Earlier run `33279337811`
  failed only a Python 3.10 test-mock isolation defect and was superseded by
  the green implementation run; no real extraction used the failed revision.
- Authorization and execution revision:
  `cfe863890ad040684ac837c1b5d7f346bc0159cc`
- Pre-execution GitHub Actions:
  [run 33279713875](https://github.com/laxman-kc/compact-vio-uav/actions/runs/33279713875),
  successful before the one-use claim was created
- [Authorization](../governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.authorization.json),
  SHA-256
  `f39ba7598eac1a0301ced5b13d835231c79757b26e096219145737a139f79e81`
- [Exact allowlist](../configs/data/tumvi_room4_512_16_compatibility_slice_v1.json),
  SHA-256
  `db8a24c18a62bb0e74140a20799d1e7414c34c5bbc75f284ec907736ae2dacd0`
- [Completed receipt](../governance/datasets/acquisitions/tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json),
  7,106 bytes, SHA-256
  `a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820`
- Consumed ignored claim:
  `data/quarantine/tum-vi/room4-512-16/compatibility-slice.claim.json`, 692
  bytes, SHA-256
  `8e4e8a8ad8c58c96e10535600caacaed51776c173c3b6babec557c3f973c4271`
- Ignored destination:
  `data/quarantine/tum-vi/room4-512-16/tumvi-room4-512-16-compatibility-slice-v1`
- Retained archive:
  `data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar`,
  1,356,206,080 bytes, MD5 `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c`,
  SHA-256
  `2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68`

The execution receipt binds the complete upstream chain: candidate SHA-256
`0de942674afcadd2f768385a82c52b8cb65eea14d5e8c4d17dc9e48262023740`,
transfer authorization SHA-256
`fb2108f7d1bb6bbf317bd8693c80cb55a5162f0ca297c562c7e89ccd460dbf19`,
transfer claim SHA-256
`1c6b9d54e763a9ec2c899461e7701f8652f550bf9a19bb03367b1555edc3abc0`,
transfer-failure SHA-256
`51979c3749e8a10187191ef43a355b72ebe456828d309703c22e0c6fccb0c75f`,
structural-audit authorization SHA-256
`cff468e9fd2702fb9c62176067e23db6a0d32b66502d5e92e37a42ea8324fbb8`,
structural-audit claim SHA-256
`c997ebdd4ff90aaee4044a17088c4de78ccf3dfa48c9089c300a01e70414a244`,
structural-audit SHA-256
`a75734de25567168eeb90a4b165361eb7df340ade2da5ed0382b6e9b228e6399`,
and structural-audit receipt SHA-256
`1e3216a7bf789ef3a6d5425fa64f5a7cfa0a712c905460f5b444b65f5e323a92`.

The ignored claim, archive, audit, and output tree are local evidence. Their
recorded hashes do not create an independent recovery copy. The receipt and
this report retain identities and summaries, not the ignored payload bytes.

## Execution timing, capacity, and cost

| Observation | Exact value |
|---|---:|
| Claim prepared | `2026-08-29T22:55:17Z` |
| Controller started | `2026-08-29T22:55:17Z` |
| Receipt prepared | `2026-08-29T22:55:25Z` |
| Controller elapsed time | `8.26419195800554` seconds |
| Maximum authorized elapsed time | 3,600 seconds |
| Initial free bytes | 94,954,934,272 |
| Free bytes before receipt | 94,949,638,144 |
| Authorized minimum free bytes | 2,154,624,100 |
| Retained post-slice reserve | 2,147,483,648 bytes |
| Maximum claim bytes | 1,048,576 |
| Maximum receipt bytes | 1,048,576 |
| Selected expanded bytes | 5,043,300 |
| Controller-initiated paid-service cost | USD 0 |
| Retention review | `2026-09-06T22:49:00Z` |

The minimum-free-space value is the exact sum of the selected-byte bound, claim
bound, receipt bound, and 2 GiB retained reserve. Capacity was checked before
the claim and again before receipt publication.

## Exact published tree

The receipt records these files in allowlist order:

| Regular member | Bytes | SHA-256 |
|---|---:|---|
| `dataset-room4_512_16/mav0/cam0/data.csv` | 98,057 | `feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67` |
| `dataset-room4_512_16/mav0/cam1/data.csv` | 98,057 | `feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67` |
| `dataset-room4_512_16/mav0/imu0/data.csv` | 2,232,296 | `4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be` |
| `dataset-room4_512_16/mav0/mocap0/data.csv` | 1,481,244 | `073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a` |
| `dataset-room4_512_16/mav0/cam0/data/1520531124150444163.png` | 284,188 | `1c8371dd64a55790c561f98611f132a645a1944291da63f18c054263ed0c5963` |
| `dataset-room4_512_16/mav0/cam1/data/1520531124150444163.png` | 283,001 | `e5a853fc43776237e9536e90443fdbd2ae3f8349c6385cbea77133c66542be1f` |
| `dataset-room4_512_16/mav0/cam0/data/1520531124200446163.png` | 283,946 | `77f022fd752680fde1ad52d3347eb0c7548f7939ecd3742bc7be807984c38c65` |
| `dataset-room4_512_16/mav0/cam1/data/1520531124200446163.png` | 282,511 | `cb616c08af29f4a413577fc00ad189fc029597800cdead394435ef52ebf1dc42` |
| **Total** | **5,043,300** | **8 independently hashed files** |

The four CSV paths are exact audited regular members. The two PNG basenames are
the lexicographically earliest two filenames in the exact intersection of
audited regular-image paths under `cam0/data` and `cam1/data`. That deterministic
engineering rule is not a scientific sampling rule and does not establish CSV
timestamp membership or camera synchronization.

At `2026-08-29T22:57:26Z`, a separate read-only raw-byte walk reconfirmed:

- exactly eight directories below the destination root;
- exactly eight regular files and 5,043,300 total bytes;
- link count one for every file;
- no symbolic link or other special file; and
- exact agreement with every receipt-recorded path, size, and SHA-256.

The verification hashed opaque bytes only. It did not parse CSV content, decode
PNG content, load samples, or infer semantic relationships. A second read-only
check completed by `2026-08-29T22:58:36Z` and reconfirmed the retained archive's
size, MD5, and SHA-256 shown above. Independent post-run review found no
P0, P1, or P2 issue in the receipt or published tree.

## Operational method and truth gates

Before creating its one-use claim, the controller required an active exact
authorization, clean execution revision, exact tracked tool/source hashes,
ignored immutable-source paths, absent outputs, sufficient capacity, and the
full elapsed-time window remaining. After the claim, it verified the complete
source-evidence chain and retained archive identity.

The extraction primitive first recomputed the full structural audit and
required exact ordered equality with the bound 4,485-member record. During the
copy pass it revalidated every header's canonical path, kind, declared size,
and link target. It opened payload streams only for the eight selected regular
members, copied them into an identity-bound staging directory, hashed each
copy, required the exact expected directory/file tree, rehashed the archive,
and published the directory atomically without replacement.

Before and across receipt publication, the controller revalidated the clean
revision or exact permitted new-receipt Git state, tracked and ignored source
bytes, claim, archive, capacity, authorization window, elapsed deadline, and
the identity-bound published tree. The receipt records outcome `completed` and
scientific authority `none`.

## Deliberately unperformed operations

The completed operation did not:

- download or modify the source archive;
- follow links, copy the `dso` tree, or copy any unlisted member;
- invoke `tarfile.extract` or `tarfile.extractall`;
- parse sensor CSVs, decode PNGs, or load dataset samples;
- assign protocol membership or select TUM VI for scientific use;
- load a model or checkpoint, train, infer, or evaluate;
- publish a scientific result; or
- delete the archive, audit, claim, slice, or other source evidence.

## Limitations remain decision-relevant

- A matching path, size, and SHA-256 proves byte identity only. It does not
  establish payload validity or suitability for any adapter.
- The CSV members have not been parsed. Their columns, timestamps, units,
  frames, ordering, membership relationships, and calibration/reference
  semantics remain unverified.
- The PNG members have not been decoded. Bit depth, dimensions, preprocessing,
  timestamp correspondence, and camera synchronization remain unverified.
- The `mocap0` file is an uninterpreted reference-metadata candidate, not an
  accepted ground-truth endpoint.
- The deterministic two-name intersection is an engineering smoke boundary,
  not a representative sample, scientific unit selection, or leakage review.
- The local ignored output has no independent recovery copy recorded here.
- TUM VI remains a handheld-room candidate with unresolved project role and
  source membership; this slice supplies no UAV-domain or model-quality
  evidence.

## Next controlled evidence boundary

Any semantic compatibility check must have its own reviewed scope before it
opens these payloads. That scope must state the exact files and read operations,
expected schemas and units, timestamp/synchronization rules, image-format and
preprocessing expectations, calibration/reference contracts, output evidence,
failure behavior, and prohibited model/scientific operations. It must not infer
dataset selection from this completed extraction.

Only after sufficient independent compatibility evidence exists may a separate
unit-selection decision accept or reject TUM VI `room4`. Source grouping,
leakage review, membership role, and a full-pose evaluation protocol still must
be frozen before any model/checkpoint access, inference, training, or
evaluation.
