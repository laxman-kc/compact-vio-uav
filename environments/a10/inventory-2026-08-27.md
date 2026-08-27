# A10 bounded-task inventory — 2026-08-27

Purpose: read-only inventory for the owner-approved repository implementation
smoke. This record does not authorize dataset download, dependency installation,
model training, artifact retention, or a lifecycle action.

Observation window: `2026-08-27T18:02Z`–`2026-08-27T18:04Z`.

| Component | Observed value |
|---|---|
| Workspace | `compact-vio-uav-gpu` (`127k2gq5e`) |
| Brev state | `RUNNING`; build `COMPLETED`; shell `READY`; health `HEALTHY` |
| Instance type | `gpu_1x_a10` |
| Architecture | `x86_64` |
| GPU | NVIDIA A10 |
| Reported GPU memory | 23,028 MiB |
| NVIDIA driver | 570.148.08 |
| Python | 3.10.12 |
| PyTorch | 2.7.0 |
| PyTorch CUDA build | 12.8 |
| `torch.cuda.is_available()` | `True` |
| Logical CPUs | 30 |
| Memory visible to context | 222 GiB total; 219 GiB available |
| Swap | None |
| Root disk | 1.4 TiB total; approximately 1.3 TiB available |

The type's current price, stoppability, billing state, and persistence behavior
were not established by this inventory. Re-check them before any lifecycle or
spending decision. Worker-local state is disposable; the smoke must use a pushed
Git revision and produce no unique retained artifact.
