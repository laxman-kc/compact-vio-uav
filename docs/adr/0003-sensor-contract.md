# ADR-0003: Sensor contract

- Status: Unresolved
- Decision owner: TBD
- Decision date: TBD

## Context

Monocular/stereo choice, shutter, rate, synchronization, calibration, and initialization excitation materially change observability, domain transfer, compute, and deployment hardware. Dataset availability must not silently select the physical sensor contract.

## Decision required

Choose and document:

- Monocular or stereo camera.
- Color or grayscale and supported resolution/rate envelope.
- Global or rolling shutter and exposure timestamp convention.
- Lens/FOV and supported calibration model.
- IMU rate, ranges, units, noise/bias model, and temperature expectations.
- Hardware trigger/shared clock requirement and maximum allowed jitter/offset.
- Camera-to-IMU extrinsic and temporal calibration procedure.
- Permitted initialization motion.

## Evidence required before acceptance

- Target mission dynamics and compute envelope.
- Candidate sensor interface and synchronization evidence.
- Calibration repeatability and residuals.
- Timing/calibration sensitivity experiments.
- Dataset-to-target sensor-gap analysis.

## Follow-up evidence

- Integration-time clock, frame, transport, calibration, and fault evidence from
  M13 when vehicle integration is in scope.
- Revalidation after every declared hardware, mount, focus, resolution, exposure,
  rate, firmware, driver, or timestamp-behavior change.
- Reopen or supersede this ADR if follow-up evidence violates an accepted sensor
  assumption or threshold.
