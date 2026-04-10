#!/usr/bin/env python3
"""
Same shards as before/, but reads via io_uring batched :meth:`read_async` and wraps
bytes with :func:`numpy.frombuffer` (no extra copy if you keep uint8 view).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import List

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringCtx, UringError


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        data = np.full(size_kb * 1024, i & 0xFF, dtype=np.uint8)
        data.tofile(p)
        paths.append(p)
    return paths


def load_pyuring_batched(paths: List[str], batch_size: int) -> List[int]:
    if not paths:
        return []
    file_size = os.path.getsize(paths[0])
    sums: List[int] = []

    with iou.UringCtx(entries=max(batch_size, 64), setup_flags=0) as ctx:
        i = 0
        while i < len(paths):
            batch = paths[i : i + batch_size]
            fds = []
            bufs: List[bytearray] = []
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
                arr = np.frombuffer(bufs[ud], dtype=np.uint8, count=n)
                sums.append(int(arr.sum()))
            for fd in fds:
                os.close(fd)
            i += batch_size

    return sums


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="pyuring_np_") as d:
        paths = create_shards(d, args.shards, args.size_kb)
        sums = load_pyuring_batched(paths, args.batch_size)
        print(f"pyuring + np.frombuffer (bs={args.batch_size}): {args.shards} shards, sum={sum(sums)}")


if __name__ == "__main__":
    main()
