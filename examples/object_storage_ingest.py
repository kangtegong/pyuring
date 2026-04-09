#!/usr/bin/env python3
"""
Object storage ingest pipeline using pyuring.

Object storage systems (S3-compatible APIs, MinIO, Ceph RGW) are often fronted
by a local ingest node that:
  1. Receives uploaded files over the network
  2. Writes them to a local staging area
  3. Computes a checksum
  4. Moves the staged file to its final location (or replicates it)

The write throughput of the ingest node directly determines upload capacity.
When ingesting many concurrent uploads of varying sizes, batching writes with
io_uring reduces syscall pressure compared to issuing one write(2) per chunk.

This example simulates the local-disk portion of such a pipeline:
  - Multiple "upload streams" write files of varying sizes concurrently
  - Each stream writes chunks as they arrive (simulated with in-memory bytes)
  - After all chunks are written, the file is fsync'd and moved to final location

It compares:
  1. sequential standard write (one write + fsync per file, no concurrency)
  2. pyuring pipeline using write_many for bulk fixed-size ingests
  3. pyuring UringCtx for variable-size, progress-tracked ingests

Usage:
    python3 examples/object_storage_ingest.py
    python3 examples/object_storage_ingest.py --objects 50 --size-mb 10
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyuring as iou
from pyuring import UringError


def make_object(obj_id: int, size_mb: int) -> bytes:
    """Generate deterministic object content for verification."""
    chunk = bytes([obj_id & 0xFF, (obj_id >> 8) & 0xFF] * 512)  # 1 KiB pattern
    repeat = (size_mb * 1024 * 1024) // len(chunk) + 1
    return (chunk * repeat)[:size_mb * 1024 * 1024]


def ingest_standard(objects: List[Tuple[str, bytes]], staging: str, final: str) -> float:
    """Write each object sequentially: open, write chunks, fsync, rename."""
    t0 = time.perf_counter()
    for name, data in objects:
        stage_path = os.path.join(staging, name)
        final_path = os.path.join(final, name)
        chunk_size = 256 * 1024  # 256 KiB chunks (simulate network arrival)
        fd = os.open(stage_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            for off in range(0, len(data), chunk_size):
                os.write(fd, data[off:off + chunk_size])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(stage_path, final_path)
    return time.perf_counter() - t0


def ingest_pyuring_write_many(
    objects: List[Tuple[str, bytes]], staging: str, final: str, size_mb: int
) -> float:
    """
    Ingest a batch of equal-size objects using write_many.

    write_many writes N files of the same size in a single io_uring pipeline.
    Suitable for fixed-size object stores (e.g. chunk-based storage where
    every object is exactly one chunk size).
    """
    t0 = time.perf_counter()

    # Write all objects to staging directory at once
    iou.write_many(
        staging,
        nfiles=len(objects),
        mb_per_file=size_mb,
        mode="fast",
        fsync_end=True,
    )

    # Rename staged files to final names
    # write_many names files sequentially as file_0, file_1, ...
    for i, (name, _) in enumerate(objects):
        src = os.path.join(staging, f"file_{i}")
        dst = os.path.join(final, name)
        if os.path.exists(src):
            os.rename(src, dst)

    return time.perf_counter() - t0


def ingest_pyuring_progress(
    objects: List[Tuple[str, bytes]], staging: str, final: str
) -> Tuple[float, dict]:
    """
    Ingest variable-size objects using copy_path_dynamic with progress tracking.

    In a real ingest pipeline, progress_cb would update a metadata store
    (e.g. Redis, PostgreSQL) with the number of bytes persisted so far.
    This is useful for resumable uploads: if the ingest node crashes mid-write,
    the client can resume from the last confirmed offset.
    """
    progress_log = {}  # obj_name -> list of (done_bytes, total_bytes) snapshots

    def make_progress_cb(name: str):
        snapshots = []
        progress_log[name] = snapshots
        def cb(done: int, total: int) -> bool:
            snapshots.append((done, total))
            return False  # do not cancel
        return cb

    t0 = time.perf_counter()

    for name, data in objects:
        stage_path = os.path.join(staging, name)
        final_path = os.path.join(final, name)

        # Write data to staging file first
        with open(stage_path, "wb") as f:
            f.write(data)

        # Copy from staging to final with progress tracking
        iou.copy(
            stage_path,
            final_path,
            mode="auto",
            fsync=True,
            progress_cb=make_progress_cb(name),
        )
        os.unlink(stage_path)

    return time.perf_counter() - t0, progress_log


def verify_checksums(objects: List[Tuple[str, bytes]], final_dir: str) -> int:
    """Verify that written files match original content. Returns number of mismatches."""
    mismatches = 0
    for name, expected in objects:
        path = os.path.join(final_dir, name)
        if not os.path.exists(path):
            mismatches += 1
            continue
        with open(path, "rb") as f:
            actual = f.read()
        if hashlib.md5(actual).digest() != hashlib.md5(expected).digest():
            mismatches += 1
    return mismatches


def run(num_objects: int, size_mb: int) -> None:
    print(f"Objects: {num_objects}   Size: {size_mb} MiB each   Total: {num_objects * size_mb} MiB")
    print()

    objects = [(f"obj_{i:04d}.bin", make_object(i, size_mb)) for i in range(num_objects)]

    with tempfile.TemporaryDirectory(prefix="pyuring_ingest_") as tmpdir:
        for sub in ("staging_std", "final_std",
                    "staging_wm",  "final_wm",
                    "staging_prog", "final_prog"):
            os.makedirs(os.path.join(tmpdir, sub))

        # 1. Standard ingest
        t_std = ingest_standard(
            objects,
            os.path.join(tmpdir, "staging_std"),
            os.path.join(tmpdir, "final_std"),
        )
        throughput_std = (num_objects * size_mb) / t_std
        print(f"  Standard (sequential write+fsync): {t_std*1000:.0f}ms  {throughput_std:.1f} MiB/s")

        # 2. pyuring write_many
        try:
            t_wm = ingest_pyuring_write_many(
                objects,
                os.path.join(tmpdir, "staging_wm"),
                os.path.join(tmpdir, "final_wm"),
                size_mb,
            )
            throughput_wm = (num_objects * size_mb) / t_wm
            print(f"  pyuring write_many:                {t_wm*1000:.0f}ms  {throughput_wm:.1f} MiB/s")
        except UringError as e:
            print(f"  pyuring write_many: skipped ({e})")

        # 3. pyuring copy with progress
        t_prog, progress_log = ingest_pyuring_progress(
            objects,
            os.path.join(tmpdir, "staging_prog"),
            os.path.join(tmpdir, "final_prog"),
        )
        throughput_prog = (num_objects * size_mb) / t_prog
        print(f"  pyuring copy+progress:             {t_prog*1000:.0f}ms  {throughput_prog:.1f} MiB/s")

        print()

        # Verify
        mm = verify_checksums(objects, os.path.join(tmpdir, "final_std"))
        print(f"  Standard checksum:       {'OK' if mm == 0 else f'{mm} mismatches'}")
        mm = verify_checksums(objects, os.path.join(tmpdir, "final_prog"))
        print(f"  pyuring copy checksum:   {'OK' if mm == 0 else f'{mm} mismatches'}")

        # Show a sample progress trace
        sample_name = objects[0][0]
        if sample_name in progress_log:
            snaps = progress_log[sample_name]
            print()
            print(f"  Progress snapshots for {sample_name} ({len(snaps)} callbacks):")
            for done, total in snaps[:5]:
                pct = done / total * 100 if total else 0
                print(f"    {done:>10,} / {total:>10,} bytes  ({pct:.1f}%)")
            if len(snaps) > 5:
                print(f"    ... ({len(snaps) - 5} more)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Object storage ingest benchmark")
    parser.add_argument("--objects", type=int, default=10,
                        help="Number of objects to ingest (default: 10)")
    parser.add_argument("--size-mb", type=int, default=20,
                        help="Size of each object in MiB (default: 20)")
    args = parser.parse_args()

    try:
        run(args.objects, args.size_mb)
    except UringError as e:
        print(f"io_uring error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
