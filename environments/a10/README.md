# A10 disposable worker environment

Status: an A10 was observed for the bounded 2026-08-27 implementation smoke;
the dated observation proves neither present state nor future-task authority.

Each worker receives its own dated inventory. The 2026-08-27 worker was approved
only for that repository checkout and implementation-smoke task. Dataset
preparation, baseline execution, learned/hybrid training, common evaluation,
export-feasibility tests, and any later use require fresh state verification and
task-specific confirmation. The project does not assume that a later worker is
an A10 or shares this image.

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
