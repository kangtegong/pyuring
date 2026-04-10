#!/usr/bin/env python3
"""
Read many binary shards with NumPy (:func:`numpy.fromfile`) and a thread pool —
common pattern for feeding numeric pipelines without torch.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import List

import numpy as np


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        data = np.full(size_kb * 1024, i & 0xFF, dtype=np.uint8)
        data.tofile(p)
        paths.append(p)
    return paths


def read_one(path: str) -> int:
    x = np.fromfile(path, dtype=np.uint8)
    return int(x.sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=32)
    ap.add_argument("--size-kb", type=int, default=64)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="pyuring_np_") as d:
        paths = create_shards(d, args.shards, args.size_kb)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            sums = list(ex.map(read_one, paths))
        print(f"numpy.fromfile + ThreadPoolExecutor({args.workers}): {args.shards} shards, sum={sum(sums)}")


if __name__ == "__main__":
    main()
