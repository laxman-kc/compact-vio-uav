# Representative dataset-unit candidate brief

Status: Official-source evidence for later owner review; non-authoritative  
Access reviewed: 2026-08-27

## Authority boundary

This brief narrows later review work. It does not approve a dataset, release,
sequence, modality, project role, split, acquisition location, download,
training use, or final-test use. ADR-0004 remains `Proposed`; M6 remains
blocked until the research scope is accepted and the project owner separately
approves one exact dataset scope after a dataset-file rights review.

No dataset bytes were downloaded or integrity-tested for this brief.
"Reachable" below means that an official landing or listing page was reachable
on the review date.

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
| EuRoC MAV | Real MAV; stereo monochrome cameras at 20 Hz, IMU at 200 Hz, calibration, and Vicon-room 6-DoF ground truth. Official notes also describe synchronization limits and difficult motion/illumination. Archive rights label is `In Copyright - Non-Commercial Use Permitted`. | **Provisional technical review lead** for one small real-MAV integration unit. This is not a selection. | Exact release/archive object, Vicon sequence, files/modalities, byte sizes, SHA-256, source group/split, GT synchronization assessment, acquisition location, owner approval, and separate rights review. Machine Hall Leica data is position-only and must not be treated as equivalent to full 6-DoF Vicon ground truth. |
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

If ADR-0004 is accepted without a material change to its target phenomenon,
perform these later reviews as separate slices:

1. Resolve one exact EuRoC Vicon-room unit for technical integration review,
   including archive identity, files, sizes, SHA-256 plan, GT suitability,
   source group, split, acquisition location, owner approval, and rights review.
2. Independently resolve one exact UZH-FPV public-GT unit for high-motion stress
   review, including the replacement-GT revision and hashes.
3. Screen an authenticated real-sensor illumination dataset only after its
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
