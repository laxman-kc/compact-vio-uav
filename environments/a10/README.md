# A10 disposable worker environment

Status: one live A10 exists for the bounded 2026-08-27 implementation smoke;
future-task authorization is not implied.

Each worker receives its own dated inventory. The current worker is approved
only for repository checkout and implementation smoke verification. Dataset
preparation, baseline execution, learned/hybrid training, common evaluation, and
export-feasibility tests require later task-specific confirmation. The project
does not assume that a later worker is an A10 or shares this image.

Before the first paid experiment, capture and pin:

- operating system and x86-64 architecture;
- NVIDIA driver, CUDA, and GPU inventory;
- Python and framework versions;
- base container digest or fully locked environment;
- build tools required by selected classical baselines;
- exact clean Git commit;
- dataset and split manifest hashes.

The worker disk is scratch. A run is not durable until its governed bundle has
been checksum-verified in two independent destinations outside the temporary
worker.
