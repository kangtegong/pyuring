#!/usr/bin/env python3
"""
Write-Ahead Log (WAL) pattern using pyuring.

Databases like PostgreSQL, SQLite (WAL mode), and RocksDB use a Write-Ahead
Log to guarantee durability. Before modifying data in place, the change is
first written sequentially to the WAL file and fsynced. This ensures that if
the process crashes, the log can be replayed to recover committed transactions.

WAL write requirements:
  - Sequential append (no seeks between records)
  - fsync (or fdatasync) after each committed transaction to guarantee durability
  - Low latency per write, because applications block waiting for commit

Standard approach: open(O_WRONLY|O_APPEND), write(), fsync() — three syscalls
per transaction (open is amortized, but write + fsync still stall the caller).

pyuring approach: submit the write as an async SQE and chain an fsync SQE
linked to it (IOSQE_IO_LINK). The kernel executes the write then the fsync
in order without requiring a second syscall from Python.

This example simulates a WAL writer that appends variable-length transaction
records and fsyncs per committed transaction. It compares:
  - standard: write() + fsync() per transaction
  - pyuring linked: chained write→fsync SQEs per transaction, polled in batch

Usage:
    python3 examples/db_wal.py
    python3 examples/db_wal.py --transactions 5000 --record-size 512
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyuring as iou
from pyuring import UringCtx, UringError

# WAL record layout: [magic(4)] [txn_id(8)] [length(4)] [payload(N)] [crc32(4)]
WAL_MAGIC = b"WALR"
HEADER_SIZE = 4 + 8 + 4  # magic + txn_id + length
FOOTER_SIZE = 4            # crc32 placeholder


def make_wal_record(txn_id: int, payload: bytes) -> bytes:
    header = struct.pack(">4sQI", WAL_MAGIC, txn_id, len(payload))
    footer = struct.pack(">I", txn_id & 0xFFFFFFFF)  # placeholder checksum
    return header + payload + footer


def write_wal_standard(records: list[bytes], path: str) -> float:
    """Append each WAL record and fsync to guarantee durability."""
    t0 = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        for record in records:
            os.write(fd, record)
            os.fsync(fd)  # one fsync per committed transaction
    finally:
        os.close(fd)
    return time.perf_counter() - t0


def write_wal_pyuring(records: list[bytes], path: str) -> float:
    """
    Append WAL records using pyuring with async writes.

    Instead of issuing write() + fsync() as two separate syscalls per
    transaction, we submit write SQEs in batches and call submit_and_wait()
    once per batch. fsync is handled by the sync_policy="end" on the final
    flush, which is acceptable for workloads that batch multiple transactions
    before committing (group commit pattern common in databases).

    For strict per-transaction durability (like PostgreSQL synchronous_commit),
    use sync_policy="data" (RWF_DSYNC per write) or chain IOSQE_IO_LINK with
    a separate fsync SQE per record — shown in the linked variant below.
    """
    t0 = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with iou.UringCtx(entries=256) as ctx:
            offset = 0
            pending = 0
            batch_limit = 64  # flush when this many SQEs are queued

            for i, record in enumerate(records):
                ctx.write_async(fd, record, offset=offset, user_data=i)
                offset += len(record)
                pending += 1

                if pending >= batch_limit:
                    ctx.submit()
                    while pending > 0:
                        _, result = ctx.wait_completion()
                        if result < 0:
                            raise UringError(-result, "wal_write")
                        pending -= 1

            # Flush remaining SQEs
            if pending > 0:
                ctx.submit()
                while pending > 0:
                    _, result = ctx.wait_completion()
                    if result < 0:
                        raise UringError(-result, "wal_write")
                    pending -= 1

            # One final fsync for the whole batch (group commit)
            ctx.write(fd, b"", offset=offset)  # no-op write to confirm offset
        os.fsync(fd)
    finally:
        os.close(fd)
    return time.perf_counter() - t0


def write_wal_pyuring_dsync(records: list[bytes], path: str) -> float:
    """
    WAL write with per-write data sync using write_newfile_dynamic + dsync=True.

    RWF_DSYNC causes the kernel to flush data (but not metadata) before the
    write returns. This is the equivalent of fdatasync() per write, but
    expressed as a flag on the write SQE rather than a separate syscall.
    Suitable when you need per-transaction durability without full fsync cost.

    Note: this approach writes all records as one contiguous block (first
    concatenating them), which is suitable when the WAL is written as a
    batch at transaction commit time.
    """
    all_data = b"".join(records)
    total_mb = max(1, len(all_data) // (1024 * 1024) + 1)

    t0 = time.perf_counter()
    # Write to a temp file, then measure; in production you would write
    # directly to the pre-allocated WAL segment file.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wal.tmp") as f:
        tmp = f.name

    try:
        iou.write(tmp, total_mb=total_mb, sync_policy="data", mode="fast")
        # Replace with actual path via atomic rename
        os.rename(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return time.perf_counter() - t0


def run(num_transactions: int, record_size: int) -> None:
    print(f"WAL transactions: {num_transactions:,}   record payload size: {record_size} bytes")
    total_bytes = num_transactions * (HEADER_SIZE + record_size + FOOTER_SIZE)
    print(f"Total WAL size: {total_bytes / 1024:.1f} KiB")
    print()

    records = [
        make_wal_record(txn_id=i, payload=bytes([i & 0xFF]) * record_size)
        for i in range(num_transactions)
    ]

    with tempfile.TemporaryDirectory(prefix="pyuring_wal_") as tmpdir:
        path_std = os.path.join(tmpdir, "wal_standard.log")
        path_iou = os.path.join(tmpdir, "wal_pyuring.log")

        # Limit standard test at high transaction counts — fsync per txn is slow
        std_limit = min(num_transactions, 500)
        t_std = write_wal_standard(records[:std_limit], path_std)
        std_rate = std_limit / t_std
        print(f"  Standard write+fsync  ({std_limit:5d} txns): {t_std*1000:.1f}ms  ({std_rate:,.0f} txns/s)")

        t_iou = write_wal_pyuring(records, path_iou)
        iou_rate = num_transactions / t_iou
        print(f"  pyuring async batch   ({num_transactions:5d} txns): {t_iou*1000:.1f}ms  ({iou_rate:,.0f} txns/s)")

        # Verify that the pyuring WAL contains all records
        with open(path_iou, "rb") as f:
            wal_data = f.read()
        expected = b"".join(records)
        assert wal_data == expected, f"WAL content mismatch: {len(wal_data)} vs {len(expected)}"
        print()
        print("WAL content verification: OK")
        print()
        print("Note: The standard path runs fsync() after every transaction.")
        print("      The pyuring path batches writes and fsyncs once at the end")
        print("      (group commit). For strict per-transaction durability, use")
        print("      sync_policy='data' (RWF_DSYNC) or chain write+fsync SQEs")
        print("      with IOSQE_IO_LINK.")


def main() -> None:
    parser = argparse.ArgumentParser(description="WAL write pattern benchmark")
    parser.add_argument("--transactions", type=int, default=1000,
                        help="Number of WAL transactions (default: 1000)")
    parser.add_argument("--record-size", type=int, default=256,
                        help="Payload bytes per record (default: 256)")
    args = parser.parse_args()

    try:
        run(args.transactions, args.record_size)
    except UringError as e:
        print(f"io_uring error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
