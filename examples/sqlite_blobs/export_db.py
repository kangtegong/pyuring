#!/usr/bin/env python3
"""
Build a small SQLite DB with BLOB rows, then export each row to a flat ``shard_*.bin`` file.

The read benchmarks (before/after) only touch those files — a common "escape hatch"
from DB blobs to fast sequential I/O.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=32)
    ap.add_argument("--blob-kb", type=int, default=64)
    ap.add_argument(
        "--out-dir",
        default="",
        help="directory for shard files (default: temp dir printed to stdout)",
    )
    args = ap.parse_args()

    blob = bytes([(i * 17) & 0xFF for i in range(args.blob_kb * 1024)])

    if args.out_dir:
        out_dir = os.path.abspath(args.out_dir)
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = tempfile.mkdtemp(prefix="pyuring_sqlite_")

    db_path = os.path.join(out_dir, "blobs.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, data BLOB)")
        conn.execute("DELETE FROM t")
        conn.executemany(
            "INSERT INTO t (id, data) VALUES (?, ?)",
            [(i, blob) for i in range(args.rows)],
        )
        conn.commit()

        cur = conn.execute("SELECT id, data FROM t ORDER BY id")
        for row_id, data in cur:
            p = os.path.join(out_dir, f"shard_{row_id:04d}.bin")
            with open(p, "wb") as f:
                f.write(data)
    finally:
        conn.close()

    print(f"database: {db_path}")
    print(f"exported {args.rows} shards to {out_dir}")


if __name__ == "__main__":
    main()
