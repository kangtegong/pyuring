# Platform support matrix

pyuring targets **Linux only**. The Python layer is **CPython 3.8+** (see `setup.py`).

## Kernel

| Tier | Kernel | Notes |
|------|--------|--------|
| **Minimum (generic)** | **5.1+** | io_uring exists; many features and opcodes were added later. |
| **Recommended / CI assumption** | **5.15+** | Matches common LTS distros and README assumptions; broader opcode and flag support. |
| **Newer features** | **6.x+** | Some `IORING_SETUP_*` combinations, `uring_cmd`, extended opcodes—use `UringCtx.probe_*` to detect. |

Unsupported combinations fail at runtime with `UringError` (see `uring_create_ex` detail text).

### Opcodes and setup flags (approximate)

Exact minimum versions vary by distro backports. Prefer **runtime probes** (`probe_opcode_supported`, ring creation with chosen flags) over hard-coding versions.

| Feature | Typical kernel | Notes |
|--------|----------------|--------|
| `io_uring` base | 5.1+ | Queue, basic read/write |
| `IORING_SETUP_SQPOLL` | 5.1+ (behavior evolved) | May need privileges / `CAP_SYS_ADMIN` on older kernels |
| `IORING_SETUP_SINGLE_ISSUER` / `IORING_SETUP_COOP_TASKRUN` / `IORING_SETUP_DEFER_TASKRUN` | 5.15–6.x+ | Combinations may return `EOPNOTSUPP` on older kernels |
| Multishot recv/accept, buffer selection | 5.19–6.x+ | Probe `IORING_OP_*` and feature bits |
| Many newer `IORING_OP_*` | 6.x+ | See [kernel io_uring docs](https://www.kernel.org/doc/html/latest/io_uring/index.html) |

When something is missing, the syscall or queue init fails with an errno (`UringError`); there is no silent downgrade except in explicit high-level helpers (e.g. `pyuring.open(..., prefer_uring=False)` uses threaded I/O).

## liburing

- **Build from source:** the Makefile links against **liburing** from the system (`liburing-dev` / `liburing-devel`) or from **`third_party/liburing`** when vendored.
- **Version:** follow the vendored submodule tag or your distro package; liburing aims to track the kernel UAPI. pyuring does not pin a separate minimum beyond “headers + `.a` / `.so` usable by the wrapper”.

## Python / wheels

- **sdist:** builds `liburingwrap.so` at install time when possible.
- **manylinux wheels (x86_64):** may bundle a prebuilt `liburingwrap.so`; other platforms typically build from source.

## Containers

io_uring is often **blocked by default Docker seccomp**. Use `--security-opt seccomp=unconfined` (or an appropriate profile) for tests and for applications that need the ring—see `scripts/docker-test-matrix.sh`.
