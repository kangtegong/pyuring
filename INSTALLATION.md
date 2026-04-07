# Installation Guide

This guide covers install, build, verification, and first usage for `pyuring`.

## Requirements

- Linux kernel 5.15+
- Python 3.6+
- `gcc`, `make`, `git`

Optional:

- System `liburing-dev` (or use vendored `third_party/liburing`)

## Recommended install

```bash
pip install pyuring
```

## If `pip install -e .` fails

### Option A: install system liburing

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y liburing-dev
```

Fedora/RHEL:

```bash
sudo dnf install liburing-devel
```

Arch:

```bash
sudo pacman -S liburing
```

Then retry:

```bash
pip install -e .
```

### Option B: build vendored liburing manually

```bash
git submodule update --init --recursive
cd third_party/liburing
make
cd ../..
make
mkdir -p pyuring/lib
cp build/liburingwrap.so pyuring/lib/
pip install -e .
```

## Verify installation

```bash
python -c "import pyuring as iou; print(iou.__version__)"
python -c "import pyuring as iou; print(iou.copy.__name__, iou.raw.copy_path.__name__)"
```

## First run

Easy API:

```python
import pyuring as iou

copied = iou.copy("/tmp/source.dat", "/tmp/dest.dat")
written = iou.write("/tmp/new.dat", total_mb=10)
total = iou.write_many("/tmp/out", nfiles=5, mb_per_file=10)
```

Raw API (full native feature set):

```python
import pyuring as iou

copied = iou.raw.copy_path("/tmp/source.dat", "/tmp/dest.dat", qd=32, block_size=1 << 20)
```

## Benchmarks

```bash
python3 examples/bench_async_vs_sync.py
```

More options: [examples/BENCHMARKS.md](examples/BENCHMARKS.md)

## Uninstall

```bash
pip uninstall pyuring
```

Clean build artifacts:

```bash
make clean
```
