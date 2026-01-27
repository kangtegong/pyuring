#!/usr/bin/env python3
"""
System call count measurement script

Measures system call counts for synchronous/asynchronous I/O using strace.
This script is executed wrapped with strace.

Usage:
    strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10
    strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32
"""

import os
import sys
import tempfile
from pathlib import Path

# pyiouring import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import UringCtx, BufferPool


def sync_write_read(num_files: int, file_size_mb: int):
    """Write/read files synchronously"""
    import time
    
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    with tempfile.TemporaryDirectory(prefix="iouring_syscall_") as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Write
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            try:
                offset = 0
                chunk_size = 65536
                while offset < len(data):
                    chunk = data[offset:offset + chunk_size]
                    os.write(fd, chunk)
                    offset += len(chunk)
            finally:
                os.close(fd)
        
        # Read
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, os.O_RDONLY)
            try:
                chunk_size = 65536
                while True:
                    chunk = os.read(fd, chunk_size)
                    if not chunk:
                        break
            finally:
                os.close(fd)


def async_write_read(num_files: int, file_size_mb: int, qd: int):
    """Write/read files asynchronously"""
    import time
    import ctypes
    
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    with tempfile.TemporaryDirectory(prefix="iouring_syscall_") as tmpdir:
        tmp_path = Path(tmpdir)
        
        with UringCtx(entries=qd * 2) as ctx:
            with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
                # Write
                file_idx = 0
                inflight = 0
                
                # Submit initial operations
                while file_idx < num_files and inflight < qd:
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
                    slot = inflight % qd
                    
                    # Copy data to buffer
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    pool.set_size(slot, len(data))
                    ctypes.memmove(buf_ptr, data, len(data))
                    
                    # Submit asynchronous write (encode fd in user_data)
                    user_data_encoded = (fd << 32) | slot
                    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                
                ctx.submit()
                
                # Process remaining operations
                while file_idx < num_files:
                    user_data_encoded, result = ctx.wait_completion()
                    # Extract and close fd
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                    
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
                    slot = inflight % qd
                    
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    pool.set_size(slot, len(data))
                    ctypes.memmove(buf_ptr, data, len(data))
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                    
                    ctx.submit()
                
                # Wait for remaining completions
                while inflight > 0:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                
                # Read
                file_idx = 0
                inflight = 0
                
                # Submit initial operations
                while file_idx < num_files and inflight < qd:
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_RDONLY)
                    slot = inflight % qd
                    
                    pool.set_size(slot, file_size)
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.read_async_ptr(fd, buf_ptr, file_size, offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                
                ctx.submit()
                
                # Process remaining operations
                while file_idx < num_files:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                    
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_RDONLY)
                    slot = inflight % qd
                    
                    pool.set_size(slot, file_size)
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.read_async_ptr(fd, buf_ptr, file_size, offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                    
                    ctx.submit()
                
                # Wait for remaining completions
                while inflight > 0:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="System call measurement script")
    parser.add_argument("--mode", choices=["sync", "async"], required=True, help="Measurement mode")
    parser.add_argument("--num-files", type=int, default=100, help="Number of files")
    parser.add_argument("--file-size-mb", type=int, default=10, help="File size (MB)")
    parser.add_argument("--qd", type=int, default=32, help="Queue depth (async mode)")
    
    args = parser.parse_args()
    
    if args.mode == "sync":
        sync_write_read(args.num_files, args.file_size_mb)
    else:
        async_write_read(args.num_files, args.file_size_mb, args.qd)


if __name__ == "__main__":
    main()

