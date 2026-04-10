#!/usr/bin/env python3
"""
Same split files as before/, read with batched io_uring :meth:`read_async`.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringError


def split_cache(src: str, tmpdir: str, chunk_kb: int) -> List[str]:
    chunk = chunk_kb * 1024
    paths = []
    with open(src, "rb") as f:
        i = 0
        while True:
            blob = f.read(chunk)
            if not blob:
                break
            p = os.path.join(tmpdir, f"part_{i:05d}.bin")
            with open(p, "wb") as out:
                out.write(blob)
            paths.append(p)
            i += 1
    return paths


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
                    raise UringError(-n, "part_read")
                total += n
            for fd in fds:
                os.close(fd)
            i += batch_size

    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cache",
        default=os.path.join(os.path.dirname(__file__), "..", "cached_blob.bin"),
    )
    ap.add_argument("--chunk-kb", type=int, default=128)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    src = os.path.abspath(args.cache)
    if not os.path.isfile(src):
        print(f"missing {src}; run fetch_data.py first", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="pyuring_cr_") as d:
        paths = split_cache(src, d, args.chunk_kb)
        n = load_pyuring_batched(paths, args.batch_size)
        print(f"pyuring batched (bs={args.batch_size}): {len(paths)} parts, {n} bytes")


if __name__ == "__main__":
    main()
