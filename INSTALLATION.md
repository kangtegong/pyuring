# Installation — pyuring

This guide applies to the **[pyuring](https://github.com/kangtegong/pyuring)** repository: a Python package with a **native extension library** (`liburingwrap.so`) that must be present next to the built wheel/sdist or under `build/` during development.

## What you are installing

| Piece | Purpose |
|-------|---------|
| **`pyuring` (Python)** | `ctypes` bindings, orchestrated helpers, grouped **`pyuring.direct`** exports, **`IORING_*`** constants, **`UringCtx`** helpers for setup flags / fixed registration / probe |
| **`liburingwrap.so`** | Shared object produced by **`make`** from `csrc/`; links against **liburing**; implements **`uring_create_ex`**, register/unregister files and buffers, fixed read/write, and probe helpers |
| **liburing** | Either **system-installed** (`-luring`) or **vendored** under `third_party/liburing` |

Installing with **`pip install .`** or **`pip install -e .`** runs **`build_ext`**, which invokes **`make`**, copies the `.so` into **`pyuring/lib/`**, and then installs the package.

## Binary wheels (manylinux) and linking

Official **manylinux** wheels (built in CI with **[cibuildwheel](https://github.com/pypa/cibuildwheel)**) clone **[liburing](https://github.com/axboe/liburing)** into **`third_party/liburing`**, build **`liburing.a`**, and link the wrapper as **`liburingwrap.so`** against that archive. **`ldd`** on that **`liburingwrap.so`** shows only **`libc`** (and the dynamic loader), not **`liburing.so`** — so end users **do not** install a separate liburing package for those wheels.

| Build / install path | liburing usage | Needs **`liburing.so`** at runtime? |
|----------------------|----------------|-------------------------------------|
| **manylinux wheel** from CI | static archive → linked into **`liburingwrap.so`** | **No** |
| **sdist** or **editable** build **without** vendored headers | **`Makefile`** uses **`-luring`** (system) | **Yes** (distro **`liburing`** / SONAME on the loader path) |
| **sdist** or **editable** build **with** vendored **`third_party/liburing`** (headers + **`liburing.a`**) | same as wheels | **No** |

### Wheel platform tags (reference)

Repair is done by **auditwheel** inside cibuildwheel; exact **`manylinux_*`** glibc tags depend on the tool version and base image.

| Artifact | Typical arch | Default CI (`ubuntu-latest`) |
|----------|--------------|------------------------------|
| **`manylinux_*_x86_64`** | 64-bit x86 | Build locally with **`cibuildwheel .`** (Docker required); CI is optional. |
| **`manylinux_*_aarch64`** | 64-bit ARM | **No** unless you set e.g. **`CIBW_ARCHS_LINUX=aarch64`** (QEMU) or use an aarch64 runner. |
| **`musllinux_*`** | musl-based Linux | **Not** built by default (Alpine liburing build path is still optional); install from **sdist** or use glibc wheels. |

To build wheels locally (Docker required): **`pip install cibuildwheel`** then **`cibuildwheel .`** from the repo root; wheels appear under **`wheelhouse/`**. **`pyproject.toml`** pins **manylinux_2_28** images (not manylinux2014): current liburing needs newer kernel UAPI headers than CentOS 7-era manylinux2014 provides.

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

For **sdist** or **source** installs you need a toolchain and **liburing** (system headers or a vendored **`third_party/liburing`** tree) on the **build** machine. **Prebuilt manylinux wheels** bundle **`liburingwrap.so`** built with vendored static liburing — no separate liburing package is required at install time on supported glibc **x86_64** Linux.

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
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 examples/bench_async_vs_sync.py --num-files 10 --file-size-mb 10
```

**Unit tests** under **`tests/`** exercise **`UringCtx`** ring setup flags, **`IORING_REGISTER_PROBE`**-backed opcode queries, and **`register_files`** / **`register_buffers`** with **`read_fixed`** / **`write_fixed`**. Some combinations (e.g. **`IORING_SETUP_SINGLE_ISSUER`** + **`IORING_SETUP_COOP_TASKRUN`**) are **skipped** if the running kernel refuses those flags—this is expected on older or restricted environments.

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

**Manual equivalent:** PyPI **rejects** wheels tagged `linux_x86_64` (not `manylinux_*` / `musllinux_*`). Build audited wheels with **cibuildwheel** (see **Binary wheels** above), copy **`wheelhouse/*.whl`** into **`dist/`**, then run **`./scripts/publish-pypi.sh`**, which uploads the sdist and any **`manylinux`/`musllinux`** wheels.

```bash
rm -rf dist && python3 -m build
# Optional: add cibuildwheel-produced wheels to dist/ before upload
python3 -m twine check dist/pyuring-*.tar.gz  # add dist/*.whl when present
python3 -m twine upload dist/pyuring-*.tar.gz
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
