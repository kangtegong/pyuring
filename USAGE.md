# Usage Guide

This document explains how to use the `pyiouring` package.

## Installation

First, you need to install the package:

```bash
# Clone repository
git clone --recursive git@github.com:kangtegong/pyiouring.git
cd pyiouring

# Install package
pip install -e .
```

For detailed installation instructions, see [INSTALLATION.md](INSTALLATION.md).

## Basic Usage

### Import Package

```python
import pyiouring
```

### File Copy

Simplest usage:

```python
# Copy file with default settings
copied_bytes = pyiouring.copy_path("/tmp/source.dat", "/tmp/dest.dat")
print(f"Copied {copied_bytes:,} bytes")
```

With options:

```python
copied_bytes = pyiouring.copy_path(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=64,           # Queue depth
    block_size=65536  # Block size (64KB)
)
```

### File Copy with Dynamic Buffer Size Adjustment

Adjust buffer size dynamically based on progress:

```python
def adaptive_buffer_size(current_offset, total_bytes, default_block_size):
    """Adjust buffer size based on progress"""
    if total_bytes == 0:
        return default_block_size
    
    progress = current_offset / total_bytes
    
    if progress < 0.25:
        return default_block_size      # First 25%: default size
    elif progress < 0.5:
        return default_block_size * 2  # Next 25%: 2x
    elif progress < 0.75:
        return default_block_size * 4  # Next 25%: 4x
    else:
        return default_block_size * 8  # Last 25%: 8x

# Copy with dynamic buffer size
copied_bytes = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=32,
    block_size=65536,
    buffer_size_cb=adaptive_buffer_size,
    fsync=True  # Flush to SSD
)
```

### File Writing

Create and write a new file:

```python
# Basic file write
written_bytes = pyiouring.write_newfile(
    "/tmp/newfile.dat",
    total_mb=100,      # 100MB
    block_size=4096,   # 4KB blocks
    qd=256,            # Queue depth
    fsync=True         # fsync at the end
)
```

Write with dynamic buffer size:

```python
def linear_increase(offset, total, default):
    """Linearly increase buffer size"""
    if total == 0:
        return default
    progress = offset / total
    multiplier = 1.0 + (progress * 15.0)  # 1x ~ 16x
    return int(default * multiplier)

written_bytes = pyiouring.write_newfile_dynamic(
    "/tmp/newfile.dat",
    total_mb=100,
    block_size=4096,
    qd=256,
    fsync=True,
    buffer_size_cb=linear_increase
)
```

### Using UringCtx (Advanced)

For more fine-grained control:

```python
import os
import pyiouring

# Create context
with pyiouring.UringCtx(entries=64) as ctx:
    # Open file
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # Synchronous read
        data = ctx.read(fd, length=4096, offset=0)
        print(f"Read {len(data)} bytes")
        
        # Batch read
        data = ctx.read_batch(fd, block_size=4096, blocks=10, offset=0)
        print(f"Read {len(data)} bytes in batch")
        
        # Read from multiple offsets
        offsets = [0, 4096, 8192, 12288]
        data = ctx.read_offsets(fd, block_size=4096, offsets=offsets)
        print(f"Read {len(data)} bytes from {len(offsets)} offsets")
    finally:
        os.close(fd)
```

### Asynchronous Read/Write API

To directly use io_uring's asynchronous features:

```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # Submit asynchronous read
        buf = bytearray(4096)
        ctx.read_async(fd, buf, offset=0, user_data=1)
        
        # Submit operations
        ctx.submit()
        
        # Wait for completion (blocking)
        user_data, result = ctx.wait_completion()
        print(f"Read {result} bytes (user_data={user_data})")
        
        # Or check non-blocking
        completion = ctx.peek_completion()
        if completion:
            user_data, result = completion
            print(f"Read {result} bytes")
    finally:
        os.close(fd)
```

Asynchronous write:

```python
with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        # Submit multiple write operations
        data1 = b"Chunk 1"
        data2 = b"Chunk 2"
        data3 = b"Chunk 3"
        
        ctx.write_async(fd, data1, offset=0, user_data=1)
        ctx.write_async(fd, data2, offset=len(data1), user_data=2)
        ctx.write_async(fd, data3, offset=len(data1)+len(data2), user_data=3)
        
        # Submit all operations
        ctx.submit()
        
        # Wait for all completions
        for _ in range(3):
            user_data, result = ctx.wait_completion()
            print(f"Write {user_data}: {result} bytes written")
    finally:
        os.close(fd)
```

### Dynamic Buffer Pool (BufferPool)

Perform asynchronous I/O while dynamically adjusting buffer sizes:

```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    # Create buffer pool (4 buffers, each starting at 4KB)
    with pyiouring.BufferPool.create(initial_count=4, initial_size=4096) as pool:
        fd = os.open("/tmp/test.dat", os.O_RDONLY)
        try:
            # First read: 4KB
            buf_ptr, buf_size = pool.get_ptr(0)
            pool.set_size(0, 4096)
            ctx.read_async_ptr(fd, buf_ptr, 4096, offset=0, user_data=1)
            
            # Second read: adjust buffer size to 8KB
            pool.resize(1, 8192)
            buf_ptr, buf_size = pool.get_ptr(1)
            pool.set_size(1, 8192)
            ctx.read_async_ptr(fd, buf_ptr, 8192, offset=4096, user_data=2)
            
            # Third read: adjust buffer size to 16KB
            pool.resize(2, 16384)
            buf_ptr, buf_size = pool.get_ptr(2)
            pool.set_size(2, 16384)
            ctx.read_async_ptr(fd, buf_ptr, 16384, offset=12288, user_data=3)
            
            # Submit all operations
            ctx.submit()
            
            # Handle completions
            for _ in range(3):
                user_data, result = ctx.wait_completion()
                print(f"Read {user_data}: {result} bytes")
                
                # Read buffer data
                if user_data == 1:
                    data = pool.get(0)
                elif user_data == 2:
                    data = pool.get(1)
                elif user_data == 3:
                    data = pool.get(2)
                print(f"Buffer data: {data[:50]}...")
        finally:
            os.close(fd)
```

Adaptive buffer size adjustment example:

```python
def adaptive_read_with_pool(ctx, fd, file_size, pool):
    """Read while dynamically adjusting buffer size based on file position"""
    offset = 0
    user_data = 1
    slot = 0
    
    while offset < file_size:
        # Determine buffer size based on progress
        progress = offset / file_size
        if progress < 0.25:
            buf_size = 4096
            target_slot = 0
        elif progress < 0.5:
            buf_size = 8192
            target_slot = 1
        elif progress < 0.75:
            buf_size = 16384
            target_slot = 2
        else:
            buf_size = 32768
            target_slot = 3
        
        # Adjust buffer size
        pool.resize(target_slot, buf_size)
        pool.set_size(target_slot, min(buf_size, file_size - offset))
        
        # Submit asynchronous read
        buf_ptr, _ = pool.get_ptr(target_slot)
        ctx.read_async_ptr(fd, buf_ptr, min(buf_size, file_size - offset), 
                          offset=offset, user_data=user_data)
        
        offset += buf_size
        user_data += 1
        
        # Submit periodically
        if user_data % 8 == 0:
            ctx.submit()
    
    # Submit remaining operations
    ctx.submit()
    
    # Wait for all completions
    results = []
    for _ in range(user_data - 1):
        user_data_result, result = ctx.wait_completion()
        results.append((user_data_result, result))
    
    return results
```

## Error Handling

```python
import pyiouring

try:
    copied = pyiouring.copy_path("/nonexistent/file", "/tmp/dest.dat")
except pyiouring.UringError as e:
    print(f"Error: {e}")
```

## Examples

### Example 1: Simple File Copy

```python
import pyiouring

# Copy file
copied = pyiouring.copy_path("input.txt", "output.txt")
print(f"Copied {copied} bytes")
```

### Example 2: Large File Copy with Dynamic Buffer Size

```python
import pyiouring

def stepwise_buffer_size(offset, total, default):
    """Stepwise buffer size increase"""
    if total == 0:
        return default
    
    progress = offset / total
    
    if progress < 0.1:
        return default
    elif progress < 0.3:
        return default * 2
    elif progress < 0.6:
        return default * 4
    else:
        return default * 8

# Copy large file
copied = pyiouring.copy_path_dynamic(
    "/path/to/large_file.dat",
    "/path/to/copy.dat",
    qd=64,
    block_size=65536,
    buffer_size_cb=stepwise_buffer_size,
    fsync=True
)
print(f"Copied {copied:,} bytes")
```

### Example 3: Create Multiple Files

```python
import pyiouring
import os

# Create directory
os.makedirs("/tmp/many_files", exist_ok=True)

# Create multiple files
total_written = pyiouring.write_manyfiles(
    "/tmp/many_files",
    nfiles=100,
    mb_per_file=10,
    block_size=4096,
    qd=256,
    fsync_end=True
)
print(f"Total written: {total_written:,} bytes")
```

## API Reference

### Functions

- `copy_path(src_path, dst_path, *, qd=32, block_size=1048576)`: Copy file
- `copy_path_dynamic(src_path, dst_path, *, qd=32, block_size=1048576, buffer_size_cb=None, fsync=False)`: Copy file with dynamic buffer size
- `write_newfile(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False)`: Write new file
- `write_newfile_dynamic(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False, buffer_size_cb=None)`: Write new file with dynamic buffer size
- `write_manyfiles(dir_path, *, nfiles, mb_per_file, block_size=4096, qd=256, fsync_end=False)`: Write multiple files

### Classes

- `UringCtx(entries=64)`: io_uring context manager
  
  **Synchronous methods:**
  - `read(fd, length, offset=0)`: Synchronous read
  - `write(fd, data, offset=0)`: Synchronous write
  - `read_batch(fd, block_size, blocks, offset=0)`: Batch read
  - `read_offsets(fd, block_size, offsets, *, offset_bytes=True)`: Read from multiple offsets
  
  **Asynchronous methods:**
  - `read_async(fd, buf, offset=0, user_data=0)`: Submit asynchronous read
  - `write_async(fd, data, offset=0, user_data=0)`: Submit asynchronous write
  - `read_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)`: Asynchronous read using pointer
  - `write_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)`: Asynchronous write using pointer
  - `submit()`: Submit pending operations
  - `submit_and_wait(wait_nr=1)`: Submit and wait for completion
  - `wait_completion()`: Wait for completion (blocking), returns `(user_data, result)` tuple
  - `peek_completion()`: Check for completion (non-blocking), returns `(user_data, result)` tuple if available, `None` otherwise

- `BufferPool`: Dynamic buffer size management pool
  
  **Class methods:**
  - `BufferPool.create(initial_count=8, initial_size=4096)`: Create buffer pool
  
  **Instance methods:**
  - `resize(index, new_size)`: Dynamically adjust buffer size
  - `get(index)`: Return buffer data as bytes
  - `get_ptr(index)`: Return buffer pointer and size as `(ptr, size)` tuple
  - `set_size(index, size)`: Set buffer size (no reallocation, within capacity)
  - `close()`: Release buffer pool

### Exceptions

- `UringError`: io_uring related errors

## Performance Tips

1. **Queue Depth (qd)**: Higher qd allows more parallel I/O but also increases memory usage.
2. **Block Size**: Generally 64KB~1MB shows good performance.
3. **Dynamic buffer size**: Starting with small buffers and gradually increasing can reduce initial latency while improving overall throughput.
4. **fsync**: Only use when data integrity is important (performance degradation).

## Additional Resources

- [README.md](README.md): Project overview
- [INSTALLATION.md](INSTALLATION.md): Detailed installation guide
