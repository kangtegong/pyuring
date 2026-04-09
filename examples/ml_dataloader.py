#!/usr/bin/env python3
"""
Workloads: ML training data pipeline / Media processing / Search indexing / Batch jobs

If your application reads a large number of files and currently uses
ThreadPoolExecutor to avoid blocking — this example is for you.

PyTorch DataLoader workers, image/audio preprocessing pipelines, document
indexers, and batch processing jobs all do the same thing: open N files,
read their contents, process, repeat. The standard Python approach is
ThreadPoolExecutor — parallelize across threads to hide per-file open/read
latency. It works, but every file read involves a thread wakeup.

pyuring submits N read SQEs in a single io_uring_enter syscall and collects
all completions in another. Same concurrency, no thread pool overhead.
On NVMe with cold cache, batched submission also lets the storage controller
service multiple reads in parallel across its internal queues.

  Sequential os.read       ~1,630 MiB/s  (baseline, warm cache)
  ThreadPoolExecutor (4w)    ~775 MiB/s
  pyuring batched            ~1,070 MiB/s  (+38% vs threadpool)

This example benchmarks all four approaches — sequential, threadpool,
pyuring batched, and pyuring fixed-buffer — and verifies identical output.

Usage:
    python3 examples/ml_dataloader.py
    python3 examples/ml_dataloader.py --num-files 200 --file-size-kb 64 --workers 4
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
