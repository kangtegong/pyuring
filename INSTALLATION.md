# Installation Guide

This document explains how to install and build the adaptive_buffering project step by step.

## Table of Contents

1. [Install as Python Package (Recommended)](#install-as-python-package-recommended)
2. [Uninstall](#uninstall)
3. [Build from Source](#build-from-source)
4. [Install Dependencies](#install-dependencies)
5. [Build](#build)
6. [Verify Build](#verify-build)
7. [Simple Tests](#simple-tests)

## Install as Python Package (Recommended)

### 1. Clone Repository


```bash
git clone --recursive https://github.com/kangtegong/pyiouring.git
cd pyiouring
```

**Note**: The `--recursive` option automatically initializes submodules.

### 2. Initialize Submodules (Required)

This repository uses `third_party/liburing` as a Git submodule. You must initialize it before installation:

```bash
# Initialize submodules
git submodule update --init --recursive

# Verify submodule is initialized
ls -la third_party/liburing/
```

**Note**: If you cloned with `--recursive`, this step may be skipped, but it's safe to run it again.

### 3. Build Native Library

The native library must be built before installation. You have two options:

#### Option A: Automatic Build (via pip install)

The `setup.py` will automatically build the library during installation:

```bash
pip install -e .
```

If this fails, proceed to Option B.

#### Option B: Manual Build (Recommended if automatic build fails)

```bash
# 1. Build liburing (if using vendored liburing)
cd third_party/liburing
make
cd ../..

# 2. Build native library
make

# 3. Verify build
ls -la build/liburingwrap.so

# 4. Copy to package directory (if needed)
mkdir -p pyiouring/lib
cp build/liburingwrap.so pyiouring/lib/
```

**Troubleshooting**: If `make` fails with "fetch-liburing" error, the submodule is already initialized. Build directly:

```bash
# Skip fetch-liburing and build directly
mkdir -p build
gcc -O2 -g -Wall -Wextra -fPIC \
    -Ithird_party/liburing/src/include \
    -shared \
    -o build/liburingwrap.so \
    csrc/uring_wrap.c csrc/bench_direct.c \
    third_party/liburing/src/liburing.a
```

### 4. Install Package

#### Install in Development Mode (Recommended)

When developing or modifying source code:

```bash
pip install -e .
```

Or:

```bash
python setup.py develop
```

#### Regular Installation

```bash
pip install .
```

Or:

```bash
python setup.py install
```

### 5. Verify Installation

```bash
python -c "import pyiouring; print(pyiouring.__version__)"
```

### 6. Usage

```python
import pyiouring

# Copy file
copied = pyiouring.copy_path("/tmp/source.dat", "/tmp/dest.dat")

# Write file with dynamic buffer size
def adaptive_size(offset, total, default):
    progress = offset / total if total > 0 else 0
    if progress < 0.25:
        return default
    elif progress < 0.5:
        return default * 2
    else:
        return default * 4

written = pyiouring.write_newfile_dynamic(
    "/tmp/test.dat",
    total_mb=100,
    block_size=4096,
    buffer_size_cb=adaptive_size,
    fsync=True
)
```

For detailed usage examples, see [README.md](README.md).

## Uninstall

To uninstall the package:

```bash
# Uninstall the package
pip uninstall pyiouring
```

**Note**: This only removes the Python package. Build artifacts in `build/` and `third_party/` directories are preserved. To clean them:

```bash
# Clean build artifacts
make clean

# Remove submodule (optional)
rm -rf third_party/liburing
```

## Build from Source

## Getting Started

### 1. Clone Repository

Using SSH:

```bash
git clone git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

Using HTTPS:

```bash
git clone https://github.com/kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

### 2. Initialize Submodules (Required)

This repository manages `third_party/liburing` as a Git submodule. You must initialize submodules after cloning:

```bash
# Initialize and download submodules
git submodule update --init --recursive
```

Or all at once when cloning:

```bash
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

**Note**: `third_party/liburing` is managed as a Git submodule. 
After cloning, initialize with `git submodule update --init --recursive`, 
or download directly with `make fetch-liburing`.

## Install Dependencies

### System Requirements

- Linux kernel 5.15 or higher (io_uring support)
- Python 3.6 or higher
- GCC compiler
- Make
- Git (for submodules)

### Option A: Install liburing-dev on System (Recommended)

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y liburing-dev
```

Fedora/RHEL:

```bash
sudo dnf install liburing-devel
```

Arch Linux:

```bash
sudo pacman -S liburing
```

### Option B: Use Vendored liburing (When No Sudo Access)

If you cannot install `liburing-dev` on the system, you can use the liburing included in the project:

**Step 1: Initialize submodule**

```bash
# Initialize submodule
git submodule update --init --recursive
```

**Step 2: Build liburing**

```bash
# Build liburing
cd third_party/liburing
make
cd ../..
```

**Step 3: Build native library**

```bash
# Build liburingwrap.so
make
```

**Note**: If `make` fails with "fetch-liburing" error because the submodule already exists, you can build directly:

```bash
# Build directly (skip fetch-liburing)
mkdir -p build
gcc -O2 -g -Wall -Wextra -fPIC \
    -Ithird_party/liburing/src/include \
    -shared \
    -o build/liburingwrap.so \
    csrc/uring_wrap.c csrc/bench_direct.c \
    third_party/liburing/src/liburing.a
```

## Build

### Basic Build

```bash
make
```

If the build succeeds, the `build/liburingwrap.so` file will be created.

### Build Options

You can modify the following variables in the Makefile:

```bash
# Change compiler
CC=gcc make

# Change optimization level
CFLAGS="-O3 -g" make

# Debug build
CFLAGS="-O0 -g -DDEBUG" make
```

## Verify Build

Check if the build succeeded:

```bash
ls -lh build/liburingwrap.so
```

Expected output:
```
-rwxr-xr-x 1 user user 123K Jan 23 20:00 build/liburingwrap.so
```

## Simple Tests

After the build completes, you can test with the following commands:

### Dynamic Buffer Size Adjustment Test

```bash
python3 examples/test_dynamic_buffer.py
```

### Run Benchmarks

```bash
# Synchronous vs asynchronous I/O performance comparison
python3 examples/bench_async_vs_sync.py --num-files 20 --file-size-mb 5

# See examples/BENCHMARKS.md for detailed benchmark guide
```

## Additional Information

### Build Artifacts

- `build/liburingwrap.so`: Shared library usable from Python
- `third_party/liburing/src/liburing.a`: Static library (when using vendored build)

### Environment Variables

The following environment variables can be used during build:

- `CC`: Specify compiler (default: `gcc`)
- `CFLAGS`: Compile flags (default: `-O2 -g -Wall -Wextra -fPIC`)
- `LDFLAGS`: Linker flags

Example:
```bash
CC=clang CFLAGS="-O3 -march=native" make
```

### Cleanup

To clean build artifacts:

```bash
make clean
```

This command deletes the `build/` directory. `third_party/liburing` is preserved.
