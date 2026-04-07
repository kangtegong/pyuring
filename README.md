# pyuring

Python bindings for io_uring (Linux 5.15+) with two API layers:

- **Easy API**: short entrypoints for everyday use (`copy`, `write`, `write_many`)
- **Raw API**: full low-level feature set preserved under `pyuring.raw`

## Install

```bash
pip install pyuring
```

If your environment does not have `liburing` headers installed, install them first:

- Ubuntu/Debian: `sudo apt-get install -y liburing-dev`
- Fedora/RHEL: `sudo dnf install liburing-devel`
- Arch: `sudo pacman -S liburing`

## Quick Start (Easy API)

```python
import pyuring as iou

# 1) Copy one file
copied = iou.copy("/tmp/source.dat", "/tmp/dest.dat")

# 2) Write one file
written = iou.write("/tmp/new.dat", total_mb=100)

# 3) Write many files
total = iou.write_many("/tmp/out", nfiles=10, mb_per_file=100)
```

### Easy API modes

- `mode="safe"`: conservative tuning
- `mode="fast"`: aggressive tuning
- `mode="auto"`: dynamic buffer strategy (default)

```python
iou.copy("a.bin", "b.bin", mode="safe")
iou.copy("a.bin", "b.bin", mode="fast")
iou.copy("a.bin", "b.bin", mode="auto", fsync=True)
```

## Full Feature Access (Raw API)

All original APIs are preserved:

```python
import pyuring as iou

iou.raw.copy_path(...)
iou.raw.copy_path_dynamic(...)
iou.raw.write_newfile(...)
iou.raw.write_newfile_dynamic(...)
iou.raw.write_manyfiles(...)

with iou.raw.UringCtx(entries=64) as ctx:
    ...

with iou.raw.BufferPool.create(initial_count=4, initial_size=4096) as pool:
    ...
```

You can also import symbols directly from the package:

```python
from pyuring import copy_path, write_newfile_dynamic, UringCtx
```

## Documents

- [INSTALLATION.md](INSTALLATION.md): install/build/troubleshooting
- [USAGE.md](USAGE.md): easy + raw API guide and reference
- [examples/BENCHMARKS.md](examples/BENCHMARKS.md): benchmark usage
