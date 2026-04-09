#!/usr/bin/env python3
"""
Example: same shards as before/, submitted to io_uring in batches (similar role
to prefetching many files for training).

To combine with torch Dataset/DataLoader, run this pattern inside a worker with
one UringCtx per worker, or prefetch from the main process — mind process/thread
lifetime and that UringCtx is not shared across threads unsafely.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringCtx, UringError


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        with open(p, "wb") as f:
            f.write(bytes([i & 0xFF]) * (size_kb * 1024))
        paths.append(p)
    return paths


def load_pyuring_batched(paths: List[str], batch_size: int) -> List[bytes]:
    if not paths:
        return []
    file_size = os.path.getsize(paths[0])
    out: List[bytes | None] = [None] * len(paths)

    with iou.UringCtx(entries=max(batch_size, 64), setup_flags=0) as ctx:
        i = 0
        while i < len(paths):
            batch = paths[i : i + batch_size]
            fds = []
            bufs = []
            for j, path in enumerate(batch):
                fd = os.open(path, os.O_RDONLY)
                fds.append(fd)
                b = bytearray(file_size)
                bufs.append(b)
                ctx.read_async(fd, b, offset=0, user_data=j)
            ctx.submit()
            for _ in range(len(batch)):
                ud, n = ctx.wait_completion()
                if n < 0:
                    raise UringError(-n, "shard_read")
                out[i + ud] = bytes(bufs[ud][:n])
            for fd in fds:
                os.close(fd)
            i += batch_size

    return [b for b in out if b is not None]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="pyuring_pt_") as d:
        paths = create_shards(d, args.shards, args.size_kb)
        blobs = load_pyuring_batched(paths, args.batch_size)
        total = sum(len(b) for b in blobs)
        print(f"pyuring batched (bs={args.batch_size}): {args.shards} shards, {total} bytes total")


if __name__ == "__main__":
    main()
