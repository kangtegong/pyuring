#!/usr/bin/env python3
"""
Demo of the async io_uring API with dynamic buffer size adjustment.

This demonstrates:
1. Initializing io_uring
2. Asynchronous reading
3. Asynchronous writing
4. Dynamic buffer size adjustment
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyiouring import UringCtx, BufferPool, UringError


def demo_basic_async():
    """Basic async read/write example."""
    print("=== Basic Async Read/Write Demo ===")
    
    # Create test file
    test_file = "/tmp/test_async.dat"
    with open(test_file, "wb") as f:
        f.write(b"Hello, io_uring async API!" * 100)
    
    try:
        with UringCtx(entries=64) as ctx:
            fd = os.open(test_file, os.O_RDONLY)
            
            # Read asynchronously
            buf = bytearray(1024)
            user_data = 1
            ctx.read_async(fd, buf, offset=0, user_data=user_data)
            
            # Submit and wait for completion
            ctx.submit()
            user_data_result, result = ctx.wait_completion()
            
            print(f"Read completion: user_data={user_data_result}, bytes_read={result}")
            print(f"Data: {buf[:result].decode('utf-8', errors='ignore')[:50]}...")
            
            os.close(fd)
    except UringError as e:
        print(f"Error: {e}")
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


def demo_async_with_buffer_pool():
    """Async operations with dynamic buffer pool."""
    print("\n=== Async with Dynamic Buffer Pool Demo ===")
    
    # Create test file
    test_file = "/tmp/test_async_pool.dat"
    test_data = b"X" * 4096 + b"Y" * 8192 + b"Z" * 16384
    with open(test_file, "wb") as f:
        f.write(test_data)
    
    try:
        with UringCtx(entries=64) as ctx:
            with BufferPool.create(initial_count=4, initial_size=4096) as pool:
                fd = os.open(test_file, os.O_RDONLY)
                
                # Read with different buffer sizes
                offset = 0
                user_data = 1
                
                # First read: 4KB
                buf_ptr, buf_size = pool.get_ptr(0)
                pool.set_size(0, 4096)
                ctx.read_async_ptr(fd, buf_ptr, 4096, offset=offset, user_data=user_data)
                offset += 4096
                user_data += 1
                
                # Second read: resize to 8KB
                pool.resize(1, 8192)
                buf_ptr, buf_size = pool.get_ptr(1)
                pool.set_size(1, 8192)
                ctx.read_async_ptr(fd, buf_ptr, 8192, offset=offset, user_data=user_data)
                offset += 8192
                user_data += 1
                
                # Third read: resize to 16KB
                pool.resize(2, 16384)
                buf_ptr, buf_size = pool.get_ptr(2)
                pool.set_size(2, 16384)
                ctx.read_async_ptr(fd, buf_ptr, 16384, offset=offset, user_data=user_data)
                
                # Submit all operations
                ctx.submit()
                
                # Wait for all completions
                results = []
                for _ in range(3):
                    user_data_result, result = ctx.wait_completion()
                    results.append((user_data_result, result))
                    print(f"Read {user_data_result}: {result} bytes")
                
                # Verify data
                buf0 = pool.get(0)
                buf1 = pool.get(1)
                buf2 = pool.get(2)
                
                print(f"Buffer 0 (4KB): starts with {buf0[:20]}")
                print(f"Buffer 1 (8KB): starts with {buf1[:20]}")
                print(f"Buffer 2 (16KB): starts with {buf2[:20]}")
                
                os.close(fd)
    except UringError as e:
        print(f"Error: {e}")
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


def demo_async_write():
    """Async write example."""
    print("\n=== Async Write Demo ===")
    
    test_file = "/tmp/test_async_write.dat"
    
    try:
        with UringCtx(entries=64) as ctx:
            fd = os.open(test_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            
            # Write multiple chunks asynchronously
            chunks = [
                (b"Chunk 1: " + b"A" * 1000, 0),
                (b"Chunk 2: " + b"B" * 2000, 1000),
                (b"Chunk 3: " + b"C" * 3000, 3000),
            ]
            
            user_data = 1
            for data, offset in chunks:
                ctx.write_async(fd, data, offset=offset, user_data=user_data)
                user_data += 1
            
            # Submit and wait for all completions
            ctx.submit()
            
            for _ in range(len(chunks)):
                user_data_result, result = ctx.wait_completion()
                print(f"Write {user_data_result}: {result} bytes written")
            
            os.close(fd)
            
            # Verify
            with open(test_file, "rb") as f:
                content = f.read()
                print(f"Total file size: {len(content)} bytes")
                print(f"First 100 bytes: {content[:100]}")
    except UringError as e:
        print(f"Error: {e}")
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


def demo_adaptive_buffer_size():
    """Demo of adaptive buffer sizing based on file position."""
    print("\n=== Adaptive Buffer Size Demo ===")
    
    # Create a large test file
    test_file = "/tmp/test_adaptive.dat"
    file_size = 1024 * 1024  # 1MB
    with open(test_file, "wb") as f:
        f.write(b"X" * file_size)
    
    try:
        with UringCtx(entries=64) as ctx:
            with BufferPool.create(initial_count=4, initial_size=4096) as pool:
                fd = os.open(test_file, os.O_RDONLY)
                
                # Adaptive buffer sizing: start small, increase as we progress
                def get_buffer_size(offset, total_size, default_size):
                    """Calculate buffer size based on position in file."""
                    progress = offset / total_size
                    if progress < 0.25:
                        return default_size  # 4KB
                    elif progress < 0.5:
                        return default_size * 2  # 8KB
                    elif progress < 0.75:
                        return default_size * 4  # 16KB
                    else:
                        return default_size * 8  # 32KB
                
                offset = 0
                user_data = 1
                operations = []
                
                # Submit reads with adaptive buffer sizes
                while offset < file_size:
                    buf_size = get_buffer_size(offset, file_size, 4096)
                    remaining = file_size - offset
                    actual_size = min(buf_size, remaining)
                    
                    # Use buffer pool slot based on size
                    slot = 0
                    if buf_size > 16384:
                        slot = 3
                        pool.resize(3, 32768)
                    elif buf_size > 8192:
                        slot = 2
                        pool.resize(2, 16384)
                    elif buf_size > 4096:
                        slot = 1
                        pool.resize(1, 8192)
                    
                    pool.set_size(slot, actual_size)
                    buf_ptr, _ = pool.get_ptr(slot)
                    
                    ctx.read_async_ptr(fd, buf_ptr, actual_size, offset=offset, user_data=user_data)
                    operations.append((user_data, offset, actual_size, slot))
                    
                    offset += actual_size
                    user_data += 1
                    
                    # Submit in batches to avoid queue overflow
                    if len(operations) % 8 == 0:
                        ctx.submit()
                
                # Submit remaining
                ctx.submit()
                
                # Wait for all completions
                total_read = 0
                for user_data, expected_offset, expected_size, slot in operations:
                    user_data_result, result = ctx.wait_completion()
                    total_read += result
                    print(f"Read {user_data_result}: {result} bytes at offset {expected_offset} "
                          f"(buffer size: {expected_size}, slot: {slot})")
                
                print(f"\nTotal bytes read: {total_read}")
                print(f"Expected: {file_size}")
                
                os.close(fd)
    except UringError as e:
        print(f"Error: {e}")
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


if __name__ == "__main__":
    demo_basic_async()
    demo_async_with_buffer_pool()
    demo_async_write()
    demo_adaptive_buffer_size()
    print("\n=== All demos completed ===")

