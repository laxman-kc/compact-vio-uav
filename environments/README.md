# Execution environments

The project separates environment definitions by role and architecture. A single
container is not assumed to be portable between the local Mac, the x86-64 A10
worker, and a future ARM64 edge target.

Each locked environment must record its operating system, CPU architecture,
dependency lock, base-image digest when applicable, and hardware/runtime
inventory. Training and release-producing runs additionally record the clean Git
commit and dataset manifest hashes in their experiment bundle.

- `local/`: documentation, lightweight validation, artifact inspection, and code review.
- `a10/`: disposable x86-64 CUDA training and offline evaluation.
- `target/`: future device-specific runtime; remains intentionally unresolved.

Version locks will be added only after the corresponding environment has been
inspected and its gate approved.
