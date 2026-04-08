# pyuring — API specification

This document describes the public Python API of the [pyuring](https://github.com/kangtegong/pyuring) package. Symbols are loaded from **`liburingwrap.so`** (built from this repository’s C sources). Errors from the native layer raise **`UringError`**, a subclass of **`OSError`**: use **`exc.errno`** (and optionally **`exc.operation`**) for programmatic handling.

## Errors and messages

| Field / behavior | Meaning |
|------------------|---------|
| **`errno`** | Kernel-style errno (same meaning as in **`os`**, **`OSError`**). |
| **`operation`** | Which ctypes wrapper failed (e.g. **`"uring_read_fixed_sync"`**, **`"uring_create_ex"`**). |
| **`detail`** | Optional multi-line hint (e.g. search paths when **`liburingwrap.so`** is missing). |
| **String form** | **`{operation}: {strerror}`**, plus **`detail`** when present. |

## Recommended patterns

- **Fixed files / buffers:** Keep FDs and mutable buffers (e.g. **`bytearray`**) alive for the whole time they are registered or used in-flight. Call **`unregister_files`** / **`unregister_buffers`** (or **`close()`** on **`UringCtx`**) when done.
- **Context managers:** Prefer **`with UringCtx(...) as ctx:`** and **`with BufferPool.create(...) as pool:`** so the ring and pool are torn down reliably.
- **Branching on failure:** `except UringError as e:` then **`if e.errno == errno.EEXIST:`** (etc.), not string parsing.

## asyncio (`pyuring.aio`)

Import: **`from pyuring.aio import UringAsync, wait_completion_in_executor`** (also re-exported from **`pyuring`**).

| Symbol | Role |
|--------|------|
| **`UringCtx.ring_fd`** | Kernel fd for the completion queue; **`UringAsync`** registers it with **`asyncio.loop.add_reader`**. |
| **`UringAsync(ctx)`** | **`async def wait_completion() -> (user_data, result)`** — same contract as **`UringCtx.wait_completion`**, integrated with the running event loop. First use pins the **current** **`asyncio`** loop; using another loop later raises **`RuntimeError`**. |
| **`wait_completion_in_executor(ctx, executor=None)`** | **`loop.run_in_executor(executor, ctx.wait_completion)`** — thread-based; cancellation does not unblock a blocked worker thread. |

**Lifecycle**

- Prefer **`async with UringAsync(ctx) as ua:`** or call **`ua.close()`** when done; that removes the reader and cancels pending **`wait_completion`** futures. It does **not** close **`ctx`**.
- Do not **`close()`** the **`UringCtx`** while coroutines still **`await ua.wait_completion()`**; completions may still be delivered or errors may surface.

**GIL, threads, buffers**

- **`UringAsync`** and **`UringCtx`** are intended for **one thread** — the thread that runs the **`asyncio`** event loop. Do not share a **`UringCtx`** across threads.
- **`read_async`** / **`write_async`** retain kernel references to buffer memory until the matching completion is returned; keep **`bytearray`** / **`BufferPool`** views alive until that **`await`**.

## Naming

| Concept | Description |
|---------|-------------|
| **Orchestrated helpers** | Module-level functions **`copy`**, **`write`**, **`write_many`** that forward to the direct bindings with **preset tuning** controlled by **`mode`**. |
| **Direct bindings** | The ctypes-backed functions and classes: available at **package top level**, and grouped on **`pyuring.direct`** for qualified access. **`pyuring.raw`** is an alias of **`pyuring.direct`** (backward compatibility only). |

Unless noted, numeric parameters are passed through to C; invalid combinations may raise **`UringError`** with a matching **`errno`** (see **Errors and messages** above).

---

## Orchestrated helpers

### `copy`

| Item | Specification |
|------|-----------------|
| **Signature** | `copy(src_path, dst_path, *, mode="auto", qd=32, block_size=1<<20, fsync=False, buffer_size_cb=None) -> int` |
| **Return value** | Number of bytes copied (as reported by the native implementation). |
| **`mode`** | `"safe"` — caps `qd` at 16 and `block_size` at 1 MiB. `"fast"` — raises `qd` to at least 64 and `block_size` to at least 1 MiB. `"auto"` — uses **`copy_path_dynamic`** with default adaptive **`buffer_size_cb`** unless **`buffer_size_cb`** is supplied. |
| **`qd`** | Queue depth (tuned by **`mode`** before use). |
| **`block_size`** | Default block size in bytes (tuned by **`mode`**). |
| **`fsync`** | Passed through when the dynamic path is used (`mode="auto"`). |
| **`buffer_size_cb`** | Optional `(offset, total_bytes, default_block_size) -> int`; used only when **`mode=="auto"`**. |

### `write`

| Item | Specification |
|------|-----------------|
| **Signature** | `write(dst_path, *, total_mb, mode="auto", qd=256, block_size=4096, fsync=False, dsync=False, buffer_size_cb=None) -> int` |
| **Return value** | Bytes written (native report). |
| **`mode`** | `"safe"` — caps `qd` at 128 and `block_size` at 4096. `"fast"` — `qd` at least 256, `block_size` at least 64 KiB. `"auto"` — **`write_newfile_dynamic`** with default adaptive callback unless **`buffer_size_cb`** is set. |
| **`total_mb`** | Total size to write, in mebibytes (MiB). |
| **`fsync` / `dsync`** | Passed to the underlying native write helpers. |
| **`buffer_size_cb`** | Same shape as for **`copy`**; only for **`mode=="auto"`**. |

### `write_many`

| Item | Specification |
|------|-----------------|
| **Signature** | `write_many(dir_path, *, nfiles, mb_per_file, mode="auto", qd=256, block_size=4096, fsync_end=False) -> int` |
| **Return value** | Total bytes written across files. |
| **`mode`** | Adjusts **`qd`** and **`block_size`** like **`write`** (no separate dynamic path; always **`write_manyfiles`**). |
| **`nfiles` / `mb_per_file`** | Count and per-file size in MiB. |
| **`fsync_end`** | Native end-of-run fsync flag. |

---

## Direct bindings — module-level functions

These names are importable from `pyuring` and are also attributes of **`pyuring.direct`**.

### File pipeline (C-side io_uring)

| Function | Parameters (keyword-only after paths) | Returns | Notes |
|----------|----------------------------------------|---------|--------|
| **`copy_path`** | `qd=32`, `block_size=1<<20` | `int` | Copy **`src_path`** → **`dst_path`** in the native pipeline. |
| **`copy_path_dynamic`** | `qd=32`, `block_size=1<<20`, `buffer_size_cb=None`, `fsync=False` | `int` | Per-chunk size from optional callback `(current_offset, total_bytes, default_block_size) -> int`. |
| **`write_newfile`** | `total_mb`, `block_size=4096`, `qd=256`, `fsync=False`, `dsync=False` | `int` | Create **`dst_path`** and fill with sequential writes in C. |
| **`write_newfile_dynamic`** | Same as **`write_newfile`** plus `buffer_size_cb=None` | `int` | Dynamic per-write size via callback (same callback shape as **`copy_path_dynamic`**). |
| **`write_manyfiles`** | `nfiles`, `mb_per_file`, `block_size=4096`, `qd=256`, `fsync_end=False` | `int` | Writes **`nfiles`** under **`dir_path`**. |

Path arguments are `str`; they are encoded for the native layer.

---

## `UringCtx`

Context manager wrapping one **`io_uring`** instance from the native library. The native side uses **`io_uring_queue_init_params`** (not only the zero-flags **`io_uring_queue_init`** path).

### Constructor

| Parameter | Default | Meaning |
|-----------|---------|---------|
| **`lib_path`** | `None` | If `None`, resolves **`liburingwrap.so`** (package `lib/`, then repo `build/`, then system). |
| **`entries`** | `64` | Submission queue size hint. |
| **`setup_flags`** | `0` | Bit mask of **`IORING_SETUP_*`** flags (see **Exported constants** below). Passed to **`io_uring_params.flags`**. |
| **`sq_thread_cpu`** | `-1` | If `>= 0`, passed as **`sq_thread_cpu`** when relevant (e.g. with **`IORING_SETUP_SQPOLL`** / **`IORING_SETUP_SQ_AFF`**). |
| **`sq_thread_idle`** | `0` | Milliseconds for SQPOLL idle behaviour when applicable; non-zero or SQPOLL may set **`sq_thread_idle`**. |

Some flag combinations require a recent kernel or extra privileges (e.g. **`IORING_SETUP_SQPOLL`**). Unsupported combinations fail at construction with **`UringError`**.

### Exported constants (package level)

Opcode and setup values match the Linux UAPI (`linux/io_uring.h`). Useful with **`probe_opcode_supported`** and **`UringCtx(..., setup_flags=...)`**.

| Names (examples) | Role |
|--------------------|------|
| **`IORING_SETUP_IOPOLL`**, **`IORING_SETUP_SQPOLL`**, **`IORING_SETUP_SQ_AFF`**, **`IORING_SETUP_COOP_TASKRUN`**, **`IORING_SETUP_SINGLE_ISSUER`**, **`IORING_SETUP_DEFER_TASKRUN`**, … | Ring creation flags. |
| **`IORING_OP_NOP`**, **`IORING_OP_READ`**, **`IORING_OP_WRITE`**, **`IORING_OP_READ_FIXED`**, **`IORING_OP_WRITE_FIXED`**, **`IORING_OP_READV`**, **`IORING_OP_WRITEV`**, … | Opcode numbers for probing. |

The full set is defined in **`pyuring._native`** and re-exported from **`pyuring`**.

### Synchronous methods

| Method | Arguments | Returns | Meaning |
|--------|-----------|---------|---------|
| **`read`** | `fd`, `length`, `offset=0` | `bytes` | Single read at **`offset`**. |
| **`write`** | `fd`, `data` (bytes-like), `offset=0` | `int` | Bytes written count. |
| **`read_batch`** | `fd`, `block_size`, `blocks`, `offset=0` | `bytes` | Contiguous read of **`blocks`** × **`block_size`** bytes. |
| **`read_offsets`** | `fd`, `block_size`, `offsets`, `offset_bytes=True` | `bytes` | One block per entry in **`offsets`**; offsets are byte offsets if **`offset_bytes`**, else block indices. |

### Registered files and buffers (kernel registration)

These map to **`io_uring_register_files`**, **`io_uring_register_buffers`**, and fixed **`READ_FIXED`** / **`WRITE_FIXED`** submissions with **`IOSQE_FIXED_FILE`**. Intended for workloads that reuse the same FDs and memory regions at high queue depth.

| Method | Arguments | Returns | Meaning |
|--------|-----------|---------|---------|
| **`register_files`** | `fds` — non-empty sequence of `int` | — | Registers open file descriptors; use index **`0 .. len(fds)-1`** as the file slot in **`read_fixed`** / **`write_fixed`**. |
| **`unregister_files`** | — | — | **`io_uring_unregister_files`**. |
| **`register_buffers`** | `buffers` — non-empty sequence of **writable** contiguous buffers (e.g. **`bytearray`**) | — | Each element becomes a registered buffer index **`0 .. n-1`**. **`bytes`** is rejected (must be mutable). The implementation pins memory via **`ctypes`**; keep those objects alive while registered (the context holds internal references). |
| **`unregister_buffers`** | — | — | **`io_uring_unregister_buffers`**; clears pinned references. |
| **`read_fixed`** | `file_index`, `buf` (**`bytearray`**), `offset`, `buf_index` | `int` | Bytes read into **`buf`** using registered file **`file_index`** and registered buffer **`buf_index`**. |
| **`write_fixed`** | `file_index`, `data` (**`bytearray`**), `offset`, `buf_index` | `int` | Writes from the same memory region that was registered at **`buf_index`** (typical pattern: fill the registered buffer, then submit). |

### Opcode probe

| Method | Arguments | Returns | Meaning |
|--------|-----------|---------|---------|
| **`probe_opcode_supported`** | `opcode` (`int`) | `bool` | **`True`** if the kernel reports the opcode as supported (via **`io_uring_get_probe_ring`** / probe ops). |
| **`probe_last_op`** | — | `int` | Highest opcode index described by the probe (**`io_uring_probe.last_op`**). |
| **`probe_supported_mask`** | — | `bytes` | Length **`probe_last_op() + 1`**; byte **`i`** is **`1`** if opcode **`i`** is supported, else **`0`**. |

### Asynchronous methods

| Method | Arguments | Returns / behavior |
|--------|-----------|---------------------|
| **`read_async`** | `fd`, `buf`, `offset=0`, `user_data=0` | Submits read; **`buf`** may be `bytes`/`bytearray` or `(ptr, size)` tuple from **`BufferPool.get_ptr`**. |
| **`read_async_ptr`** | `fd`, `buf_ptr`, `buf_len`, `offset=0`, `user_data=0` | Submits read using a raw address / `c_void_p`. |
| **`write_async`** | `fd`, `data`, `offset=0`, `user_data=0` | Submits write for bytes-like **`data`**. |
| **`write_async_ptr`** | `fd`, `buf_ptr`, `buf_len`, `offset=0`, `user_data=0` | Submits write from raw buffer. |
| **`wait_completion`** | — | `(user_data: int, result: int)` blocking. |
| **`peek_completion`** | — | Same tuple or `None` if none ready. |
| **`submit`** | — | `int` — number of operations submitted (or native success code per binding). |
| **`submit_and_wait`** | `wait_nr=1` | `int` — submit/wait combined (native semantics). |

### Lifecycle

| Method | Meaning |
|--------|---------|
| **`close()`** | Destroys the ring; safe if already closed. |
| **`__enter__` / `__exit__`** | Context manager: **`close()`** on exit. |

---

## `BufferPool`

Fixed pool of buffers allocated in native code; use with **`read_async`** / **`write_async`** via **`get_ptr`**.

### Construction

| Call | Meaning |
|------|---------|
| **`BufferPool.create(initial_count=8, initial_size=4096)`** | Class method; returns a **`BufferPool`** instance. |

### Methods

| Method | Arguments | Returns / meaning |
|--------|-----------|-------------------|
| **`resize`** | `index`, `new_size` | Resize slot **`index`**. |
| **`get`** | `index` | `bytes` copy of buffer **`index`**. |
| **`get_ptr`** | `index` | `(c_void_p, length)` for zero-copy style use with **`read_async`**. |
| **`set_size`** | `index`, `size` | Logical size without exceeding capacity. |
| **`close`** | — | Frees the pool. |
| **`__enter__` / `__exit__`** | — | Context manager. |

---

## Exceptions

| Type | When |
|------|------|
| **`UringError`** | Subclass of **`OSError`**. Native call failed (e.g. queue init, I/O). **`errno`** is set; **`operation`** names the wrapper; see **Errors and messages** at the top of this file. |

---

## Install from source (reference)

```bash
git clone --recursive https://github.com/kangtegong/pyuring.git
cd pyuring
git submodule update --init --recursive
pip install -e .
```

See **[INSTALLATION.md](INSTALLATION.md)** for header packages, vendored builds, and troubleshooting.
