#!/usr/bin/env python3
"""
System call count measurement script

Measures system call counts for synchronous/asynchronous I/O using strace.
This script is executed wrapped with strace.
Uses O_DIRECT by default (--no-odirect to use page cache).

Usage:
    strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10
    strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32
"""

import ctypes
import os
import sys
import tempfile
from pathlib import Path

# xk import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xk import UringCtx, BufferPool

# O_DIRECT requires aligned buffers
O_DIRECT_ALIGN = 4096
CHUNK_SIZE = 65536

_libc = ctypes.CDLL("libc.so.6")
_libc.posix_memalign.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t, ctypes.c_size_t]
_libc.posix_memalign.restype = ctypes.c_int
_libc.read.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
_libc.read.restype = ctypes.c_ssize_t


def _aligned_buffer(size: int):
    ptr = ctypes.c_void_p()
    if _libc.posix_memalign(ctypes.byref(ptr), O_DIRECT_ALIGN, size) != 0:
        raise OSError("posix_memalign failed")
    return ptr


def sync_write_read(num_files: int, file_size_mb: int, use_odirect: bool = True):
    """Write/read files synchronously (O_DIRECT by default)."""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size

    write_flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    read_flags = os.O_RDONLY
    if use_odirect:
        write_flags |= os.O_DIRECT
        read_flags |= os.O_DIRECT

    with tempfile.TemporaryDirectory(prefix="iouring_syscall_") as tmpdir:
        tmp_path = Path(tmpdir)

        # Write
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, write_flags, 0o644)
            try:
                offset = 0
                if use_odirect:
                    ptr = _aligned_buffer(CHUNK_SIZE)
                    try:
                        buf_array = (ctypes.c_char * CHUNK_SIZE).from_address(ptr.value)
                        while offset < len(data):
                            n = min(CHUNK_SIZE, len(data) - offset)
                            ctypes.memmove(ptr, (ctypes.c_char * n).from_buffer_copy(data[offset : offset + n]), n)
                            os.write(fd, memoryview(buf_array)[:n])
                            offset += n
                    finally:
                        _libc.free(ptr)
                else:
                    while offset < len(data):
                        chunk = data[offset : offset + CHUNK_SIZE]
                        os.write(fd, chunk)
                        offset += len(chunk)
            finally:
                os.close(fd)

        # Read
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, read_flags)
            try:
                if use_odirect:
                    ptr = _aligned_buffer(CHUNK_SIZE)
                    try:
                        while True:
                            n = _libc.read(fd, ptr, CHUNK_SIZE)
                            if n <= 0:
                                break
                    finally:
                        _libc.free(ptr)
                else:
                    while True:
                        chunk = os.read(fd, CHUNK_SIZE)
                        if not chunk:
                            break
            finally:
                os.close(fd)


def async_write_read(num_files: int, file_size_mb: int, qd: int, use_odirect: bool = True):
    """Write/read files asynchronously (O_DIRECT by default)."""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size

    write_flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    read_flags = os.O_RDONLY
    if use_odirect:
        write_flags |= os.O_DIRECT
        read_flags |= os.O_DIRECT

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
                    fd = os.open(file_path, write_flags, 0o644)
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
                    fd = os.open(file_path, write_flags, 0o644)
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
                    fd = os.open(file_path, read_flags)
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
                    fd = os.open(file_path, read_flags)
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
    parser.add_argument("--no-odirect", action="store_true", help="Disable O_DIRECT (use page cache)")

    args = parser.parse_args()
    use_odirect = not args.no_odirect

    if args.mode == "sync":
        sync_write_read(args.num_files, args.file_size_mb, use_odirect)
    else:
        async_write_read(args.num_files, args.file_size_mb, args.qd, use_odirect)


if __name__ == "__main__":
    main()

