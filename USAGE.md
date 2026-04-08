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
- **`UringCtx` threading:** Use a single instance from **one** Python thread (the creator) unless you pass **`single_thread_check=False`** and enforce mutual exclusion yourself. The default raises **`UringError`** if another thread calls into the context. For **`wait_completion_in_executor`**, build **`UringCtx(..., single_thread_check=False)`** so the worker thread can call **`wait_completion`**.
- **After `UringCtx.close()`:** Any further use raises **`UringError`** with a clear “closed” **`detail`** (not a silent crash from ctypes).
- **`BufferPool` / pinned memory:** Keep the **`BufferPool`** object alive while any SQE may still reference pool memory; do not **`close()`** the pool until in-flight ops using **`get_ptr`** / **`get`** are complete. After **`close()`**, methods raise **`UringError`**.
- **Context managers:** Prefer **`with UringCtx(...) as ctx:`** and **`with BufferPool.create(...) as pool:`** so the ring and pool are torn down reliably.
- **Branching on failure:** `except UringError as e:` then **`if e.errno == errno.EEXIST:`** (etc.), not string parsing.

## asyncio (`pyuring.aio`)

Import: **`from pyuring.aio import UringAsync, wait_completion_in_executor`** (also re-exported from **`pyuring`**).

| Symbol | Role |
|--------|------|
| **`UringCtx.ring_fd`** | Kernel fd for the completion queue; **`UringAsync`** registers it with **`asyncio.loop.add_reader`**. |
| **`UringAsync(ctx)`** | **`async def wait_completion() -> (user_data, result)`** — same contract as **`UringCtx.wait_completion`**, integrated with the running event loop. First use pins the **current** **`asyncio`** loop; using another loop later raises **`RuntimeError`**. |
| **`wait_completion_in_executor(ctx, executor=None)`** | **`loop.run_in_executor(executor, ctx.wait_completion)`** — thread-based; cancellation does not unblock a blocked worker thread. Use **`UringCtx(..., single_thread_check=False)`** so the executor thread may call **`wait_completion`**. |

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
| **Signature** | `copy(..., *, sync_policy="default", progress_cb=None, ...)` — see full parameters below. |
| **Return value** | Number of bytes copied (as reported by the native implementation). |
| **`mode`** | `"safe"` — caps `qd` at 16 and `block_size` at 1 MiB. `"fast"` — raises `qd` to at least 64 and `block_size` to at least 1 MiB. `"auto"` — uses **`copy_path_dynamic`** with default adaptive **`buffer_size_cb`** unless **`buffer_size_cb`** is supplied. |
| **`qd`** | Queue depth (tuned by **`mode`** before use). |
| **`block_size`** | Default block size in bytes (tuned by **`mode`**). |
| **`fsync`** | When **`sync_policy`** is **`"default"`**, passed through to the C pipeline (end **`fsync`** on the destination). |
| **`sync_policy`** | **`"default"`** — use **`fsync`**. **`"none"`** — no end **`fsync`**. **`"end"`** — always end **`fsync`** (overrides **`fsync=False`**). |
| **`buffer_size_cb`** | Optional `(offset, total_bytes, default_block_size) -> int`; **`mode="auto"`** or when **`progress_cb`** / non-default **`sync_policy`** forces the dynamic C path. |
| **`progress_cb`** | Optional `(done_bytes, total_bytes) -> bool`. Invoked after each completed destination write; return **`True`** to stop cooperatively (**`UringError`**, **`errno.ECANCELED`**). May **`sleep`** for throttling. Not available on the minimal static path (no progress / default sync / **`mode`** other than **`auto`** without extras → uses **`copy_path`** only). |

### `write`

| Item | Specification |
|------|-----------------|
| **Signature** | `write(..., *, sync_policy="default", progress_cb=None, ...)` |
| **Return value** | Bytes written (native report). |
| **`mode`** | `"safe"` — caps `qd` at 128 and `block_size` at 4096. `"fast"` — `qd` at least 256, `block_size` at least 64 KiB. `"auto"` — **`write_newfile_dynamic`** with default adaptive callback unless **`buffer_size_cb`** is set. |
| **`total_mb`** | Total size to write, in mebibytes (MiB). |
| **`fsync` / `dsync`** | When **`sync_policy`** is **`"default"`**, passed to the underlying native write helpers. |
| **`sync_policy`** | **`"default"`** — use **`fsync`** / **`dsync`**. **`"none"`** — neither end **`fsync`** nor **`RWF_DSYNC`**. **`"end"`** — end **`fsync`** only. **`"data"`** — **`RWF_DSYNC`** per write. **`"end_and_data"`** — both. |
| **`buffer_size_cb`** | Same shape as for **`copy`**; used when **`mode=="auto"`** or when **`progress_cb`** / non-default **`sync_policy`** selects the dynamic path. |
| **`progress_cb`** | Same contract as **`copy`**. |

### `write_many`

| Item | Specification |
|------|-----------------|
| **Signature** | `write_many(..., *, fsync_end=False, sync_policy="default", ...)` |
| **Return value** | Total bytes written across files. |
| **`mode`** | Adjusts **`qd`** and **`block_size`** like **`write`** (no separate dynamic path; always **`write_manyfiles`**). |
| **`nfiles` / `mb_per_file`** | Count and per-file size in MiB. |
| **`fsync_end`** | When **`sync_policy`** is **`"default"`**, passed as the native end-of-run fsync flag. |
| **`sync_policy`** | Same **`"default"`** / **`"none"`** / **`"end"`** interpretation as **`copy`** for the end-fsync behaviour. |

### Kernel probe cache (opcode support)

| Symbol | Role |
|--------|------|
| **`get_probe_info()`** | Returns **`IoUringProbeInfo`** (**`last_op`**, **`opcode_mask`**) using a short-lived **`UringCtx`**; result is cached for the process unless **`refresh=True`**. |
| **`opcode_supported(opcode)`** | **`True`** if the cached mask reports the opcode. |
| **`require_opcode_supported(opcode)`** | Raises **`UringError(EOPNOTSUPP, ...)`** with a detail line pointing at **`IO_URING_KERNEL_DOC`** if the opcode is missing. |

Constants **`IO_URING_KERNEL_DOC`** and **`LIBURING_PROJECT`** are stable URLs for error text and docs. **`UringCtx`** construction failure (**`uring_create_ex`**) includes the same links when **`io_uring_queue_init_params`** rejects the request.

---

## Direct bindings — module-level functions

These names are importable from `pyuring` and are also attributes of **`pyuring.direct`**.

### File pipeline (C-side io_uring)

| Function | Parameters (keyword-only after paths) | Returns | Notes |
|----------|----------------------------------------|---------|--------|
| **`copy_path`** | `qd=32`, `block_size=1<<20` | `int` | Copy **`src_path`** → **`dst_path`** in the native pipeline. |
| **`copy_path_dynamic`** | `qd=32`, `block_size=1<<20`, `buffer_size_cb=None`, `fsync=False`, `progress_cb=None` | `int` | Per-chunk size from optional callback `(current_offset, total_bytes, default_block_size) -> int`. Optional **`progress_cb`**: `(done_bytes, total_bytes) -> bool` (return **`True`** to cancel with **`ECANCELED`**). |
| **`write_newfile`** | `total_mb`, `block_size=4096`, `qd=256`, `fsync=False`, `dsync=False` | `int` | Create **`dst_path`** and fill with sequential writes in C. |
| **`write_newfile_dynamic`** | Same as **`write_newfile`** plus `buffer_size_cb=None`, `progress_cb=None` | `int` | Dynamic per-write size via callback (same callback shape as **`copy_path_dynamic`**). Optional **`progress_cb`** as for **`copy_path_dynamic`**. |
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
| **`single_thread_check`** | `True` | If **`True`**, operations from a thread other than the constructor thread raise **`UringError`**. Set **`False`** only if you serialize access (e.g. **`wait_completion_in_executor`**). |

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
