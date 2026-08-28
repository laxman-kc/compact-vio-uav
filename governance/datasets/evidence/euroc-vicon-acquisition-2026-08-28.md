# EuRoC Vicon acquisition evidence — 2026-08-28

Status: Executed development acquisition  
Decision authority: Accepted ADR-0004 and explicit project-owner instruction  
Purpose: Compact learned VIO development prototype; non-commercial research

## Selected data

- Dataset: The EuRoC micro aerial vehicle datasets.
- Publisher: ETH Zurich.
- DOI: `10.3929/ethz-b-000690084`.
- Rights statement: `In Copyright - Non-Commercial Use Permitted`.
- Modalities used: monocular `cam0`, `imu0` gyroscope and accelerometer, official
  sensor calibration, and `state_groundtruth_estimate0` labels/reference.
- Physical units: the six Vicon Room 1 and Vicon Room 2 source sequences. The
  exact development membership is in
  [`configs/data/euroc_vicon_v1.json`](../../../configs/data/euroc_vicon_v1.json).

Ground truth is exposed only to supervised examples from training membership
and to validation/test evaluation. It is not a model inference input.

## Official archive identity

| Archive | Official bitstream | Bytes | ETH MD5 | Locally computed SHA-256 |
|---|---|---:|---|---|
| `vicon_room1.zip` | `02ecda9a-298f-498b-970c-b7c44334d880` | 6,042,263,426 | `5ce06b405827e453a82523d3ca9c2fd0` | `fe73c27be6dc8ac00493b78b750d36b144daf49eea7fdf3163e934527c1b5297` |
| `vicon_room2.zip` | `ea12bc01-3677-4b4c-853d-87c7870b8c44` | 6,013,384,949 | `c6347f4e0476aaa9a43a919c163c49c5` | `6daf2cbc2de9a6bc4e02866c99ed01c29a5c7c164756f06c4f72656192977cfc` |

The byte sizes and MD5 values came from the ETH repository API. SHA-256 was
computed from the matching downloaded bytes on the authorized A10 worker. The
checked-in acquisition plan contains the exact HTTPS content endpoints.

## Execution record

- Worker: `compact-vio-uav-gpu`, NVIDIA A10 24 GB.
- Data root: `/home/ubuntu/datasets/euroc` (worker-local, disposable).
- Download date: 2026-08-28.
- Both archive byte counts and MD5 values matched before extraction.
- SHA-256 values above were recorded before any training use.
- Extraction retained only `cam0`, `imu0`, and
  `state_groundtruth_estimate0`; `cam1` and ROS bag files are not model inputs.
- The worker remains a temporary execution/data copy, not the repository or a
  durable artifact store.

## Scientific boundary

This acquisition enables an executable prototype. It does not by itself prove
model accuracy, UAV generalization, embedded performance, deployment fitness,
or flight safety. Exact training configuration, checkpoint identity, held-out
metrics, and failures are separate run outputs.
