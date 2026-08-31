# Changelog

This file records user-visible changes. CompactVIO-UAV has not published a versioned software or
model release yet.

## Unreleased

### Added

- Offline camera-and-IMU recording inference with CSV, SVG, JSON, and HTML outputs.
- A local web interface with a built-in synthetic workflow example and one-ZIP recording bundles.
- A packaged RAFT/gyro/translation-head runtime and checked translation-head ONNX export.
- Separate getting-started, input-format, result-interpretation, architecture, and model-card
  documentation.
- Contribution, conduct, security, citation, third-party-notice, issue, pull-request, and example
  scaffolding for a future public release.

### Changed

- The README now leads with the runnable user workflow, current capability, architecture, and
  measured benchmark result instead of the historical execution ledger.
- Software execution success and model-quality acceptance are reported as separate facts.

### Known limitations

- The current model candidate failed the held-out distance-scale and long-horizon-drift gates.
- A clean clone does not include the Git-ignored model package; no rights-reviewed model download
  has been published.
- The project source license, artifact redistribution terms, and first release tag remain
  unresolved.
- The full camera-and-IMU pipeline is not exported as one ONNX graph.
