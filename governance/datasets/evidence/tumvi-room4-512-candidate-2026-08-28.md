# TUM VI `room4` 512x512 candidate evidence — 2026-08-28

Status: Candidate evidence only; not selected, approved, acquired, or executable  
Decision authority: None  
Proposed lane: External full-pose generalization candidate only  
Identity state: `published_identity_only`

## Candidate identity

- Dataset: TUM Visual-Inertial Dataset (TUM VI).
- Publisher: Technical University of Munich Computer Vision Group.
- Candidate sequence: `room4`.
- Candidate distribution: official EuRoC/DSO 512x512, 16-bit export.
- Candidate archive: `dataset-room4_512_16.tar`.
- Official landing page:
  [TUM VI Visual-Inertial Dataset](https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset).
- Official download directory:
  [EuRoC/DSO 512x512 exports](https://vision.in.tum.de/tumvi/exported/euroc/512_16/).
- Benchmark publication DOI:
  [`10.1109/IROS.2018.8593419`](https://doi.org/10.1109/IROS.2018.8593419).
  This DOI identifies the benchmark paper, not a dataset deposit or archive.

The exact machine-readable candidate record is
[`configs/data/tumvi_room4_512_16_candidate_v1.json`](../../../configs/data/tumvi_room4_512_16_candidate_v1.json).
It has no acquisition or evaluation authority. A strict exact-field loader and
focused tests now validate its unresolved state. Loading the record does not
approve acquisition, selection, extraction, inference, or evaluation; a
separate bounded operational authorization remains required before transfer.

## Officially published capabilities

The official dataset page describes a rigid, hardware-synchronized sensor rig
with two monochrome cameras in stereo and one IMU. It reports camera capture at
20 Hz, three-axis accelerometer and gyroscope measurements at 200 Hz, 16-bit
linear-response images, and provided geometric and photometric calibration.
It also states that processed sequences have consistent camera/IMU/ground-truth
timestamps, corrected IMU scale and axes, and ground-truth poses expressed in
the IMU frame.

For the `room` class specifically, the official page says MoCap ground-truth
poses cover the entire trajectory. That makes `room4` worth screening for a
full-pose evaluator. It does not prove that the current project adapter can
parse the archive or that the reference representation matches the project's
unfrozen full-pose protocol.

## Archive identity and response observation

No archive content was downloaded in this slice. Read-only HTTP `HEAD`
observations on 2026-08-28 produced:

| Observation | Value |
|---|---|
| Official request URL | `https://cdn3.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar` |
| Request response | `302 Found` at `2026-08-28T14:05:09Z` |
| Observed redirect target | `https://cdn2.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar` |
| Redirected response | `200 OK` at `2026-08-28T14:05:19Z` |
| Observed `Content-Length` | `1,356,206,080` bytes |
| `Last-Modified` | `Tue, 17 Apr 2018 22:54:49 GMT` |
| Locally computed SHA-256 | Unresolved; no bytes were acquired |

The archive redirect policy is closed to the exact observed final URL above and
the `https://cdn2.vision.in.tum.de` origin. No other redirect target or origin is
implicitly allowed.

The official MD5 sidecar was fetched separately as small identity metadata; no
archive content was fetched. Its machine-observed provenance is:

| Observation | Value |
|---|---|
| Official sidecar request URL | `https://cdn3.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar.md5` |
| Method and request response | `GET`; `302 Found` at `2026-08-28T14:11:43Z` |
| Allowed and observed final URL | `https://cdn2.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar.md5` |
| Allowed redirect origin | `https://cdn2.vision.in.tum.de` |
| Redirected response | `200 OK` at `2026-08-28T14:11:44Z` |
| Observed `Content-Length` | `59` bytes |
| `Last-Modified` | `Tue, 17 Apr 2018 22:54:52 GMT` |
| Exact body | ASCII `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c  dataset-room4_512_16.tar` followed by one LF byte (`0x0a`) |
| Parsed published MD5 | `8e2ec2c35ee40a54c9aaa5bc2b3c9d8c` |

The observed archive headers and exact sidecar identify only published source
metadata. They do not prove possession, content integrity, safe extraction, or
adapter compatibility. Any later separately approved acquisition must verify
the exact received byte count and MD5, compute SHA-256 over those bytes, and
retain the closed redirect chain as provenance.

## Rights boundary

The official dataset page licenses all Visual-Inertial Dataset data under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and accompanying
source code under the
[BSD 2-Clause License](https://opensource.org/license/bsd-2-clause). The data
and code licences are distinct. This record does not decide downstream model,
checkpoint, report, or redistribution terms; those require the applicable
release review and attribution record.

## Intended scientific boundary

If separately selected and approved later, this unit may serve only as an
external full-pose generalization evaluation candidate. TUM VI `room4` is a
handheld indoor room capture, not UAV-domain confirmation. A successful result
could not establish aerial-motion robustness, physical UAV sensor equivalence,
onboard performance, deployment fitness, flight safety, or publishable
superiority by itself.

## Unresolved mandatory gates

The following remain unresolved. They block progress at their applicable gate;
received-byte evidence is created only after a separately authorized bounded
acquisition and therefore is not presented as a prerequisite for that transfer:

- Project-owner authorization for any bounded acquisition, and later separate
  evaluation-unit selection/approval and exact sequence membership role.
- Received-archive SHA-256, safe TAR layout, expanded size, and retained raw
  manifest.
- Exact camera/IMU/calibration files, their hashes, and compatibility with the
  project sensor/frame/clock contract.
- Exact ground-truth file schema, pose convention, timestamp coverage, units,
  association behavior, and parser compatibility.
- The 16-bit image decoding and preprocessing policy; no 8-bit conversion,
  normalization, rectification, or camera selection is chosen here.
- Source-group identity, leakage review, and separation from development or
  later confirmatory membership.
- Candidate/control checkpoints, native classical backend, fairness contract,
  ATE/RPE/rotation/drift definitions, coverage/failure rules, resource scope,
  primary metric, thresholds, tie handling, and stop rule.

There was no dataset selection, acquisition, extraction, inference, training,
evaluation, threshold choice, or architecture change in this evidence slice.
