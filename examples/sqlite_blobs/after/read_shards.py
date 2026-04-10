#!/usr/bin/env python3
"""
Same shards as sqlite_blobs/before/, loaded with batched io_uring reads.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringError


def load_pyuring_batched(paths: List[str], batch_size: int) -> int:
    if not paths:
        return 0
    file_size = os.path.getsize(paths[0])
    total = 0

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
                total += n
            for fd in fds:
                os.close(fd)
            i += batch_size

    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory with shard_*.bin")
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    pattern = os.path.join(args.dir, "shard_*.bin")
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no shards under {args.dir}")

    n = load_pyuring_batched(paths, args.batch_size)
    print(f"pyuring (bs={args.batch_size}): {len(paths)} shards, {n} bytes")


if __name__ == "__main__":
    main()
