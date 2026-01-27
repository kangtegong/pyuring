# Using io_uring in Python (kernel 5.15)

Python doesn't "directly" support io_uring, so the simplest approach is to create a thin wrapper `.so` around **liburing (C)** and call it from Python using `ctypes`.

This repository provides:

- `csrc/uring_wrap.c`: liburing-based io_uring read/write wrapper (synchronous and asynchronous)
- `pyiouring/`: Python package (ctypes bindings)
- `examples/`: Demo and benchmark code
- **Asynchronous read/write API**: Direct use of io_uring's asynchronous features
- **Dynamic buffer size adjustment**: Dynamically adjust read/write buffer sizes at runtime
- **BufferPool**: Buffer pool that can dynamically adjust buffer sizes

## Installation

### Install as Python Package (Recommended)

```bash
# Clone repository
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering

# Install package
pip install -e .
```

### Usage

**Basic file copy:**
```python
import pyiouring

# Copy file
copied = pyiouring.copy_path("/tmp/source.dat", "/tmp/dest.dat")
```

**Copy with dynamic buffer size:**
```python
def adaptive_size(offset, total, default):
    progress = offset / total if total > 0 else 0
    if progress < 0.25:
        return default
    elif progress < 0.5:
        return default * 2
    else:
        return default * 4

copied = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    buffer_size_cb=adaptive_size,
    fsync=True
)
```

**Asynchronous read/write:**
```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # Submit asynchronous read
        buf = bytearray(4096)
        ctx.read_async(fd, buf, offset=0, user_data=1)
        ctx.submit()
        
        # Wait for completion
        user_data, result = ctx.wait_completion()
        print(f"Read {result} bytes")
    finally:
        os.close(fd)
```

**Using dynamic buffer pool:**
```python
with pyiouring.UringCtx(entries=64) as ctx:
    with pyiouring.BufferPool.create(initial_count=4, initial_size=4096) as pool:
        fd = os.open("/tmp/test.dat", os.O_RDONLY)
        try:
            # Dynamically adjust buffer size
            pool.resize(0, 8192)  # 4KB -> 8KB
            buf_ptr, buf_size = pool.get_ptr(0)
            pool.set_size(0, 8192)
            
            # Asynchronous read
            ctx.read_async_ptr(fd, buf_ptr, 8192, offset=0, user_data=1)
            ctx.submit()
            
            user_data, result = ctx.wait_completion()
            data = pool.get(0)  # Get read data
        finally:
            os.close(fd)
```

For detailed installation and usage instructions, see:
- [INSTALLATION.md](INSTALLATION.md): Detailed installation guide
- [USAGE.md](USAGE.md): Usage guide and API reference
- [examples/BENCHMARKS.md](examples/BENCHMARKS.md): Benchmark guide

### Build from Source (Development Mode)

```bash
# Clone repository
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering

# Install dependencies (Option A: Use system library)
sudo apt-get install -y liburing-dev
make

# Or Option B: Use vendored liburing
make fetch-liburing
make

```

## Benchmarks

Synchronous vs asynchronous I/O performance comparison:

```bash
# Basic benchmark
python3 examples/bench_async_vs_sync.py

# See examples/BENCHMARKS.md for detailed usage
```

### 5) Dynamic Buffer Size Adjustment (Runtime)

You can **dynamically adjust** the buffer size at runtime for reading and writing (flushing) to SSD using io_uring.

The `write_newfile_dynamic` function allows you to call a callback function before each write to determine the buffer size:

```python
import pyiouring

def adaptive_size(current_offset, total_bytes, default_block_size):
    """Adjust buffer size based on progress"""
    progress = current_offset / total_bytes
    if progress < 0.25:
        return default_block_size      # First 25%: default size
    elif progress < 0.5:
        return default_block_size * 2  # Next 25%: 2x
    elif progress < 0.75:
        return default_block_size * 4  # Next 25%: 4x
    else:
        return default_block_size * 8  # Last 25%: 8x

# Write file with dynamic buffer size
written = pyiouring.write_newfile_dynamic(
    "/tmp/test.dat",
    total_mb=100,
    block_size=4096,  # Default block size
    qd=256,
    fsync=True,
    buffer_size_cb=adaptive_size,  # Callback function
)
```

### Dynamic Buffer Size Adjustment in Read+Write Copy

You can also dynamically adjust buffer size when copying files from one to another:

```python
import pyiouring

def adaptive_size(current_offset, total_bytes, default_block_size):
    """Adjust buffer size based on progress"""
    progress = current_offset / total_bytes
    if progress < 0.25:
        return default_block_size      # First 25%: default size
    elif progress < 0.5:
        return default_block_size * 2  # Next 25%: 2x
    elif progress < 0.75:
        return default_block_size * 4  # Next 25%: 4x
    else:
        return default_block_size * 8  # Last 25%: 8x (SSD flush efficiency)

# Copy file with dynamic buffer size (read+write)
copied = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=32,
    block_size=65536,  # Default block size (64KB)
    buffer_size_cb=adaptive_size,  # Callback function
    fsync=True,  # Flush to SSD
)
```

Using this feature allows you to:
- **Start with small buffers** to reduce initial latency
- **Gradually increase buffer size** as you progress to improve overall throughput
- **Use large buffers** at the end to improve SSD flush efficiency

## Key Features

### Asynchronous I/O API
- `read_async()`, `write_async()`: Submit asynchronous read/write
- `wait_completion()`, `peek_completion()`: Handle completion
- `submit()`, `submit_and_wait()`: Submit and wait for operations

### Dynamic Buffer Management
- `BufferPool`: Dynamically adjust buffer sizes at runtime
- `resize()`: Reallocate buffer size
- `get()`, `get_ptr()`: Access buffer data

### High-Level API
- `copy_path()`, `copy_path_dynamic()`: File copy
- `write_newfile()`, `write_newfile_dynamic()`: Write new file
- `write_manyfiles()`: Write multiple files simultaneously

## Notes

- Both synchronous and asynchronous APIs are supported.
- Using the asynchronous API allows parallel processing of multiple I/O operations.
- Using `BufferPool` enables efficient memory usage while adjusting buffer sizes at runtime.
