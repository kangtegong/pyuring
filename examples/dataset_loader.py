#!/usr/bin/env python3
"""
Reading many files concurrently using pyuring.

Any application that needs to read a large number of files — and currently
uses ThreadPoolExecutor to avoid blocking — can use pyuring to get the same
concurrency with less overhead. Threads have a fixed cost per wakeup; pyuring
submits all reads in one syscall and collects completions in another.

This pattern applies to:
  - ML training data pipelines (images, audio clips, tokenized shards per batch)
  - Media processing (reading frames, thumbnails, or metadata from many files)
  - Search and indexing (reading documents, log files, or crawled pages)
  - Configuration or asset loading at startup (reading many small config files)
  - Any batch job that processes a directory of input files

The standard go-to for concurrent file reads in Python is ThreadPoolExecutor.
pyuring's batched read_async offers a single-threaded alternative: submit N
read SQEs in one ring submission, wait for their CQEs, and reassemble results.
On cold-cache storage, this allows the kernel's I/O scheduler to reorder and
overlap reads across files, which is particularly effective on NVMe where
multiple queues can be in-flight simultaneously.

This example compares:
  1. Sequential os.read (single thread, one syscall per file)
  2. ThreadPoolExecutor (standard Python approach, N threads)
  3. pyuring batched reads (single thread, N SQEs per submission)
  4. pyuring fixed-buffer reads (registered kernel buffers, reduced validation overhead)

Usage:
    python3 examples/dataset_loader.py
    python3 examples/dataset_loader.py --num-files 200 --file-size-kb 64 --workers 4
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyuring as iou
from pyuring import UringCtx, UringError


def create_dataset(tmpdir: str, num_files: int, size_kb: int) -> List[str]:
    """Create synthetic dataset files. Returns list of absolute paths."""
    paths = []
    for i in range(num_files):
        path = os.path.join(tmpdir, f"shard_{i:05d}.bin")
        # Pattern: file index repeated to fill the file
        content = bytes([i & 0xFF]) * (size_kb * 1024)
        with open(path, "wb") as f:
            f.write(content)
        paths.append(path)
    return paths


# ──────────────────────────────────────────────────────────────────────────────
# Loader implementations
# ──────────────────────────────────────────────────────────────────────────────

def load_sequential(paths: List[str]) -> List[bytes]:
    """Baseline: read each file sequentially with os.read."""
    results = []
    for path in paths:
        fd = os.open(path, os.O_RDONLY)
        size = os.fstat(fd).st_size
        data = os.read(fd, size)
        os.close(fd)
        results.append(data)
    return results


def load_threadpool(paths: List[str], workers: int) -> List[bytes]:
    """
    Standard approach for PyTorch DataLoader workers: concurrent.futures threads.

    PyTorch uses multiple worker processes for data loading. Each worker opens
    files independently. This simulates one worker with thread-level parallelism.
    """
    def _read_one(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_read_one, paths))


def load_pyuring_batched(paths: List[str], batch_size: int = 32) -> List[bytes]:
    """
    pyuring batched loader: submit up to batch_size read SQEs at once.

    Each file is read with one async SQE. After submitting a batch, we wait
    for all completions before moving to the next batch. user_data carries
    the path index so completions can be reassembled in order.

    This is suitable for the "prefetch" step of a DataLoader: while the GPU
    processes batch N, the loader fills a buffer with batch N+1's data.
    """
    file_size = os.path.getsize(paths[0])
    results = [None] * len(paths)

    with iou.UringCtx(
        entries=max(batch_size, 64),
        # IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_COOP_TASKRUN improve throughput
        # on kernels >= 5.19. Drop setup_flags=0 to use defaults on older kernels.
        setup_flags=0,
    ) as ctx:
        i = 0
        while i < len(paths):
            batch_paths = paths[i:i + batch_size]
            fds = []
            buffers = []

            # Open files and allocate buffers for this batch
            for j, path in enumerate(batch_paths):
                fd = os.open(path, os.O_RDONLY)
                buf = bytearray(file_size)
                fds.append(fd)
                buffers.append(buf)
                ctx.read_async(fd, buf, offset=0, user_data=j)

            ctx.submit()

            # Collect completions
            for _ in range(len(batch_paths)):
                user_data, n_bytes = ctx.wait_completion()
                if n_bytes < 0:
                    raise UringError(-n_bytes, "dataset_read")
                results[i + user_data] = bytes(buffers[user_data][:n_bytes])

            for fd in fds:
                os.close(fd)

            i += batch_size

    return results


def load_pyuring_fixed(paths: List[str], batch_size: int = 32) -> List[bytes]:
    """
    pyuring fixed-buffer loader: register buffers once, reuse across batches.

    Registering buffers with the kernel via register_buffers() pins the memory
    and allows the kernel to skip per-operation buffer validation. This is
    beneficial when the same buffer slots are reused across many batches
    (e.g. a fixed-size prefetch pool).
    """
    file_size = os.path.getsize(paths[0])
    results = [None] * len(paths)

    with iou.UringCtx(
        entries=max(batch_size, 64),
        setup_flags=0,
    ) as ctx:
        # Allocate and register a pool of batch_size buffers
        pool = [bytearray(file_size) for _ in range(batch_size)]
        ctx.register_buffers(pool)

        fds_registered = []
        i = 0

        while i < len(paths):
            batch_paths = paths[i:i + batch_size]
            fds = [os.open(p, os.O_RDONLY) for p in batch_paths]

            # Register this batch's fds
            if fds_registered:
                ctx.unregister_files()
            ctx.register_files(fds)
            fds_registered = fds

            for j in range(len(batch_paths)):
                ctx.read_fixed(file_index=j, buf=pool[j], offset=0, buf_index=j)

            for j in range(len(batch_paths)):
                results[i + j] = bytes(pool[j])

            for fd in fds:
                os.close(fd)

            i += batch_size

        if fds_registered:
            ctx.unregister_files()
        ctx.unregister_buffers()

    return results


# ──────────────────────────────────────────────────────────────────────────────

def run(num_files: int, size_kb: int, workers: int, batch_size: int) -> None:
    print(f"Dataset: {num_files} files × {size_kb} KiB  |  threadpool workers: {workers}  |  pyuring batch: {batch_size}")
    total_mb = num_files * size_kb / 1024
    print(f"Total data: {total_mb:.1f} MiB")
    print()

    with tempfile.TemporaryDirectory(prefix="pyuring_ds_") as tmpdir:
        paths = create_dataset(tmpdir, num_files, size_kb)

        def measure(name, fn, *args):
            t0 = time.perf_counter()
            data = fn(*args)
            t = time.perf_counter() - t0
            throughput = total_mb / t
            print(f"  {name:<30s}  {t*1000:6.0f}ms   {throughput:5.1f} MiB/s")
            return data

        r_seq  = measure("sequential os.read",        load_sequential,      paths)
        r_tp   = measure(f"threadpool ({workers} workers)",
                                                       load_threadpool,      paths, workers)
        r_iou  = measure(f"pyuring batched (bs={batch_size})",
                                                       load_pyuring_batched, paths, batch_size)

        # Fixed-buffer loader requires kernel support for register_files
        try:
            r_fix = measure(f"pyuring fixed-buf (bs={batch_size})",
                            load_pyuring_fixed, paths, batch_size)
        except UringError as e:
            r_fix = None
            print(f"  pyuring fixed-buf: skipped ({e})")

        print()

        # Verify all loaders produced identical output
        for i, (a, b, c) in enumerate(zip(r_seq, r_tp, r_iou)):
            assert a == b == c, f"content mismatch at index {i}"
        if r_fix is not None:
            for i, (a, b) in enumerate(zip(r_seq, r_fix)):
                assert a == b, f"fixed-buf content mismatch at index {i}"

        print("All loaders produced byte-identical output. OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dataset loader benchmark")
    parser.add_argument("--num-files", type=int, default=100,
                        help="Number of dataset shards (default: 100)")
    parser.add_argument("--file-size-kb", type=int, default=32,
                        help="Size of each shard in KiB (default: 32)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Threads for threadpool loader (default: 4)")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="SQEs per ring submission for pyuring loaders (default: 32)")
    args = parser.parse_args()

    try:
        run(args.num_files, args.file_size_kb, args.workers, args.batch_size)
    except UringError as e:
        print(f"io_uring error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
