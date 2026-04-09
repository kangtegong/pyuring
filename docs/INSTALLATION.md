# Installation

**Requirements:** Linux kernel 5.15+, Python 3.8+, gcc and make (for source builds)

---

## Install from PyPI (recommended)

```bash
pip install pyuring
```

On glibc x86\_64 Linux, pip installs a prebuilt manylinux wheel. That wheel includes a statically-linked `liburingwrap.so`, so no separate liburing package is required at runtime.

On other platforms (ARM, musl libc, etc.), pip will fall back to building from the sdist. In that case, follow the source build instructions below.

---

## Build from source

### 1. Clone and initialize submodules

```bash
git clone https://github.com/kangtegong/pyuring.git
cd pyuring
git submodule update --init --recursive
```

The `third_party/liburing` submodule contains the liburing source tree. You can either use this vendored copy or a system-installed liburing.

### 2. Provide liburing headers

Choose one of the two options:

**Option A — system liburing (simpler)**

Install the development package for your distribution:

```bash
# Debian / Ubuntu
sudo apt-get install liburing-dev

# Fedora / RHEL
sudo dnf install liburing-devel

# Arch Linux
sudo pacman -S liburing
```

Then run:
```bash
pip install -e .
```

**Option B — vendored liburing (no system package needed)**

Build liburing from the submodule, then build and install pyuring:

```bash
cd third_party/liburing && make && cd ../..
make
pip install -e .
```

The `Makefile` detects the vendored headers automatically when `third_party/liburing/src/include/liburing.h` exists.

---

## How liburing is linked

| Install method | liburing linking | Needs liburing.so at runtime? |
|----------------|-----------------|-------------------------------|
| PyPI manylinux wheel | statically linked into `liburingwrap.so` | No |
| Source build with system liburing | dynamically linked (`-luring`) | Yes — liburing must be on the dynamic linker path |
| Source build with vendored liburing | statically linked | No |

If you built with dynamic linking and later move the `.so` to a machine without liburing installed, the import will fail with a linker error. Use the vendored build or the PyPI wheel for portable installs.

---

## Verify the installation

```bash
python -c "import pyuring; print(pyuring.__version__)"
```

A quick functional check:

```python
import pyuring as iou

# Check that the native library loaded and io_uring is available on this kernel
info = iou.get_probe_info()
print(f"io_uring probe: last_op={info.last_op}, supported opcodes={sum(info.opcode_mask)}")
```

---

## Development build notes

When working in a cloned repo, `make` by itself builds `liburingwrap.so` into `build/` and copies it to `pyuring/lib/`. After that, `PYTHONPATH=. python3 ...` will pick up the freshly built library without a `pip install` step.

```bash
make
PYTHONPATH=. python3 -c "import pyuring; print(pyuring.__version__)"
```

If you reinstall with `pip install -e .`, the build step runs automatically via `setup.py`.

---

## Uninstall

```bash
pip uninstall pyuring

# Remove build artifacts from a source checkout
make clean
```

`make clean` does not touch `third_party/liburing`. To clean the vendored liburing build as well:

```bash
cd third_party/liburing && make clean
```
