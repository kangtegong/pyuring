# API Reference

This document covers every public symbol in pyuring. All importable names are available both at the package root (`import pyuring as iou; iou.copy(...)`) and on the `pyuring.direct` namespace object (`iou.direct.copy_path(...)`). `pyuring.raw` is a backward-compatible alias for `pyuring.direct`.

---

## Error handling

Any failure in the native layer raises `UringError`, a subclass of `OSError`.

```python
import errno
from pyuring import UringError

try:
    iou.copy("/tmp/src.dat", "/tmp/dst.dat")
except UringError as e:
    print(e.errno)      # int — kernel errno (e.g. errno.ENOENT)
    print(e.operation)  # str — name of the failing C function
    print(e.detail)     # str or None — extra hint (e.g. .so search paths)
```

`e.errno` matches the values in Python's `errno` module, so you can branch on `errno.ENOENT`, `errno.ECANCELED`, etc. Do not parse the string representation.

---

## High-level helpers

These three functions are the recommended starting point. They handle queue depth, buffer sizing, and the io_uring pipeline internally. Import them from the package root.

### `copy`

Copies a file from `src_path` to `dst_path` using an io_uring read→write pipeline in C. Returns the number of bytes copied.

```python
bytes_copied = iou.copy(
    src_path,
    dst_path,
    *,
    mode="auto",             # tuning preset: "auto" | "safe" | "fast"
    qd=32,                   # queue depth (adjusted by mode)
    block_size=1 << 20,      # default I/O block size in bytes (adjusted by mode)
    fsync=False,             # fsync the destination file after all writes
    sync_policy="default",   # overrides fsync when not "default" (see table below)
    buffer_size_cb=None,     # optional callback to control block size per chunk
    progress_cb=None,        # optional callback called after each completed write
)
```

**`mode` behavior:**

| mode | queue depth | block size | io path |
|------|-------------|------------|---------|
| `"auto"` | unchanged | starts at `block_size`, grows adaptively | `copy_path_dynamic` with built-in callback |
| `"safe"` | capped at 16 | capped at 1 MiB | `copy_path` (static) or dynamic if extras used |
| `"fast"` | minimum 64 | minimum 1 MiB | same as above |

**`sync_policy` values:**

| sync_policy | Effect |
|-------------|--------|
| `"default"` | Uses the `fsync` boolean parameter. |
| `"none"` | Never fsyncs, regardless of `fsync`. |
| `"end"` | Always fsyncs at the end, regardless of `fsync`. |

**`buffer_size_cb`** — called before each read/write chunk to determine the buffer size:
```python
def my_cb(current_offset: int, total_bytes: int, default_block_size: int) -> int:
    return default_block_size  # return any positive int
```

**`progress_cb`** — called after each completed destination write:
```python
def on_progress(done_bytes: int, total_bytes: int) -> bool:
    print(f"{done_bytes}/{total_bytes}")
    return False  # return True to cancel; raises UringError(errno.ECANCELED)
```

---

### `write`

Creates a new file at `dst_path` and fills it with `total_mb` MiB of data. Returns the number of bytes written.

```python
bytes_written = iou.write(
    dst_path,
    *,
    total_mb,                    # size of the file to write, in MiB
    mode="auto",
    qd=256,
    block_size=4096,
    fsync=False,
    dsync=False,                 # apply RWF_DSYNC per write (data integrity before return)
    sync_policy="default",
    buffer_size_cb=None,
    progress_cb=None,
)
```

**`mode` behavior** (write-specific thresholds):

| mode | queue depth | block size |
|------|-------------|------------|
| `"auto"` | unchanged | adaptive |
| `"safe"` | capped at 128 | capped at 4 KiB |
| `"fast"` | minimum 256 | minimum 64 KiB |

**`sync_policy` values** (write adds `"data"` and `"end_and_data"` over copy):

| sync_policy | fsync at end | RWF_DSYNC per write |
|-------------|:------------:|:-------------------:|
| `"default"` | from `fsync` param | from `dsync` param |
| `"none"` | no | no |
| `"end"` | yes | no |
| `"data"` | no | yes |
| `"end_and_data"` | yes | yes |

---

### `write_many`

Writes `nfiles` files under `dir_path`, each `mb_per_file` MiB in size. Returns the total number of bytes written across all files.

```python
total_bytes = iou.write_many(
    dir_path,
    *,
    nfiles,
    mb_per_file,
    mode="auto",
    qd=256,
    block_size=4096,
    fsync_end=False,         # fsync each file after its final write
    sync_policy="default",   # "default" / "none" / "end" (same as copy)
)
```

`mode` adjusts `qd` and `block_size` with the same thresholds as `write`. There is no dynamic buffer path for `write_many`; it always uses `write_manyfiles` internally.

---

## Native pipeline functions

These functions call the C pipeline directly with no preset tuning. Use them when you want precise control over queue depth and block size. They are available at the package root and on `pyuring.direct`.

| Function | Key parameters | Returns | Notes |
|----------|----------------|---------|-------|
| `copy_path(src, dst)` | `qd=32`, `block_size=1<<20` | `int` bytes copied | Fixed block size throughout. |
| `copy_path_dynamic(src, dst)` | `qd=32`, `block_size=1<<20`, `buffer_size_cb=None`, `fsync=False`, `progress_cb=None` | `int` | Block size per chunk from callback if provided. |
| `write_newfile(dst)` | `total_mb`, `block_size=4096`, `qd=256`, `fsync=False`, `dsync=False` | `int` bytes written | Fixed block size. |
| `write_newfile_dynamic(dst)` | same as above + `buffer_size_cb=None`, `progress_cb=None` | `int` | Dynamic block size via callback. |
| `write_manyfiles(dir)` | `nfiles`, `mb_per_file`, `block_size=4096`, `qd=256`, `fsync_end=False` | `int` total bytes | Writes `nfiles` sequentially. |

All path arguments are `str`. Callback signatures are the same as documented under `copy` above.

---

## `UringCtx`

`UringCtx` wraps one `io_uring` instance. It uses `io_uring_queue_init_params` internally, which means you can pass any `IORING_SETUP_*` flag combination supported by the kernel.

**Threading:** A single `UringCtx` is not thread-safe. By default (`single_thread_check=True`), calling any method from a thread other than the one that created the context raises `UringError`. If you need a worker thread to call `wait_completion` (e.g. via `wait_completion_in_executor`), construct with `single_thread_check=False` and ensure exclusive access yourself.

**Lifecycle:** After `close()`, every method raises `UringError` with `detail="closed"`. Use a `with` statement to ensure cleanup.

### Constructor

```python
UringCtx(
    lib_path=None,            # path to liburingwrap.so; None = auto-discover
    entries=64,               # submission queue size hint passed to the kernel
    setup_flags=0,            # bitwise OR of IORING_SETUP_* constants
    sq_thread_cpu=-1,         # pin SQPOLL kernel thread to this CPU (-1 = don't pin)
    sq_thread_idle=0,         # SQPOLL idle timeout in milliseconds
    single_thread_check=True, # raise UringError if called from another thread
)
```

When `lib_path=None`, the library is searched in this order: `pyuring/lib/`, `build/` (repo root), then the system linker path.

**Commonly used setup flags:**

| Flag | Purpose |
|------|---------|
| `IORING_SETUP_SINGLE_ISSUER` | Tells the kernel that only one thread submits SQEs. Enables internal optimizations. |
| `IORING_SETUP_COOP_TASKRUN` | Processes completions cooperatively rather than via interrupt. Reduces latency in single-threaded loops. |
| `IORING_SETUP_DEFER_TASKRUN` | Defers task work until you explicitly call into the ring. Useful with SINGLE_ISSUER. |
| `IORING_SETUP_SQPOLL` | Spawns a kernel polling thread that drains the SQ without needing a syscall per submit. Requires elevated privileges or `CAP_SYS_ADMIN` on older kernels. |
| `IORING_SETUP_IOPOLL` | Polls for completions instead of using interrupts. Only works with O_DIRECT on supported storage. |

If a flag combination is rejected by the kernel, the constructor raises `UringError`. The `detail` field includes the liburing and kernel documentation URLs.

### Synchronous I/O methods

These methods submit one SQE and wait for its CQE before returning. They are a convenient way to run single operations without managing the submission/completion cycle manually.

| Method | Signature | Returns |
|--------|-----------|---------|
| `read` | `read(fd, length, offset=0)` | `bytes` containing the data read |
| `write` | `write(fd, data, offset=0)` | `int` number of bytes written |
| `read_batch` | `read_batch(fd, block_size, blocks, offset=0)` | `bytes` — `blocks × block_size` bytes read contiguously |
| `read_offsets` | `read_offsets(fd, block_size, offsets, offset_bytes=True)` | `bytes` — one block per entry in `offsets`; entries are byte offsets if `offset_bytes=True`, block indices otherwise |

`UringCtx` also exposes synchronous wrappers for a wide range of other io_uring operations: `openat`, `close`, `fsync`, `fallocate`, `statx`, `renameat`, `unlinkat`, `mkdirat`, `send`, `recv`, `accept`, `connect`, `splice`, `tee`, `poll_add`, `symlinkat`, `linkat`, `fadvise`, `madvise`, `getxattr`, `setxattr`, `epoll_ctl`, `socket`, `pipe`, `bind`, `listen`, `openat2`, `ftruncate`, `futex_wait`, `futex_wake`, and more. Each follows the same pattern: submit one operation and wait for its result.

### Asynchronous I/O methods

Use these when you want to submit multiple operations and collect completions in a batch, or when integrating with `asyncio` via `UringAsync`.

**Submission:**

```python
# Submit a read into a bytearray or (ptr, size) tuple from BufferPool
ctx.read_async(fd, buf, offset=0, user_data=0)

# Submit a write from a bytes-like object
ctx.write_async(fd, data, offset=0, user_data=0)

# Submit using a raw pointer (from BufferPool.get_ptr or ctypes allocation)
ctx.read_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)
ctx.write_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)
```

For `read_async` / `write_async` with `bytes`/`bytearray`, the context keeps the buffer referenced until that operation’s CQE is consumed (`wait_completion` / `peek_completion`). For `read_async_ptr` / `write_async_ptr`, you must keep the memory valid until then. Each in-flight `read_async`/`write_async` (non-ptr) must use a **distinct** `user_data` among operations not yet completed.

`user_data` is returned unchanged in the completion so you can correlate completions with submissions.

**Flushing the submission queue:**

```python
ctx.submit()                   # flush the SQ; returns number of operations submitted
ctx.submit_and_wait(wait_nr=1) # flush the SQ and block until wait_nr CQEs are available
```

**Collecting completions:**

```python
user_data, result = ctx.wait_completion()  # blocks until one CQE is available
pair = ctx.peek_completion()               # returns (user_data, result) or None immediately
```

`result` is the return value of the underlying operation: positive means success (e.g. bytes read/written), negative means a kernel errno (e.g. `-errno.ENOENT`).

### Fixed file and buffer registration

Registering file descriptors and buffers with the kernel avoids repeated fd table lookups and buffer pinning on each operation. This matters at high queue depth or in tight loops.

```python
# Register a list of open file descriptors.
# After this, use the list index (0, 1, 2, ...) as file_index in read_fixed/write_fixed.
fds = [os.open("/tmp/a.bin", os.O_RDONLY), os.open("/tmp/b.bin", os.O_RDONLY)]
ctx.register_files(fds)

# Register a list of writable buffers (bytearray or similar mutable contiguous objects).
# bytes is not accepted because it is immutable.
# After this, use the list index as buf_index in read_fixed/write_fixed.
bufs = [bytearray(4096), bytearray(4096)]
ctx.register_buffers(bufs)

# Read using registered fd index 0 and registered buffer index 0
bytes_read = ctx.read_fixed(file_index=0, buf=bufs[0], offset=0, buf_index=0)

# Write from registered buffer index 1 using registered fd index 1
bytes_written = ctx.write_fixed(file_index=1, data=bufs[1], offset=0, buf_index=1)

# Unregister when done
ctx.unregister_files()
ctx.unregister_buffers()
```

Keep the registered `fds` open and the `bufs` objects alive for the entire duration of registration. `UringCtx` holds internal references to registered buffers; `unregister_buffers()` releases them.

### Opcode probe methods

Query the kernel for which io_uring opcodes are supported. Useful before using features that were added in later kernel versions.

```python
ctx.probe_opcode_supported(iou.IORING_OP_SPLICE)  # True or False
ctx.probe_last_op()                                # highest opcode index in the probe
ctx.probe_supported_mask()                         # bytes object; byte i is 1 if opcode i is supported
```

### Properties and lifecycle

```python
ctx.ring_fd    # int — the io_uring completion queue file descriptor (used by UringAsync)

ctx.close()    # destroy the ring; safe to call multiple times
# context manager — close() is called automatically on __exit__
with UringCtx(entries=64) as ctx:
    ...
```

---

## `UringAsync`

`UringAsync` bridges `UringCtx` and `asyncio`. It registers `ctx.ring_fd` with `asyncio.loop.add_reader`. When the kernel signals that a CQE is ready, the reader callback fires and resolves the waiting future — without blocking the event loop thread on a syscall.

**One loop per instance:** The first call to `wait_completion()` records the running event loop. Subsequent calls must run on the same loop; calling from a different loop raises `RuntimeError`.

**Threading:** `UringAsync` is designed for use from the single thread running the event loop. Do not share a `UringCtx` across threads.

```python
from pyuring import UringAsync

async def main():
    with iou.UringCtx(entries=64) as ctx:
        async with UringAsync(ctx) as ua:
            fd = os.open("/tmp/data.bin", os.O_RDONLY)
            buf = bytearray(4096)

            ctx.read_async(fd, buf, user_data=1)
            ctx.submit()

            user_data, result = await ua.wait_completion()
            # result is bytes read, or negative errno

asyncio.run(main())
```

**Cancellation:** If the coroutine is cancelled while awaiting `wait_completion()`, the future is removed from the internal queue and the event loop reader is removed if no other waiters remain. The in-flight kernel operation is not cancelled — its CQE will be silently discarded when it arrives.

**Lifecycle:**
- `ua.close()` removes the loop reader and cancels all pending `wait_completion` futures.
- `close()` does **not** call `ctx.close()`. The `UringCtx` remains open.
- Prefer `async with UringAsync(ctx) as ua:` to ensure cleanup.

**Alternative — thread executor:**

If you cannot use the event loop reader (e.g. in a context where `ring_fd` cannot be watched), run the blocking `wait_completion` in a thread pool:

```python
from pyuring import wait_completion_in_executor

# UringCtx must be created with single_thread_check=False because
# the executor runs wait_completion on a different thread.
ctx = iou.UringCtx(entries=64, single_thread_check=False)
user_data, result = await wait_completion_in_executor(ctx)
```

Cancellation via task cancellation only cancels the outer coroutine; the worker thread may remain blocked until a CQE arrives.

---

## `BufferPool`

`BufferPool` manages a fixed array of native memory buffers. Each slot has an index (0-based) and a size. Use `get_ptr` to get a raw pointer for `read_async` / `write_async`, avoiding Python object allocation per operation.

**Lifetime:** Keep the `BufferPool` alive as long as any in-flight io_uring operation references its memory. Do not call `close()` until all operations using `get_ptr` pointers have completed. After `close()`, all methods raise `UringError`.

```python
with iou.BufferPool.create(initial_count=8, initial_size=4096) as pool:
    # Get the raw pointer and size for slot 0
    ptr, size = pool.get_ptr(0)

    # Submit a read that will write directly into the native buffer
    ctx.read_async(fd, (ptr, size), user_data=0)
    ctx.submit()
    ctx.wait_completion()

    # Read the result back as a Python bytes object
    data = pool.get(0)

    # Resize slot 0 to hold larger data
    pool.resize(0, 8192)
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `BufferPool.create` | `create(initial_count=8, initial_size=4096)` | Class method. Allocates `initial_count` slots, each `initial_size` bytes. |
| `get` | `get(index) -> bytes` | Returns a copy of the buffer contents as `bytes`. |
| `get_ptr` | `get_ptr(index) -> (c_void_p, int)` | Returns the raw pointer and current size of the slot. Pass this tuple directly to `read_async` or `write_async`. |
| `resize` | `resize(index, new_size)` | Reallocates slot `index` to `new_size` bytes. Invalidates any pointer previously returned by `get_ptr` for that slot. |
| `set_size` | `set_size(index, size)` | Changes the logical size without reallocating. `size` must not exceed the current capacity. |
| `close` | `close()` | Frees all native memory. |

---

## Kernel capability probe (module-level)

The module-level probe helpers open a short-lived `UringCtx(entries=8)` on the first call and cache the result for the process lifetime.

```python
from pyuring import get_probe_info, opcode_supported, require_opcode_supported

# IoUringProbeInfo(last_op=int, opcode_mask=bytes)
# opcode_mask[i] == 1 means opcode i is supported
info = iou.get_probe_info()

# Check a single opcode
if iou.opcode_supported(iou.IORING_OP_SPLICE):
    # use splice

# Raise UringError(errno.EOPNOTSUPP) if not supported.
# The error detail includes links to the kernel io_uring documentation.
iou.require_opcode_supported(iou.IORING_OP_SPLICE, "my_function")

# Force re-probe (e.g. after a kernel upgrade without restarting the process)
info = iou.get_probe_info(refresh=True)
```

---

## Constants

All `IORING_SETUP_*`, `IORING_OP_*`, and `IOSQE_*` constants are exported from the package root. Values match Linux UAPI (`linux/io_uring.h`).

```python
import pyuring as iou

# Ring setup flags (pass to UringCtx setup_flags)
iou.IORING_SETUP_IOPOLL
iou.IORING_SETUP_SQPOLL
iou.IORING_SETUP_SQ_AFF
iou.IORING_SETUP_CQSIZE
iou.IORING_SETUP_SINGLE_ISSUER
iou.IORING_SETUP_COOP_TASKRUN
iou.IORING_SETUP_DEFER_TASKRUN
# ... and more

# SQE flags (IOSQE_*)
iou.IOSQE_FIXED_FILE       # use registered file index instead of fd
iou.IOSQE_IO_DRAIN         # wait for all preceding SQEs to complete before this one
iou.IOSQE_IO_LINK          # link this SQE to the next; if this fails, cancel the next
iou.IOSQE_IO_HARDLINK      # like IO_LINK but the next SQE runs even if this one fails
iou.IOSQE_ASYNC            # always execute this operation asynchronously
iou.IOSQE_CQE_SKIP_SUCCESS # suppress CQE on success (still produces CQE on error)

# Opcode numbers (pass to probe_opcode_supported, opcode_supported, etc.)
iou.IORING_OP_NOP
iou.IORING_OP_READ
iou.IORING_OP_WRITE
iou.IORING_OP_READ_FIXED
iou.IORING_OP_WRITE_FIXED
iou.IORING_OP_SPLICE
iou.IORING_OP_TEE
iou.IORING_OP_SEND
iou.IORING_OP_RECV
iou.IORING_OP_SEND_ZC
# ... full list: iou.UAPI_CONSTANT_NAMES
```

To see all exported constant names:
```python
print(iou.UAPI_CONSTANT_NAMES)
```
