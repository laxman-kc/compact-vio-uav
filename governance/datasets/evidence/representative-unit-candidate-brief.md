# Representative dataset-unit candidate brief

Status: Historical candidate screening; EuRoC was selected on 2026-08-28
Access reviewed: 2026-08-28

## Authority boundary

This document preserves the candidate screening that preceded selection.
ADR-0004 is now `Accepted`, and EuRoC Vicon Room was selected and acquired for
the training-first development prototype. The authoritative archive identities,
split, modalities, rights statement, and execution record are the
[`euroc_vicon_v1.json`](../../../configs/data/euroc_vicon_v1.json) plan and the
[2026-08-28 acquisition evidence](euroc-vicon-acquisition-2026-08-28.md).
Other rows below remain candidate evidence only.

## Screening question

Which candidates warrant exact-unit review for these distinct future needs?

1. A small real-sensor integration unit with frame camera, IMU, calibration,
   timestamps, and ground truth suitable for the accepted endpoint.
2. Development-only evidence for the proposed degraded primary population.
3. Nominal guardrail or stress/discovery evidence without treating synthetic or
   handheld data as real-UAV confirmation.

These are screening roles, not approved project roles.

## Registered-candidate evidence matrix

| Candidate | Official-source evidence | Provisional review use | Blocking gaps |
|---|---|---|---|
| EuRoC MAV | Real MAV; stereo monochrome cameras at 20 Hz, IMU at 200 Hz, calibration, and Vicon-room 6-DoF ground truth. Official notes also describe synchronization limits and difficult motion/illumination. Archive rights label is `In Copyright - Non-Commercial Use Permitted`. | **Selected on 2026-08-28** for the compact learned VIO development prototype using `cam0`, `imu0`, and Vicon Room ground truth. | Publication-grade confirmation, broader datasets, and deployment evidence remain later work. Machine Hall Leica data is position-only and is not used as equivalent full 6-DoF evidence. |
| UZH-FPV | Real aggressive UAV flights with synchronized onboard frame-camera/IMU systems, calibration, sequence-level access, and public ground truth only for marked sequences. Dataset license is CC BY-NC-SA 3.0. | **Provisional high-motion stress review lead** after an exact public-GT unit is identified. | Exact sensor suite, public-GT sequence, post-2022 replacement-GT bytes/revision, hashes, clock alignment evidence, source group/split, and owner/rights approval. The pilot RGB camera is uncalibrated and unsynchronized; illumination is not a controlled conventional-frame factor. |
| TUM VI | Hardware-synchronized stereo/IMU, strong geometric/photometric/time calibration, CC BY 4.0. Room sequences have full-trajectory 6-DoF ground truth; low-light slides have only start/end ground truth. | Calibration/evaluator support candidate or nominal/stress evidence. | Handheld capture is not UAV-domain confirmation. Exact unit/variant, full-run GT requirement, size/hash, source group/split, and owner approval remain open. Low-light slides cannot silently become full-run trajectory evidence. |
| TartanAir V2 | Synthetic AirSim-rendered environments with image, pose, depth, flow, and generated IMU/perturbation tooling; CC BY 4.0. | Synthetic discovery or a later separately approved training lane. | Exact environment, trajectory, difficulty, camera/modalities, toolkit revision, version identity, byte sizes, checksums, source grouping, and owner approval. It cannot establish real-sensor timing, calibration, exposure, or noise robustness. |
| Blackbird UAV | Physical UAV trajectory/IMU/mocap with camera streams rendered afterward; high-speed and rendered-blur stress evidence. The corpus is multi-terabyte and some pre-rendered data is reported unavailable. | Potential hybrid physical/rendered stress source only. | **Hold:** the repository software license does not establish dataset-file rights; exact current archive access, unit, availability, size, checksums, and obligations are unresolved. Rendered imagery is not real-camera exposure/blur evidence. |
| Mid-Air | Synthetic drone data with RGB, IMU, ground truth, and climate/weather variants; CC BY-NC-SA 4.0. | Synthetic discovery/stress candidate. | Exact trajectory/condition/modalities, bytes/hashes, source grouping, and owner approval remain open. Variants of one underlying path must stay in one source group and cannot establish physical sensor/weather robustness. |

## Additional screening leads

The ETH Illumination-Robust Visual-Inertial Dataset is conceptually relevant to
rapid exposure change and low light, but it is not being added to the registry.
Its official landing page points to DOI `10.3929/ethz-b-000721641`; on the review
date, that DOI resolved to metadata for an unrelated thermal-infrared dataset.
No authenticated archive, dataset-file rights record, exact unit identity, or
complete ground-truth contract was established. It therefore remains on hold.

VIODE v3 has a current CC BY 4.0 Zenodo record and synthetic dynamic-object
variants, but it does not isolate the proposed blur/illumination phenomenon. It
is screened out as a non-candidate for this scope, so it is not being added to
the registry or assigned a role.

## Evidence-only review order

After the completed EuRoC development selection, later dataset expansion is:

1. Independently resolve one exact UZH-FPV public-GT unit for high-motion stress
   review, including the replacement-GT revision and hashes.
2. Screen an authenticated real-sensor illumination dataset only after its
   identity, rights, access, sensor contract, and full-run GT coverage are
   established.

Failure of any review stops that candidate; it does not authorize substituting
another dataset or changing the endpoint.

## Required approval record for any exact unit

Before acquisition, the future record must contain all fields required by the
[dataset governance policy](../policy.md), including:

- accepted research scope and intended evidence role;
- project-owner approval of the exact dataset, release, unit, modalities,
  source group, split membership, and acquisition location;
- separate dataset-file rights review, obligations, reviewer, and date;
- official source identity, exact files, compressed/expanded sizes, and
  checksum strategy;
- calibration, timestamps/clocks, frames/axes/units, sensor-suite consistency,
  ground-truth coverage/gaps, and endpoint suitability;
- leakage-safe grouping of every synchronized, rendered, corrupted, or derived
  variant sharing one physical acquisition or pose trace.

## Primary and official sources

- [EuRoC official dataset page](https://projects.asl.ethz.ch/datasets/euroc-mav/)
- [EuRoC official archive](https://doi.org/10.3929/ethz-b-000690084)
- [UZH-FPV official project page](https://fpv.ifi.uzh.ch/)
- [UZH-FPV sequence downloads](https://fpv.ifi.uzh.ch/datasets/)
- [TUM VI official dataset page](https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset)
- [TartanAir V2 official site](https://tartanair.org/)
- [TartanAir V2 modality documentation](https://tartanair.org/modalities.html)
- [Blackbird official repository](https://github.com/mit-aera/Blackbird-Dataset)
- [Blackbird repository software license](https://github.com/mit-aera/Blackbird-Dataset/blob/master/LICENSE.md)
- [Blackbird primary paper](https://doi.org/10.1177/0278364920908331)
- [Mid-Air official site](https://midair.ulg.ac.be/)
- [ETH illumination-dataset landing page](https://projects.asl.ethz.ch/datasets/ir-dataset/)
- [DataCite record currently returned by the ETH page's DOI](https://api.datacite.org/dois/10.3929/ethz-b-000721641)
- [VIODE official repository](https://github.com/kminoda/VIODE)
- [VIODE v3 Zenodo record](https://zenodo.org/records/4568610)
