# pyuring

[![PyPI](https://img.shields.io/pypi/v/pyuring.svg)](https://pypi.org/project/pyuring/)
[![CI](https://github.com/kangtegong/pyuring/actions/workflows/ci.yml/badge.svg)](https://github.com/kangtegong/pyuring/actions/workflows/ci.yml)

pyuring is a Python library for performing file I/O using the Linux [`io_uring`](https://kernel.dk/io_uring.pdf) kernel interface.

`io_uring` submits I/O operations to the kernel through a shared-memory ring buffer instead of issuing individual system calls per operation. This reduces per-operation syscall overhead, which is especially noticeable in workloads with many small or concurrent I/O operations.

pyuring exposes `io_uring` to Python through a C shared library (`liburingwrap.so`, built on top of [liburing](https://github.com/axboe/liburing)) and `ctypes` bindings. You do not need to understand the ring buffer mechanics to use the high-level API — but if you want direct control over submission and completion queues, that is available too.

**Requires:** Linux kernel 5.15+, Python 3.8+

## Install

```bash
pip install pyuring
```

On glibc x86\_64 Linux, pip installs a manylinux wheel that includes a pre-built `liburingwrap.so` — no separate liburing package is needed. For other platforms or source builds, see [docs/INSTALLATION.md](docs/INSTALLATION.md).

**Documentation site:** [kangtegong.github.io/pyuring](https://kangtegong.github.io/pyuring/) (MkDocs, deployed from `docs/` via GitHub Actions). Local preview: `pip install -r requirements-docs.txt && mkdocs serve`. **Enable once:** repository **Settings → Pages → Source: GitHub Actions** (not “Deploy from branch”).

## What pyuring provides

### High-level file I/O helpers

The simplest way to use pyuring. `copy`, `write`, and `write_many` handle queue depth tuning, buffer management, and the io_uring pipeline internally.

```python
import pyuring as iou

# Copy a file
iou.copy("/tmp/src.dat", "/tmp/dst.dat")

# Write a new file (100 MiB of data)
iou.write("/tmp/new.dat", total_mb=100)

# Write multiple files into a directory
iou.write_many("/tmp/out", nfiles=10, mb_per_file=100)
```

The `mode` parameter controls how queue depth and buffer size are tuned:

| mode | Behavior |
|------|----------|
| `"auto"` (default) | Starts with the default block size and increases it as the operation progresses. Uses the dynamic buffer C path. |
| `"safe"` | Conservative settings: queue depth capped at 16 (copy) or 128 (write), block size capped at 1 MiB (copy) or 4 KiB (write). |
| `"fast"` | Aggressive settings: queue depth at least 64 (copy) or 256 (write), block size at least 1 MiB (copy) or 64 KiB (write). |

You can track progress or cancel an operation cooperatively using `progress_cb`:

```python
def on_progress(done_bytes, total_bytes):
    print(f"{done_bytes} / {total_bytes} bytes")
    return False  # return True to cancel (raises UringError with errno.ECANCELED)

iou.copy("/tmp/src.dat", "/tmp/dst.dat", progress_cb=on_progress)
```

---

### UringCtx — direct ring control

`UringCtx` wraps a single `io_uring` instance. Use it when you need to submit and receive completions manually, register fixed file descriptors or buffers, or configure the ring with specific setup flags.

```python
import os
import pyuring as iou

with iou.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/data.bin", os.O_RDONLY)

    # Synchronous read (submits one SQE and waits for its CQE internally)
    data = ctx.read(fd, length=4096, offset=0)

    # Asynchronous: submit a read, then wait for its completion separately
    buf = bytearray(4096)
    ctx.read_async(fd, buf, offset=0, user_data=42)
    ctx.submit()
    user_data, result = ctx.wait_completion()
    # result is the number of bytes read, or a negative errno on error
```

You can pass `IORING_SETUP_*` flags to tune the ring at creation time:

```python
ctx = iou.UringCtx(
    entries=128,
    setup_flags=iou.IORING_SETUP_SINGLE_ISSUER | iou.IORING_SETUP_COOP_TASKRUN,
)
```

---

### UringAsync — asyncio integration

`UringAsync` integrates `UringCtx` with an `asyncio` event loop. It registers the ring's completion queue file descriptor (`ring_fd`) with the loop's reader, so `await ua.wait_completion()` returns as soon as a CQE is available — without blocking the event loop thread.

```python
import asyncio
import pyuring as iou
from pyuring import UringAsync

async def main():
    with iou.UringCtx(entries=64) as ctx:
        async with UringAsync(ctx) as ua:
            fd = os.open("/tmp/data.bin", os.O_RDONLY)
            buf = bytearray(4096)
            ctx.read_async(fd, buf, user_data=1)
            ctx.submit()
            user_data, result = await ua.wait_completion()

asyncio.run(main())
```

---

### BufferPool — native buffer management

`BufferPool` allocates and manages a set of fixed-size buffers in native memory. Use it with `read_async` / `write_async` when you want to avoid Python object allocation per I/O operation.

```python
with iou.BufferPool.create(initial_count=8, initial_size=4096) as pool:
    ptr, size = pool.get_ptr(0)  # raw pointer to buffer slot 0
    ctx.read_async(fd, (ptr, size), user_data=0)
    ctx.submit()
    ctx.wait_completion()
    data = pool.get(0)  # read the result as bytes
```

---

### Kernel capability probe

Before using a specific `io_uring` opcode, you can check at runtime whether the running kernel supports it. This is useful because opcode availability depends on the kernel version.

```python
from pyuring import opcode_supported, require_opcode_supported, IORING_OP_SPLICE

# Returns True/False
if iou.opcode_supported(iou.IORING_OP_SPLICE):
    ...

# Raises UringError(errno.EOPNOTSUPP) if not supported
require_opcode_supported(iou.IORING_OP_SPLICE, "my_splice_op")
```

---

## Error handling

All errors from the native layer raise `UringError`, which is a subclass of `OSError`. It carries three fields:

| Field | Content |
|-------|---------|
| `errno` | The kernel errno value (same meaning as in `os` / `OSError`). |
| `operation` | The name of the C wrapper function that failed (e.g. `"uring_copy_path"`). |
| `detail` | An optional string with additional context, such as search paths when `liburingwrap.so` cannot be found. |

```python
import errno
from pyuring import UringError

try:
    iou.copy("/tmp/src.dat", "/tmp/dst.dat")
except UringError as e:
    if e.errno == errno.ENOENT:
        print("source file not found")
    elif e.errno == errno.ECANCELED:
        print("cancelled by progress callback")
    print(f"failed in: {e.operation}")
```

---

## Further reading

| Document | Contents |
|----------|----------|
| [docs/USAGE.md](docs/USAGE.md) | Full API reference for all classes and functions |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Build from source, liburing options, platform notes |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | How to run the included benchmarks |
| [docs/TESTING.md](docs/TESTING.md) | How to run the test suite |
