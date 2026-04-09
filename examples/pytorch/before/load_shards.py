#!/usr/bin/env python3
"""
Example: read many shard files concurrently with ThreadPoolExecutor — the usual
Python pattern and similar to what DataLoader workers often do. Does not import torch.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import List


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        with open(p, "wb") as f:
            f.write(bytes([i & 0xFF]) * (size_kb * 1024))
        paths.append(p)
    return paths


def read_one(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def load_threadpool(paths: List[str], workers: int) -> List[bytes]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(read_one, paths))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=64)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="pyuring_pt_") as d:
        paths = create_shards(d, args.shards, args.size_kb)
        blobs = load_threadpool(paths, args.workers)
        total = sum(len(b) for b in blobs)
        print(f"ThreadPoolExecutor ({args.workers} workers): {args.shards} shards, {total} bytes total")


if __name__ == "__main__":
    main()
