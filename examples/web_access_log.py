#!/usr/bin/env python3
"""
High-throughput access log writing for web servers using pyuring.

Web servers (nginx, gunicorn, uvicorn, etc.) write one log line per request.
Under high load — thousands of requests per second — these writes become a
bottleneck because each write(2) syscall flushes a small buffer to the kernel.

Two common approaches:
  1. Synchronous write per request: simple, but one syscall per log line.
  2. Batched write: accumulate lines in memory, flush periodically.

pyuring improves approach 2: when the batch is flushed, write_newfile_dynamic()
or a UringCtx write sequence submits the entire batch as a single io_uring
pipeline, issuing far fewer syscalls than writing line-by-line.

This example simulates a web server access log writer. It generates fake
Common Log Format lines and compares:
  - standard: one os.write per line (unbuffered, simulates synchronous logging)
  - batched standard: accumulate in memory, one write() per flush
  - pyuring batched: accumulate in memory, flush via io_uring write pipeline

Usage:
    python3 examples/web_access_log.py
    python3 examples/web_access_log.py --requests 50000 --batch-size 500
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyuring as iou
from pyuring import UringCtx, UringError

# Sample data for log line generation
_METHODS = ["GET", "POST", "PUT", "DELETE"]
_PATHS = ["/", "/api/users", "/api/orders", "/static/main.js", "/static/app.css",
          "/health", "/api/products", "/api/search", "/login", "/logout"]
_STATUS = [200, 200, 200, 200, 201, 204, 301, 304, 400, 404, 500]
_IPS = [f"192.168.1.{i}" for i in range(1, 50)]


def make_log_line(req_id: int) -> bytes:
    """Generate one Common Log Format access log line."""
    ip = _IPS[req_id % len(_IPS)]
    method = _METHODS[req_id % len(_METHODS)]
    path = _PATHS[req_id % len(_PATHS)]
    status = _STATUS[req_id % len(_STATUS)]
    size = random.randint(128, 8192)
    ts = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    return f'{ip} - - [{ts}] "{method} {path} HTTP/1.1" {status} {size}\n'.encode()


def write_logs_standard_unbuffered(lines: list[bytes], path: str) -> float:
    """Write one line at a time with a separate write() call each time."""
    t0 = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        for line in lines:
            os.write(fd, line)
    finally:
        os.close(fd)
    return time.perf_counter() - t0


def write_logs_standard_batched(lines: list[bytes], path: str, batch_size: int) -> float:
    """Accumulate lines into batches, write each batch with one write() call."""
    t0 = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        for i in range(0, len(lines), batch_size):
            batch = b"".join(lines[i:i + batch_size])
            os.write(fd, batch)
    finally:
        os.close(fd)
    return time.perf_counter() - t0


def write_logs_pyuring_batched(lines: list[bytes], path: str, batch_size: int) -> float:
    """
    Accumulate lines into batches, write each batch via UringCtx.

    Each batch is submitted as one async write SQE. After all batches are
    submitted, wait for completions in order. This reduces the number of
    kernel transitions compared to issuing one write(2) per batch.

    Important: each batch bytes object must stay alive until its completion
    is received. We track in-flight batches in a dict keyed by user_data so
    the Python GC does not free the buffer before the kernel write completes.
    """
    t0 = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with iou.UringCtx(entries=128) as ctx:
            offset = 0
            uid = 0
            in_flight: dict[int, bytes] = {}  # uid -> batch bytes (keeps buffer alive)

            for i in range(0, len(lines), batch_size):
                batch = b"".join(lines[i:i + batch_size])
                ctx.write_async(fd, batch, offset=offset, user_data=uid)
                in_flight[uid] = batch  # prevent GC until completion
                offset += len(batch)
                uid += 1

                # Drain when ring is half full to avoid SQ overflow
                if len(in_flight) >= 64:
                    ctx.submit()
                    while len(in_flight) >= 64:
                        done_uid, result = ctx.wait_completion()
                        del in_flight[done_uid]

            # Flush and drain remaining
            if in_flight:
                ctx.submit()
                while in_flight:
                    done_uid, result = ctx.wait_completion()
                    del in_flight[done_uid]
    finally:
        os.close(fd)
    return time.perf_counter() - t0


def run(num_requests: int, batch_size: int) -> None:
    print(f"Simulating {num_requests:,} access log lines  (batch size: {batch_size})")
    print()

    lines = [make_log_line(i) for i in range(num_requests)]
    total_bytes = sum(len(l) for l in lines)
    print(f"Total log data: {total_bytes / 1024:.1f} KiB")
    print()

    with tempfile.TemporaryDirectory(prefix="pyuring_log_") as tmpdir:
        path_unbuf = os.path.join(tmpdir, "access_unbuffered.log")
        path_std   = os.path.join(tmpdir, "access_standard.log")
        path_iou   = os.path.join(tmpdir, "access_pyuring.log")

        # Limit unbuffered test to avoid very long runtimes at high request counts
        unbuf_limit = min(num_requests, 5000)
        t_unbuf = write_logs_standard_unbuffered(lines[:unbuf_limit], path_unbuf)
        unbuf_rate = unbuf_limit / t_unbuf
        print(f"  Unbuffered write ({unbuf_limit} lines):  {t_unbuf*1000:.1f}ms  ({unbuf_rate:,.0f} lines/s)")

        t_std = write_logs_standard_batched(lines, path_std, batch_size)
        std_rate = num_requests / t_std
        print(f"  Batched standard  ({num_requests} lines): {t_std*1000:.1f}ms  ({std_rate:,.0f} lines/s)")

        t_iou = write_logs_pyuring_batched(lines, path_iou, batch_size)
        iou_rate = num_requests / t_iou
        print(f"  Batched pyuring   ({num_requests} lines): {t_iou*1000:.1f}ms  ({iou_rate:,.0f} lines/s)")

        # Verify output correctness
        with open(path_std, "rb") as f:
            std_data = f.read()
        with open(path_iou, "rb") as f:
            iou_data = f.read()
        assert std_data == iou_data, "log content mismatch between standard and pyuring"
        print()
        print("Output verification: OK (both log files are byte-identical)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Web access log write benchmark")
    parser.add_argument("--requests", type=int, default=20000,
                        help="Number of log lines to write (default: 20000)")
    parser.add_argument("--batch-size", type=int, default=200,
                        help="Lines per write batch (default: 200)")
    args = parser.parse_args()

    try:
        run(args.requests, args.batch_size)
    except UringError as e:
        print(f"io_uring error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
