#!/usr/bin/env python3
"""
Benchmark: Synchronous I/O (os.read/os.write) vs Asynchronous I/O (io_uring)

Performs operations to create and read 100 files of 10MB each:
- Speed comparison
- System call count comparison (using strace)

Usage:
    # Basic benchmark (100 files, 10MB each)
    python3 examples/bench_async_vs_sync.py
    
    # Custom settings
    python3 examples/bench_async_vs_sync.py --num-files 50 --file-size-mb 20 --qd 64
    
    # Measure system calls (requires strace)
    python3 examples/bench_async_vs_sync.py --measure-syscalls
    
    # Measure system calls only (separate script)
    strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10
    strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32
    
    # Compare with shell script
    ./examples/compare_syscalls.sh 100 10 32
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Tuple

# pyuring import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyuring import UringCtx, BufferPool, UringError

# O_DIRECT requires aligned buffers (typical alignment 4096); chunk size multiple of 4096
O_DIRECT_ALIGN = 4096
CHUNK_SIZE = 65536  # 64KB

_libc = ctypes.CDLL("libc.so.6")
_libc.posix_memalign.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t, ctypes.c_size_t]
_libc.posix_memalign.restype = ctypes.c_int
_libc.read.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
_libc.read.restype = ctypes.c_ssize_t


def _aligned_buffer(size: int):
    """Allocate alignment-sized aligned buffer for O_DIRECT. Caller must free with _libc.free."""
    ptr = ctypes.c_void_p()
    if _libc.posix_memalign(ctypes.byref(ptr), O_DIRECT_ALIGN, size) != 0:
        raise OSError("posix_memalign failed")
    return ptr


def create_test_files(base_dir: Path, num_files: int, file_size_mb: int) -> List[Path]:
    """Create list of test files (empty files)"""
    file_paths = []
    for i in range(num_files):
        file_path = base_dir / f"test_{i:03d}.dat"
        file_paths.append(file_path)
    return file_paths


def sync_write(file_path: Path, data: bytes, use_odirect: bool = True) -> int:
    """Write file synchronously (os.write). Uses aligned buffer when O_DIRECT."""
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags, 0o644)
    try:
        total_written = 0
        offset = 0
        if use_odirect:
            ptr = _aligned_buffer(CHUNK_SIZE)
            try:
                buf_array = (ctypes.c_char * CHUNK_SIZE).from_address(ptr.value)
                while offset < len(data):
                    n = min(CHUNK_SIZE, len(data) - offset)
                    ctypes.memmove(ptr, (ctypes.c_char * n).from_buffer_copy(data[offset : offset + n]), n)
                    written = os.write(fd, memoryview(buf_array)[:n])
                    total_written += written
                    offset += written
            finally:
                _libc.free(ptr)
        else:
            while offset < len(data):
                chunk = data[offset : offset + CHUNK_SIZE]
                written = os.write(fd, chunk)
                total_written += written
                offset += written
        os.fsync(fd)  # Force write to disk
        return total_written
    finally:
        os.close(fd)


def sync_read(file_path: Path, use_odirect: bool = True) -> bytes:
    """Read file synchronously (os.read or libc read with aligned buffer when O_DIRECT)."""
    flags = os.O_RDONLY
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags)
    try:
        if use_odirect:
            ptr = _aligned_buffer(CHUNK_SIZE)
            try:
                buf_array = (ctypes.c_char * CHUNK_SIZE).from_address(ptr.value)
                parts: List[bytes] = []
                while True:
                    n = _libc.read(fd, ptr, CHUNK_SIZE)
                    if n <= 0:
                        break
                    parts.append(bytes(memoryview(buf_array)[:n]))
                return b"".join(parts)
            finally:
                _libc.free(ptr)
        else:
            data = bytearray()
            while True:
                chunk = os.read(fd, CHUNK_SIZE)
                if not chunk:
                    break
                data.extend(chunk)
            return bytes(data)
    finally:
        os.close(fd)


def async_write_uring(ctx: UringCtx, file_path: Path, data: bytes, pool: BufferPool, slot: int, user_data: int, use_odirect: bool = True) -> None:
    """Submit asynchronous file write (io_uring)"""
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags, 0o644)
    
    # Copy data to buffer
    buf_ptr, buf_size = pool.get_ptr(slot)
    pool.set_size(slot, len(data))
    
    # Copy data to buffer
    import ctypes
    ctypes.memmove(buf_ptr, data, len(data))
    
    # Submit asynchronous write (encode fd in user_data: upper 32 bits are fd, lower 32 bits are slot)
    user_data_encoded = (fd << 32) | slot
    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)


def async_read_uring(ctx: UringCtx, file_path: Path, pool: BufferPool, slot: int, expected_size: int, user_data: int, use_odirect: bool = True) -> None:
    """Submit asynchronous file read (io_uring)"""
    flags = os.O_RDONLY
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags)
    
    # Set buffer size
    pool.set_size(slot, expected_size)
    buf_ptr, buf_size = pool.get_ptr(slot)
    
    # Submit asynchronous read (encode fd in user_data)
    user_data_encoded = (fd << 32) | slot
    ctx.read_async_ptr(fd, buf_ptr, expected_size, offset=0, user_data=user_data_encoded)


def benchmark_sync_write(file_paths: List[Path], file_size_mb: int, use_odirect: bool = True) -> Tuple[float, int]:
    """Synchronous write benchmark"""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    start_time = time.perf_counter()
    total_written = 0
    
    for file_path in file_paths:
        written = sync_write(file_path, data, use_odirect)
        total_written += written
    
    end_time = time.perf_counter()
    elapsed = end_time - start_time
    
    return elapsed, total_written


def benchmark_sync_read(file_paths: List[Path], use_odirect: bool = True) -> Tuple[float, int]:
    """Synchronous read benchmark"""
    start_time = time.perf_counter()
    total_read = 0
    
    for file_path in file_paths:
        data = sync_read(file_path, use_odirect)
        total_read += len(data)
    
    end_time = time.perf_counter()
    elapsed = end_time - start_time
    
    return elapsed, total_read


def benchmark_async_write(file_paths: List[Path], file_size_mb: int, qd: int, use_odirect: bool = True) -> Tuple[float, int]:
    """Asynchronous write benchmark"""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    # Create buffer pool (queue depth size)
    with UringCtx(entries=qd * 2) as ctx:
        with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
            start_time = time.perf_counter()
            total_written = 0
            inflight = 0
            file_idx = 0
            fd_map = {}  # user_data -> fd mapping
            
            # Submit initial operations
            while file_idx < len(file_paths) and inflight < qd:
                slot = inflight % qd
                async_write_uring(ctx, file_paths[file_idx], data, pool, slot, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
            
            # Submit periodically
            if inflight > 0:
                ctx.submit()
            
            # Process remaining operations
            while file_idx < len(file_paths):
                # Wait for completion
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(-int(result), "uring_wait_completion", detail="write completion")
                
                # Extract and close fd
                fd = user_data_encoded >> 32
                os.fsync(fd)  # Force write to disk
                os.close(fd)
                
                total_written += result
                inflight -= 1
                
                # Submit new operation
                slot = inflight % qd
                async_write_uring(ctx, file_paths[file_idx], data, pool, slot, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
                
                ctx.submit()
            
            # Wait for remaining completions
            while inflight > 0:
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(-int(result), "uring_wait_completion", detail="write completion")
                
                fd = user_data_encoded >> 32
                os.fsync(fd)
                os.close(fd)
                
                total_written += result
                inflight -= 1
            
            end_time = time.perf_counter()
            elapsed = end_time - start_time
    
    return elapsed, total_written


def benchmark_async_read(file_paths: List[Path], file_size_mb: int, qd: int, use_odirect: bool = True) -> Tuple[float, int]:
    """Asynchronous read benchmark"""
    file_size = file_size_mb * 1024 * 1024
    
    with UringCtx(entries=qd * 2) as ctx:
        with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
            start_time = time.perf_counter()
            total_read = 0
            inflight = 0
            file_idx = 0
            
            # Submit initial operations
            while file_idx < len(file_paths) and inflight < qd:
                slot = inflight % qd
                async_read_uring(ctx, file_paths[file_idx], pool, slot, file_size, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
            
            # Submit periodically
            if inflight > 0:
                ctx.submit()
            
            # Process remaining operations
            while file_idx < len(file_paths):
                # Wait for completion
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(-int(result), "uring_wait_completion", detail="read completion")
                
                # Extract and close fd
                fd = user_data_encoded >> 32
                slot = user_data_encoded & 0xFFFFFFFF
                os.close(fd)
                
                total_read += result
                inflight -= 1
                
                # Submit new operation
                slot = inflight % qd
                async_read_uring(ctx, file_paths[file_idx], pool, slot, file_size, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
                
                ctx.submit()
            
            # Wait for remaining completions
            while inflight > 0:
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(-int(result), "uring_wait_completion", detail="read completion")
                
                fd = user_data_encoded >> 32
                os.close(fd)
                
                total_read += result
                inflight -= 1
            
            end_time = time.perf_counter()
            elapsed = end_time - start_time
    
    return elapsed, total_read


def count_syscalls(command: list[str], label: str) -> dict:
    """Measure system call count using strace"""
    print(f"\n=== Measuring {label} system calls... ===")
    
    try:
        # Run strace
        strace_cmd = ["strace", "-c", "-f"] + command
        result = subprocess.run(
            strace_cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            print(f"Warning: strace command failed: {result.stderr}")
            return {}
        
        # Parse strace output
        syscall_counts = {}
        lines = result.stderr.split('\n')
        
        for line in lines:
            if '%' in line and 'time' in line.lower():
                # Skip header line
                continue
            parts = line.strip().split()
            if len(parts) >= 4:
                try:
                    count = int(parts[0])
                    syscall_name = parts[-1]
                    if syscall_name and count > 0:
                        syscall_counts[syscall_name] = count
                except (ValueError, IndexError):
                    continue
        
        return syscall_counts
    
    except subprocess.TimeoutExpanded:
        print(f"Warning: strace command timed out")
        return {}
    except FileNotFoundError:
        print(f"Warning: strace not found. Install with: sudo apt-get install strace")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Synchronous vs Asynchronous I/O benchmark")
    parser.add_argument("--num-files", type=int, default=100, help="Number of files (default: 100)")
    parser.add_argument("--file-size-mb", type=int, default=10, help="File size (MB, default: 10)")
    parser.add_argument("--qd", type=int, default=32, help="Queue depth (default: 32)")
    parser.add_argument("--measure-syscalls", action="store_true", help="Measure system calls (requires strace)")
    parser.add_argument("--keep-files", action="store_true", help="Keep test files")
    parser.add_argument("--no-odirect", action="store_true", help="Disable O_DIRECT (use page cache instead of direct disk I/O)")
    parser.add_argument("--repeats", type=int, default=1, help="Number of repetitions (calculate average)")
    parser.add_argument("--clear-cache", action="store_true", help="Clear page cache before test (requires sudo)")
    
    args = parser.parse_args()
    args.odirect = not args.no_odirect

    # Create temporary directory
    with tempfile.TemporaryDirectory(prefix="iouring_bench_") as tmpdir:
        tmp_path = Path(tmpdir)
        test_dir = tmp_path / "test_files"
        test_dir.mkdir()
        
        file_paths = create_test_files(test_dir, args.num_files, args.file_size_mb)
        file_size_mb = args.file_size_mb
        total_size_gb = (args.num_files * file_size_mb) / 1024
        
        print(f"=== Benchmark Settings ===")
        print(f"Number of files: {args.num_files}")
        print(f"File size: {file_size_mb} MB")
        print(f"Total size: {total_size_gb:.2f} GB")
        print(f"Queue depth: {args.qd}")
        print(f"O_DIRECT: {'Enabled' if args.odirect else 'Disabled'}")
        print(f"Repetitions: {args.repeats}")
        if args.clear_cache:
            print("Clearing page cache...")
            try:
                subprocess.run(["sync"], check=True)
                subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"], check=True)
                print("Page cache cleared")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("Warning: Cannot clear page cache (sudo required)")
        print()
        
        # Lists for repeated measurements
        sync_write_times = []
        async_write_times = []
        sync_read_times = []
        async_read_times = []
        
        for repeat in range(args.repeats):
            if args.repeats > 1:
                print(f"Repetition {repeat + 1}/{args.repeats}...", end=" ", flush=True)
            
            # ========== Synchronous Write ==========
            sync_write_time, sync_write_bytes = benchmark_sync_write(file_paths, file_size_mb, args.odirect)
            sync_write_times.append(sync_write_time)
            sync_write_mb_s = (sync_write_bytes / (1024 * 1024)) / sync_write_time if sync_write_time > 0 else 0
            
            # ========== Asynchronous Write ==========
            async_write_time, async_write_bytes = benchmark_async_write(file_paths, file_size_mb, args.qd, args.odirect)
            async_write_times.append(async_write_time)
            async_write_mb_s = (async_write_bytes / (1024 * 1024)) / async_write_time if async_write_time > 0 else 0
            
            # ========== Synchronous Read ==========
            sync_read_time, sync_read_bytes = benchmark_sync_read(file_paths, args.odirect)
            sync_read_times.append(sync_read_time)
            sync_read_mb_s = (sync_read_bytes / (1024 * 1024)) / sync_read_time if sync_read_time > 0 else 0
            
            # ========== Asynchronous Read ==========
            async_read_time, async_read_bytes = benchmark_async_read(file_paths, file_size_mb, args.qd, args.odirect)
            async_read_times.append(async_read_time)
            async_read_mb_s = (async_read_bytes / (1024 * 1024)) / async_read_time if async_read_time > 0 else 0
            
            if args.repeats > 1:
                print("Done")
        
        # Calculate averages
        avg_sync_write_time = sum(sync_write_times) / len(sync_write_times)
        avg_async_write_time = sum(async_write_times) / len(async_write_times)
        avg_sync_read_time = sum(sync_read_times) / len(sync_read_times)
        avg_async_read_time = sum(async_read_times) / len(async_read_times)
        
        avg_sync_write_mb_s = (sync_write_bytes / (1024 * 1024)) / avg_sync_write_time if avg_sync_write_time > 0 else 0
        avg_async_write_mb_s = (async_write_bytes / (1024 * 1024)) / avg_async_write_time if avg_async_write_time > 0 else 0
        avg_sync_read_mb_s = (sync_read_bytes / (1024 * 1024)) / avg_sync_read_time if avg_sync_read_time > 0 else 0
        avg_async_read_mb_s = (async_read_bytes / (1024 * 1024)) / avg_async_read_time if avg_async_read_time > 0 else 0
        
        # ========== Result Summary ==========
        print("=" * 80)
        print("=== Result Summary ===")
        print("=" * 80)
        if args.repeats > 1:
            print(f"{'Operation':<20} {'Avg Time(s)':<18} {'Avg Throughput(MB/s)':<20} {'Speedup':<15}")
            print("-" * 80)
            
            write_speedup = avg_sync_write_time / avg_async_write_time if avg_async_write_time > 0 else 0
            read_speedup = avg_sync_read_time / avg_async_read_time if avg_async_read_time > 0 else 0
            
            print(f"{'Sync Write':<20} {avg_sync_write_time:<18.4f} {avg_sync_write_mb_s:<20.2f} {'1.00x':<15}")
            print(f"{'Async Write':<20} {avg_async_write_time:<18.4f} {avg_async_write_mb_s:<20.2f} {write_speedup:<15.2f}x")
            print(f"{'Sync Read':<20} {avg_sync_read_time:<18.4f} {avg_sync_read_mb_s:<20.2f} {'1.00x':<15}")
            print(f"{'Async Read':<20} {avg_async_read_time:<18.4f} {avg_async_read_mb_s:<20.2f} {read_speedup:<15.2f}x")
        else:
            print(f"{'Operation':<20} {'Time(s)':<15} {'Throughput(MB/s)':<15} {'Speedup':<15}")
            print("-" * 80)
            
            write_speedup = avg_sync_write_time / avg_async_write_time if avg_async_write_time > 0 else 0
            read_speedup = avg_sync_read_time / avg_async_read_time if avg_async_read_time > 0 else 0
            
            print(f"{'Sync Write':<20} {avg_sync_write_time:<15.4f} {avg_sync_write_mb_s:<15.2f} {'1.00x':<15}")
            print(f"{'Async Write':<20} {avg_async_write_time:<15.4f} {avg_async_write_mb_s:<15.2f} {write_speedup:<15.2f}x")
            print(f"{'Sync Read':<20} {avg_sync_read_time:<15.4f} {avg_sync_read_mb_s:<15.2f} {'1.00x':<15}")
            print(f"{'Async Read':<20} {avg_async_read_time:<15.4f} {avg_async_read_mb_s:<15.2f} {read_speedup:<15.2f}x")
        
        print()
        
        # Performance analysis
        write_time_saved = avg_sync_write_time - avg_async_write_time
        write_percent_faster = ((avg_sync_write_time - avg_async_write_time) / avg_sync_write_time) * 100
        read_time_saved = avg_sync_read_time - avg_async_read_time
        read_percent_faster = ((avg_sync_read_time - avg_async_read_time) / avg_sync_read_time) * 100 if avg_sync_read_time > 0 else 0
        total_sync_time = avg_sync_write_time + avg_sync_read_time
        total_async_time = avg_async_write_time + avg_async_read_time
        total_speedup = total_sync_time / total_async_time if total_async_time > 0 else 0
        total_time_saved = total_sync_time - total_async_time
        
        print("Performance Summary:")
        print(f"  Write: Sync {avg_sync_write_time:.3f}s → Async {avg_async_write_time:.3f}s ({write_speedup:.2f}x, {write_percent_faster:.1f}% improvement)")
        print(f"  Read: Sync {avg_sync_read_time:.3f}s → Async {avg_async_read_time:.3f}s ({read_speedup:.2f}x)")
        print(f"  Total: {total_sync_time:.3f}s → {total_async_time:.3f}s ({total_speedup:.2f}x, {total_time_saved:.3f}s saved)")
        print()
        
        # ========== System Call Measurement ==========
        if args.measure_syscalls:
            print("=" * 60)
            print("=== System Call Measurement ===")
            print("=" * 60)
            print("Note: A separate script is executed to measure system calls.")
            print("      To accurately measure system calls for each method:")
            print("      python3 examples/bench_syscalls.py --mode sync")
            print("      python3 examples/bench_syscalls.py --mode async")
            print()
        
        # Keep files option
        if args.keep_files:
            keep_dir = Path("/tmp/iouring_bench_files")
            keep_dir.mkdir(exist_ok=True)
            shutil.copytree(test_dir, keep_dir / "test_files", dirs_exist_ok=True)
            print(f"Test files saved to {keep_dir}.")


if __name__ == "__main__":
    main()

