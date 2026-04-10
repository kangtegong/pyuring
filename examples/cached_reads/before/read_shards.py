#!/usr/bin/env python3
"""
Split-cache read: many small files (as after a download pipeline cached chunk files).
``before`` uses ThreadPoolExecutor + plain reads — typical first implementation.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import List


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


def read_one(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cache",
        default=os.path.join(os.path.dirname(__file__), "..", "cached_blob.bin"),
        help="large file produced by fetch_data.py",
    )
    ap.add_argument("--chunk-kb", type=int, default=128)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    src = os.path.abspath(args.cache)
    if not os.path.isfile(src):
        print(f"missing {src}; run fetch_data.py first", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="pyuring_cr_") as d:
        paths = split_cache(src, d, args.chunk_kb)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            blobs = list(ex.map(read_one, paths))
        n = sum(len(b) for b in blobs)
        print(f"ThreadPoolExecutor({args.workers}): {len(paths)} parts, {n} bytes")


if __name__ == "__main__":
    main()
