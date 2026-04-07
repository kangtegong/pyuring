# Usage Guide

`xk` now has:

- **Easy API** for day-1 usage
- **Raw API** for full control (100% existing feature set preserved)

## Install

```bash
git clone --recursive https://github.com/kangtegong/xk.git
cd xk
git submodule update --init --recursive
pip install -e .
```

---

## Easy API (recommended)

```python
import xk as iou
```

### `copy()`

```python
iou.copy("src.dat", "dst.dat")
iou.copy("src.dat", "dst.dat", mode="safe")
iou.copy("src.dat", "dst.dat", mode="fast")
iou.copy("src.dat", "dst.dat", mode="auto", fsync=True)
```

**Signature**

```python
copy(
    src_path: str,
    dst_path: str,
    *,
    mode: str = "auto",          # "safe" | "fast" | "auto"
    qd: int = 32,
    block_size: int = 1 << 20,
    fsync: bool = False,
    buffer_size_cb = None,       # only for mode="auto"
) -> int
```

### `write()`

```python
iou.write("/tmp/new.dat", total_mb=100)
iou.write("/tmp/new.dat", total_mb=100, mode="safe")
iou.write("/tmp/new.dat", total_mb=100, mode="fast", fsync=True)
```

**Signature**

```python
write(
    dst_path: str,
    *,
    total_mb: int,
    mode: str = "auto",          # "safe" | "fast" | "auto"
    qd: int = 256,
    block_size: int = 4096,
    fsync: bool = False,
    dsync: bool = False,
    buffer_size_cb = None,       # only for mode="auto"
) -> int
```

### `write_many()`

```python
iou.write_many("/tmp/out", nfiles=100, mb_per_file=10)
iou.write_many("/tmp/out", nfiles=100, mb_per_file=10, mode="fast")
```

**Signature**

```python
write_many(
    dir_path: str,
    *,
    nfiles: int,
    mb_per_file: int,
    mode: str = "auto",          # "safe" | "fast" | "auto"
    qd: int = 256,
    block_size: int = 4096,
    fsync_end: bool = False,
) -> int
```

---

## Raw API (full feature set, unchanged)

All native functions/classes remain available:

```python
import xk as iou

iou.raw.copy_path(...)
iou.raw.copy_path_dynamic(...)
iou.raw.write_newfile(...)
iou.raw.write_newfile_dynamic(...)
iou.raw.write_manyfiles(...)

with iou.raw.UringCtx(entries=64) as ctx:
    ...

with iou.raw.BufferPool.create(initial_count=8, initial_size=4096) as pool:
    ...
```

Legacy imports are still supported:

```python
from xk import (
    UringError,
    UringCtx,
    BufferPool,
    copy_path,
    copy_path_dynamic,
    write_newfile,
    write_newfile_dynamic,
    write_manyfiles,
)
```

---

## Raw API reference

### Functions

- `copy_path(src_path, dst_path, *, qd=32, block_size=1048576) -> int`
- `copy_path_dynamic(src_path, dst_path, *, qd=32, block_size=1048576, buffer_size_cb=None, fsync=False) -> int`
- `write_newfile(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False) -> int`
- `write_newfile_dynamic(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False, buffer_size_cb=None) -> int`
- `write_manyfiles(dir_path, *, nfiles, mb_per_file, block_size=4096, qd=256, fsync_end=False) -> int`

### Classes

- `UringCtx(entries=64)`
  - sync: `read`, `write`, `read_batch`, `read_offsets`
  - async: `read_async`, `write_async`, `read_async_ptr`, `write_async_ptr`
  - completion: `submit`, `submit_and_wait`, `wait_completion`, `peek_completion`
- `BufferPool`
  - create: `BufferPool.create(initial_count=8, initial_size=4096)`
  - methods: `resize`, `get`, `get_ptr`, `set_size`, `close`

### Exception

- `UringError`
