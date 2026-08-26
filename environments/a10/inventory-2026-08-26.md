# A10 worker inventory — 2026-08-26

This is a read-only observation of the currently running default Brev execution
context for `compact-vio-uav-gpu`. It is evidence about the present worker, not a
dependency lock or permission to install into the global environment.

| Component | Observed value |
|---|---|
| Instance | `compact-vio-uav-gpu` |
| Architecture | x86-64 |
| Kernel | Linux 6.8.0-60-generic |
| Operating system | Ubuntu 22.04.5 LTS (Jammy) |
| GPU | NVIDIA A10 |
| Reported GPU memory | 23,028 MiB |
| NVIDIA driver | 570.148.08 |
| CUDA compiler | 12.8 (`V12.8.93`) |
| Python | 3.10.12 |
| pip | 22.0.2 |
| PyTorch | 2.7.0 |
| PyTorch CUDA build | 12.8 |
| `torch.cuda.is_available()` | `True` |
| GCC | 11.4.0 |
| Git | 2.34.1 |
| CMake | 3.22.1 |
| Docker | 28.3.1 |
| Logical CPUs | 30 |
| Memory visible to context | 222 GiB total, 219 GiB available at observation |
| Swap | None |
| Root disk | 1.4 TiB total, approximately 1.3 TiB available at observation |
| Default working directory | `/home/ubuntu` |

Before a paid or claim-supporting run, the selected environment must be isolated
and locked. The run bundle must capture this inventory again because the rented
worker image and available resources may change.

## Lifecycle observation

Observation window: `2026-08-26T18:35:53Z`–`2026-08-26T18:36:00Z`

Brev CLI: `v0.6.326` (the CLI reported `v0.6.334` available; no upgrade was
performed)

Sanitized `brev list --json` fields:

| Field | Observed value |
|---|---|
| Name | `compact-vio-uav-gpu` |
| Instance type | `gpu_1x_a10` |
| Status | `RUNNING` |
| Build | `COMPLETED` |
| Shell | `READY` |
| Health | `HEALTHY` |

The `brev search gpu --json` row with exact type ID `gpu_1x_a10` reported
provider `lambda-labs`, one A10 with 24 GB VRAM, 30 vCPU, 200 GiB RAM, 1,400 GB
disk, `stoppable=false`, `rebootable=true`, and USD 1.548/hour. These catalog and
runtime observations are volatile and do not prove the account invoice. Refresh
them immediately before any lifecycle or spending decision.

[NVIDIA's lifecycle documentation](https://docs.nvidia.com/brev/concepts/gpu-instances)
states that running instances accrue hourly compute charges and deletion is
irreversible. Its
[non-stoppable instance documentation](https://docs.nvidia.com/ai-workbench/user-guide/latest/how-to/locations/add-brev.html)
states that termination is required to halt charges and destroys all disk
writes. No stop, reboot, deletion, or termination was attempted during this
observation.

The repository clone is at `/home/ubuntu/compact-vio-uav`, outside the general
`/home/ubuntu/workspace` location NVIDIA documents as persistent across a stop
for stoppable instances. It is therefore treated as a disposable clean checkout;
for a non-stoppable termination all worker disk writes are lost regardless.
