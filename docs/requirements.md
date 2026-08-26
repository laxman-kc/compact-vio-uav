# Requirements index

Status: Navigation and source traceability only — non-normative

Last reviewed: 2026-08-26

The sole normative requirements source is
[Project requirements](requirements/project-requirements.md). This index does
not define, modify, accept, or waive a requirement.

## Authority boundaries

| Concern | Authoritative record |
|---|---|
| Requirement definitions and `R-*` IDs | [Project requirements](requirements/project-requirements.md) |
| Unresolved choices and accepted decisions | [ADR index](adr/README.md) and individual ADRs |
| Milestone order and dependency gates | [Implementation plan](plan.md) |
| Dated implementation evidence | [Progress evidence](progress.md) |
| Research method and claim controls | [Research protocol](protocols/research-protocol.md) |
| Per-run operating procedure | [Experiment lifecycle](protocols/experiment-lifecycle.md) |
| Dataset admissibility | [Dataset policy](../governance/datasets/policy.md) and [registry](../governance/datasets/registry.yaml) |
| Artifact retention and restoration | [Artifact policy](../governance/artifacts/policy.md) |
| M2 decision inputs and record lifecycle | [Governance records](../governance/records/README.md); only accepted ADRs decide |

If these records conflict, work stops until the conflict is corrected at its
authoritative source. A plan status cannot accept an ADR, and a progress entry
cannot change a requirement.

## Requirement-group map

| Group | Canonical IDs | Primary evidence |
|---|---|---|
| Research integrity | `R-RI-*` | Frozen protocol, run manifests, claim-to-evidence review |
| Data and causality | `R-DATA-*` | Dataset/split manifests, causal replay tests |
| Estimator contract | `R-EST-*` | Accepted estimator/sensor ADRs and interface tests |
| Calibration and synchronization | `R-CAL-*` | Versioned calibration profile, reports, residual/timing review |
| Artifact and infrastructure safety | `R-INFRA-*` | Static preflight and copy audit as supporting fragments; post-export storage evidence, restore drill, and cost/teardown records as gate evidence |
| Evaluation | `R-EVAL-*` | Per-sequence results, failures, coverage, same-platform profiling |
| Deployment | `R-DEP-*` | Export parity and exact-target build/profiling evidence |
| Vehicle safety | `R-SAFE-*` | Release-pinned interface, SITL/HIL fault evidence, safety approval |

## Official-source traceability

The following sources justify or constrain existing canonical requirements.
They do not decide unresolved project values such as the camera count, model,
dataset split, edge board, or numerical acceptance thresholds. Web sources were
accessed on 2026-08-26; mutable `latest` pages must be rechecked at the milestone
that uses them.

| Official source | Canonical requirements informed | Project interpretation |
|---|---|---|
| [GitHub: About large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) and [Actions artifact/log retention](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-repository) | `R-DATA-005`, `R-INFRA-001`, `R-INFRA-002`, `R-INFRA-006` | GitHub documents normal-Git size limits, says Git is not a backup tool, and gives Actions artifacts/logs a configured retention lifecycle. The canonical requirements therefore assign GitHub to versioned control-plane state rather than the independent artifact-backup role. |
| [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use) | `R-INFRA-004` | The current CI implementation applies the source's least-privilege and immutable-reference guidance through read-only token permission and verified full-SHA action references. |
| [NVIDIA Brev GPU lifecycle](https://docs.nvidia.com/brev/concepts/gpu-instances) and [non-stoppable instance semantics](https://docs.nvidia.com/ai-workbench/user-guide/latest/how-to/locations/add-brev.html) | `R-INFRA-001`, `R-INFRA-003`, `R-INFRA-005`, `R-INFRA-007` | The sources describe hourly billing while running and destructive termination for non-stoppable instances. The canonical requirements connect that lifecycle to preservation evidence and explicit authority. |
| [NIST SP 800-209](https://csrc.nist.gov/pubs/sp/800/209/final) | `R-INFRA-002`, `R-INFRA-003`, `R-INFRA-007` | NIST covers recovery copies, restoration assurance, and documented recovery practices. The canonical requirements use those concepts for the artifact restore gate. |
| [OpenVINS sensor calibration](https://docs.openvins.com/gs-calibration.html) | `R-CAL-001` through `R-CAL-005`, `R-EST-001` | OpenVINS identifies spatial/temporal calibration, IMU stochastic parameters, diagnostics, and relative timestamp error as material to VIO behavior; the canonical calibration fields preserve that evidence. |
| [Kalibr VI-sensor procedure](https://github.com/ethz-asl/kalibr/wiki/Calibrating-the-VI-Sensor), [camera–IMU calibration](https://github.com/ethz-asl/kalibr/wiki/camera-imu-calibration), and [IMU noise model](https://github.com/ethz-asl/kalibr/wiki/IMU-Noise-Model) | `R-CAL-001` through `R-CAL-005` | Kalibr documents motion excitation, timestamp-interval and residual diagnostics, and calibration report/configuration outputs; the canonical requirements make those reviewable artifacts rather than treating solver convergence as acceptance. |
| [OpenVINS timing analysis](https://docs.openvins.com/eval-timing.html) | `R-EVAL-001`, `R-EVAL-003` | OpenVINS distinguishes same-platform comparison and timing distributions from cross-hardware claims; the evaluator requirements preserve that distinction. |
| [NVIDIA TensorRT support matrix](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/support-matrix.html) and [engine compatibility](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/engine-compatibility.html) | `R-DEP-001` through `R-DEP-003` | NVIDIA documents platform/version/hardware compatibility limits. The deployment requirements therefore make export conditional and require exact-target provenance and regression evidence. |
| [PX4 v1.17 VIO integration](https://docs.px4.io/v1.17/en/computer_vision/visual_inertial_odometry), [EKF2 external vision](https://docs.px4.io/v1.17/en/advanced_config/tuning_the_ecl_ekf), and [tagged VehicleOdometry source](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/msg/versioned/VehicleOdometry.msg) | `R-EST-001`, `R-EST-004`, `R-EST-005`, `R-SAFE-002`, `R-SAFE-003` | The stable-release documents expose frame, sample-time, delay, covariance/noise, reset, and estimator-loss contracts. The canonical requirements require a newly selected release to be pinned and reverified at integration time. |

## Official decision-input sources

These sources constrain how an unresolved ADR input is recorded. They do not
define a canonical requirement, select a license, establish compatibility, or
replace legal review.

| Official source | Routed decision input | Limited project interpretation |
|---|---|---|
| [GitHub: Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) | ADR-0001 public-repository and project-license input | GitHub explains that without a selected license default copyright supplies no general license to reproduce, distribute, or create derivative works, while GitHub's Terms still grant platform-specific rights such as viewing and forking a public repository. This supports an explicit owner decision without overstating the current restriction; it does not select a license or decide rights in third-party assets. |
| [SPDX Specification 3.0.1: license expressions](https://spdx.github.io/spdx-spec/v3.0.1/annexes/spdx-license-expressions/) | ADR-0001 candidate-license and rights-matrix fields | SPDX defines a standard expression grammar for identifiers, references, exceptions, and compound terms. Use it when the reviewed terms can be represented accurately; recording an expression does not prove permission, compatibility, or commercial eligibility. |

## Unresolved-decision routing

- Purpose, license, and release lanes: [ADR-0001](adr/0001-project-and-release-scope.md).
- Estimator state and local-VIO/VI-SLAM scope: [ADR-0002](adr/0002-estimator-scope.md).
- Physical and dataset sensor contract: [ADR-0003](adr/0003-sensor-contract.md).
- One primary research contribution and hypothesis: [ADR-0004](adr/0004-primary-research-contribution.md).
- Artifact vault, backup, retention, spend, and teardown authority: [ADR-0005](adr/0005-artifact-storage.md).
- Edge/export/ROS 2/PX4/physical-flight scope: [ADR-0006](adr/0006-deployment-scope.md).

Only an `Accepted` ADR with its required evidence resolves one of these choices.
