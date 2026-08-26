# A10 disposable worker environment

Purpose: approved dataset-subset preparation, classical baseline execution,
learned/hybrid training, common evaluation, and export-feasibility tests.

Before the first paid experiment, capture and pin:

- operating system and x86-64 architecture;
- NVIDIA driver, CUDA, and GPU inventory;
- Python and framework versions;
- base container digest or fully locked environment;
- build tools required by selected classical baselines;
- exact clean Git commit;
- dataset and split manifest hashes.

The worker disk is scratch. A run is not durable until its governed bundle has
been checksum-verified in two independent destinations outside Brev.
