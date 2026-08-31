# Input formats

## Recommended recording bundle

Upload one ZIP with an optional single wrapper directory and these files:

```text
frames/
  <timestamp_ns>.png
  <timestamp_ns>.png
imu.csv
calibration.json
camera.csv                 # optional
compact-vio-bundle.json    # optional
```

The bundle reader rejects path traversal, absolute paths, symlinks, case-insensitive duplicate
names, encrypted members, unsupported entries, ambiguous calibration files, and excessive archive
expansion.

### Optional bundle metadata

```json
{
  "name": "Office walk 01",
  "schema_version": "1.0",
  "workflow_example": false
}
```

Only these three fields are accepted. `workflow_example` marks synthetic workflow fixtures; it
does not change inference.

## Camera frames

Use grayscale or color `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, or `.tiff` files. Without
`camera.csv`, every filename stem must be its non-negative nanosecond timestamp, and timestamps
must be strictly increasing.

All source images must match `camera.resolution` in the calibration document. The current hybrid
runtime rectifies and resizes frames internally for RAFT; it does not accept a silent resolution
mismatch.

## Camera timestamp CSV

This file is optional for timestamp-named images and required for MP4 input.

```csv
timestamp_ns,filename
2000000000,frames/frame-0001.png
2050000000,frames/frame-0002.png
```

`filename` is optional when rows correspond exactly to lexicographically sorted images. Accepted
timestamp headers include `timestamp_ns` and the native EuRoC timestamp spelling.

## IMU CSV

Canonical columns:

```csv
timestamp_ns,gyro_x_rad_s,gyro_y_rad_s,gyro_z_rad_s,accel_x_m_s2,accel_y_m_s2,accel_z_m_s2
0,0.0,0.0,0.001,0.0,0.0,9.81
5000000,0.0,0.0,0.001,0.0,0.0,9.81
```

Timestamps must be strictly increasing. The stream must overlap the camera recording and include
at least two samples strictly before its first frame. Keep the camera and IMU stationary during a
1–2-second pre-roll: the runtime treats the mean pre-frame gyro reading as sensor bias and
subtracts it from the recording.

Short `gx,gy,gz,ax,ay,az` and native EuRoC IMU headers are also supported.

## Calibration

Start from [`configs/raft-hybrid-calibration.example.json`](../configs/raft-hybrid-calibration.example.json).
That file is a structural example with synthetic values, not a calibration for a real camera.
Measure or obtain the intrinsics, distortion, resolution, and camera-to-IMU transform for the
actual sensor rig. Using plausible-looking placeholder numbers can produce a trajectory without
making it meaningful.

The required shape is:

```json
{
  "camera": {
    "T_BS": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
    "camera_model": "pinhole",
    "distortion_coefficients": [0.0,0.0,0.0,0.0],
    "distortion_model": "radtan",
    "intrinsics": [200.0,200.0,188.0,120.0],
    "resolution": [376,240]
  },
  "imu": {
    "T_BS": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
  }
}
```

`T_BS` maps the camera sensor into the IMU sensor frame. The current package requires
`imu.T_BS` to be identity and reports motion in the previous IMU sensor frame.

The runtime checks shape, finiteness, supported models, identity IMU transform, and exact source
image resolution. It does not calibrate a camera or estimate camera-to-IMU timing for you.

## Before you upload

- Confirm that camera and IMU timestamps use the same clock and nanosecond unit.
- Confirm that frame filenames or `camera.csv` timestamps are strictly increasing.
- Include 1–2 seconds of stationary causal IMU pre-roll before the first frame.
- Replace every synthetic calibration value with a value for the recording sensor.
- Keep a copy of the original recording; the app writes results to a separate directory.

Next: [run the app](getting-started.md) or [understand the result files](interpreting-results.md).
