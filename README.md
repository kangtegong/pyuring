# pyuring

**Repository:** [github.com/kangtegong/pyuring](https://github.com/kangtegong/pyuring) — source tree for the **`pyuring`** Python distribution.

## What this project is

`pyuring` is a **Linux-only** Python library that talks to a small native shared library, **`liburingwrap.so`**, via `ctypes`. That C layer is built on top of **[liburing](https://github.com/axboe/liburing)** and the kernel **io_uring** interface (queue depth, submissions, completions). The bindings are aimed at **high-throughput file copy and synthetic write workloads**, **synchronous and asynchronous** `read`/`write` on open file descriptors, and optional **dynamic buffer sizing** (callbacks implemented in Python for some code paths).

This repository is **not** a complete Python mapping of every liburing opcode or helper. It exposes a **focused subset** implemented in `csrc/` (e.g. pipeline copy/write in C, `UringCtx` for queued I/O, `BufferPool` for fixed-size slots). Treat it as a specialized toolkit and benchmark harness, not a general-purpose async filesystem framework.

| Component | Role |
|-----------|------|
| `pyuring/` | Python package: orchestrated helpers, `UringCtx`, `BufferPool`, module functions backed by the `.so` |
| `csrc/uring_wrap.c` (and related) | Native wrapper around io_uring; built as `build/liburingwrap.so` |
| `Makefile` | Builds the shared library (system or vendored liburing) |
| `third_party/liburing` | Optional vendored liburing (submodule or manual tree) |
| `examples/` | Benchmarks and the `test_dynamic_buffer.py` verification script |

## Requirements

- **OS:** Linux with a kernel that supports io_uring (project documentation assumes **5.15+**).
- **Python:** **3.8+** (see `setup.py`).
- **Build:** `gcc`, `make`, and **liburing development headers** (or a built vendored liburing tree).

## Install

```bash
pip install pyuring
```

From a checkout (builds the native library as part of install):

```bash
git clone --recursive https://github.com/kangtegong/pyuring.git
cd pyuring
pip install -e .
```

System packages for liburing headers when not using the submodule:

| Distribution | Package |
|--------------|---------|
| Debian / Ubuntu | `liburing-dev` |
| Fedora / RHEL | `liburing-devel` |
| Arch Linux | `liburing` |

Details, failures, and manual copy of the `.so` into `pyuring/lib/`: see **[INSTALLATION.md](INSTALLATION.md)**.

## Quick start

**Orchestrated helpers** apply preset queue-depth and block-size tuning via a `mode` argument:

```python
import pyuring as iou

iou.copy("/tmp/source.dat", "/tmp/dest.dat")
iou.write("/tmp/new.dat", total_mb=100)
iou.write_many("/tmp/out", nfiles=10, mb_per_file=100)
```

**Direct bindings** are the same functions and classes as above, grouped on `pyuring.direct` (legacy alias: `pyuring.raw`):

```python
import pyuring as iou

iou.direct.copy_path("/tmp/a.dat", "/tmp/b.dat", qd=32, block_size=1 << 20)

with iou.direct.UringCtx(entries=64) as ctx:
    ...
```

Full parameter tables, `UringCtx` / `BufferPool` methods, and semantics: **[USAGE.md](USAGE.md)**.

## Documentation index

| Document | Contents |
|----------|----------|
| [INSTALLATION.md](INSTALLATION.md) | Dependencies, editable install, vendored liburing, verification |
| [USAGE.md](USAGE.md) | API specification (tables), behavior notes |
| [examples/BENCHMARKS.md](examples/BENCHMARKS.md) | Benchmark scripts |

## Verification

After a local build:

```bash
make && python3 examples/test_dynamic_buffer.py
```

The script must exit with status **0** and print that all checks passed.
