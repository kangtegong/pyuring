# Installation — pyuring

This guide applies to the **[pyuring](https://github.com/kangtegong/pyuring)** repository: a Python package with a **native extension library** (`liburingwrap.so`) that must be present next to the built wheel/sdist or under `build/` during development.

## What you are installing

| Piece | Purpose |
|-------|---------|
| **`pyuring` (Python)** | `ctypes` bindings, orchestrated helpers, and grouped **`pyuring.direct`** exports |
| **`liburingwrap.so`** | Shared object produced by **`make`** from `csrc/`; links against **liburing** |
| **liburing** | Either **system-installed** (`-luring`) or **vendored** under `third_party/liburing` |

Installing with **`pip install .`** or **`pip install -e .`** runs **`build_ext`**, which invokes **`make`**, copies the `.so` into **`pyuring/lib/`**, and then installs the package.

## Requirements

| Requirement | Notes |
|-------------|--------|
| **Linux** | io_uring must be available; docs assume kernel **5.15+**. |
| **Python** | **3.8+** (`setup.py` / `python_requires`). |
| **Toolchain** | `gcc`, `make`, standard build headers. |
| **liburing** | Development headers **or** a complete vendored tree under `third_party/liburing`. |

## Recommended install (PyPI)

```bash
pip install pyuring
```

You still need **liburing** on the build machine when installing from sdist/source; wheels (if published for your platform) bundle the `.so` inside the package.

## Editable install from a clone

```bash
git clone https://github.com/kangtegong/pyuring.git
cd pyuring
git submodule update --init --recursive
pip install -e .
```

If **`pip install -e .`** fails during the native build, use one of the options below.

### Option A — system liburing headers

Install the development package, then retry **`pip install -e .`**.

| Distribution | Command |
|--------------|---------|
| Debian / Ubuntu | `sudo apt-get update && sudo apt-get install -y liburing-dev` |
| Fedora / RHEL | `sudo dnf install liburing-devel` |
| Arch Linux | `sudo pacman -S liburing` |

### Option B — vendored liburing only (manual sequence)

Build liburing and the wrapper, place the `.so` where the package expects it, then install:

```bash
git submodule update --init --recursive
cd third_party/liburing && make && cd ../..
make
mkdir -p pyuring/lib
cp build/liburingwrap.so pyuring/lib/
pip install -e .
```

The **`Makefile`** skips cloning when **`third_party/liburing/src/include/liburing.h`** already exists (e.g. extracted tarball without `.git`).

## Verify installation

```bash
python -c "import pyuring; print(pyuring.__version__)"
python -c "import pyuring as iou; print(iou.copy.__name__, iou.direct.copy_path.__name__)"
```

Both lines should run without **`ImportError`** or **`UringError`**.

## First use after install

**Orchestrated helpers:**

```python
import pyuring as iou

copied = iou.copy("/tmp/source.dat", "/tmp/dest.dat")
written = iou.write("/tmp/new.dat", total_mb=10)
total = iou.write_many("/tmp/out", nfiles=5, mb_per_file=10)
```

**Direct bindings** (same functions as top-level exports; grouped on **`direct`**):

```python
import pyuring as iou

copied = iou.direct.copy_path(
    "/tmp/source.dat", "/tmp/dest.dat", qd=32, block_size=1 << 20
)
```

API tables: **[USAGE.md](USAGE.md)**.

## Benchmarks and self-tests

```bash
make
python3 examples/test_dynamic_buffer.py
python3 examples/bench_async_vs_sync.py --num-files 10 --file-size-mb 10
```

More options: **[examples/BENCHMARKS.md](examples/BENCHMARKS.md)**.

## Publishing to PyPI

**Do not run `twine upload dist/*`.** Shell globbing includes **directories** under `dist/` (e.g. `manylinux-out/` from tooling), and Twine then fails with:

`InvalidDistribution: Unknown distribution format: 'manylinux-out'`

**Recommended:** use the script (cleans `dist/`, rebuilds, checks, uploads only `pyuring-*.whl` and `pyuring-*.tar.gz`):

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD='pypi-…'   # your API token; do not commit this
./scripts/publish-pypi.sh
```

Optional: `./scripts/publish-pypi.sh --verbose`

**Manual equivalent:**

```bash
rm -rf dist && python3 -m build
python3 -m twine check dist/pyuring-*.whl dist/pyuring-*.tar.gz
python3 -m twine upload dist/pyuring-*.whl dist/pyuring-*.tar.gz
```

## Uninstall

```bash
pip uninstall pyuring
```

Remove local build outputs:

```bash
make clean
```

This does not remove **`third_party/liburing`** artifacts; clean that tree separately if needed.
