# pyuring — API specification

This document describes the public Python API of the [pyuring](https://github.com/kangtegong/pyuring) package. Symbols are loaded from **`liburingwrap.so`** (built from this repository’s C sources). Errors from the native layer raise **`UringError`** (subclass of `RuntimeError`).

## Naming

| Concept | Description |
|---------|-------------|
| **Orchestrated helpers** | Module-level functions **`copy`**, **`write`**, **`write_many`** that forward to the direct bindings with **preset tuning** controlled by **`mode`**. |
| **Direct bindings** | The ctypes-backed functions and classes: available at **package top level**, and grouped on **`pyuring.direct`** for qualified access. **`pyuring.raw`** is an alias of **`pyuring.direct`** (backward compatibility only). |

Unless noted, numeric parameters are passed through to C; invalid combinations may raise **`UringError`** with a negative errno-style message.

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

Context manager wrapping one **`io_uring`** instance from the native library.

### Constructor

| Parameter | Default | Meaning |
|-----------|---------|---------|
| **`lib_path`** | `None` | If `None`, resolves **`liburingwrap.so`** (package `lib/`, then repo `build/`, then system). |
| **`entries`** | `64` | Submission queue size hint for **`uring_create`**. |

### Synchronous methods

| Method | Arguments | Returns | Meaning |
|--------|-----------|---------|---------|
| **`read`** | `fd`, `length`, `offset=0` | `bytes` | Single read at **`offset`**. |
| **`write`** | `fd`, `data` (bytes-like), `offset=0` | `int` | Bytes written count. |
| **`read_batch`** | `fd`, `block_size`, `blocks`, `offset=0` | `bytes` | Contiguous read of **`blocks`** × **`block_size`** bytes. |
| **`read_offsets`** | `fd`, `block_size`, `offsets`, `offset_bytes=True` | `bytes` | One block per entry in **`offsets`**; offsets are byte offsets if **`offset_bytes`**, else block indices. |

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
| **`UringError`** | Native call failed (e.g. queue init, I/O error); message includes errno interpretation where available. |

---

## Install from source (reference)

```bash
git clone --recursive https://github.com/kangtegong/pyuring.git
cd pyuring
git submodule update --init --recursive
pip install -e .
```

See **[INSTALLATION.md](INSTALLATION.md)** for header packages, vendored builds, and troubleshooting.
