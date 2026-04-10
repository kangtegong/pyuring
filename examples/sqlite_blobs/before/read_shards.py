#!/usr/bin/env python3
"""
Read exported ``shard_*.bin`` files (see export_db.py) with ThreadPoolExecutor.
"""

from __future__ import annotations

import argparse
import glob
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List


def read_one(path: str) -> int:
    with open(path, "rb") as f:
        return len(f.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dir",
        required=True,
        help="directory containing shard_*.bin from export_db.py",
    )
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    pattern = os.path.join(args.dir, "shard_*.bin")
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no shards under {args.dir}")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        sizes = list(ex.map(read_one, paths))
    print(f"ThreadPoolExecutor({args.workers}): {len(paths)} shards, {sum(sizes)} bytes")


if __name__ == "__main__":
    main()
