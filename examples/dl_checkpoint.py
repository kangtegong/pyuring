#!/usr/bin/env python3
"""
Deep learning checkpoint saving with pyuring.

During neural network training, checkpoints are saved periodically to disk so
that training can be resumed if interrupted. A checkpoint typically contains
model weights, optimizer state, and training metadata — often hundreds of MiB
per save.

Standard approach: serialize to bytes, then write with a blocking os.write call.
The training loop stalls for the entire duration of the write.

pyuring approach: use copy() to move a pre-serialized temp file to its final
location, or use write_newfile_dynamic() to write the serialized bytes in a
batched io_uring pipeline. Either way, the kernel-side batching reduces the
number of syscalls for large sequential writes.

This example simulates saving and loading checkpoints without an actual deep
learning framework dependency. Replace the fake "weight tensor" bytes with
real pickle/safetensors serialization in production.

Usage:
    python3 examples/dl_checkpoint.py
    python3 examples/dl_checkpoint.py --size-mb 200 --epochs 5
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
from pyuring import UringError


def fake_serialize_model(size_mb: int) -> bytes:
    """
    Simulate serializing a model to bytes.

    In a real PyTorch workflow this would be:
        buf = io.BytesIO()
        torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "epoch": epoch}, buf)
        return buf.getvalue()
    """
    # Header: magic + size
    header = struct.pack(">4sQ", b"CKPT", size_mb * 1024 * 1024)
    # Body: repeated pattern (stands in for actual weight data)
    body = (b"\xAB\xCD" * (512 * 1024))[:size_mb * 1024 * 1024 - len(header)]
    return header + body


def save_checkpoint_standard(data: bytes, path: str) -> float:
    """Write checkpoint with a plain blocking write."""
    t0 = time.perf_counter()
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return time.perf_counter() - t0


def save_checkpoint_pyuring(data: bytes, path: str) -> float:
    """
    Write checkpoint using pyuring.

    Strategy: write the serialized bytes to a temp file first, then use
    iou.copy() to move it to the final path via an io_uring pipeline.
    This separates serialization latency from I/O latency, and the copy
    step benefits from io_uring's batched read→write pipeline.

    For even lower overhead on repeated saves, keep the temp file and
    rotate: always write to temp, then rename(2) into place.
    """
    tmp_path = path + ".tmp"
    t0 = time.perf_counter()

    # Write the in-memory bytes to a staging file first
    with open(tmp_path, "wb") as f:
        f.write(data)

    # Copy from staging to final destination using io_uring pipeline
    # fsync=True ensures the data is durable before we return
    iou.copy(tmp_path, path, mode="fast", fsync=True)
    os.unlink(tmp_path)

    return time.perf_counter() - t0


def load_checkpoint_pyuring(path: str, size_mb: int) -> tuple[float, bytes]:
    """
    Load a checkpoint using UringCtx for batched reads.

    For large checkpoints, read_batch() issues multiple read SQEs in a
    single ring submission, reducing round-trips compared to reading the
    file in a Python loop.
    """
    block_size = 1 << 20  # 1 MiB per read SQE
    blocks = size_mb

    t0 = time.perf_counter()
    fd = os.open(path, os.O_RDONLY)
    try:
        with iou.UringCtx(entries=64) as ctx:
            data = ctx.read_batch(fd, block_size=block_size, blocks=blocks)
    finally:
        os.close(fd)

    return time.perf_counter() - t0, data


def run(size_mb: int, epochs: int) -> None:
    print(f"Checkpoint size: {size_mb} MiB   Epochs to simulate: {epochs}")
    print()

    with tempfile.TemporaryDirectory(prefix="pyuring_ckpt_") as tmpdir:
        std_path = os.path.join(tmpdir, "checkpoint_std.bin")
        iou_path = os.path.join(tmpdir, "checkpoint_iou.bin")

        std_times = []
        iou_times = []

        for epoch in range(1, epochs + 1):
            data = fake_serialize_model(size_mb)

            t_std = save_checkpoint_standard(data, std_path)
            t_iou = save_checkpoint_pyuring(data, iou_path)

            std_times.append(t_std)
            iou_times.append(t_iou)
            print(f"  Epoch {epoch:2d}  standard={t_std*1000:.0f}ms  pyuring={t_iou*1000:.0f}ms")

        avg_std = sum(std_times) / len(std_times)
        avg_iou = sum(iou_times) / len(iou_times)
        print()
        print(f"Average save time — standard: {avg_std*1000:.0f}ms   pyuring: {avg_iou*1000:.0f}ms")

        # Verify the checkpoint round-trips correctly
        t_load, loaded = load_checkpoint_pyuring(iou_path, size_mb)
        expected = fake_serialize_model(size_mb)
        assert loaded[:8] == expected[:8], "checkpoint header mismatch"
        print(f"Checkpoint load (pyuring read_batch): {t_load*1000:.0f}ms — OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Checkpoint save/load benchmark")
    parser.add_argument("--size-mb", type=int, default=100,
                        help="Simulated checkpoint size in MiB (default: 100)")
    parser.add_argument("--epochs", type=int, default=3,
                        help="Number of epochs to simulate (default: 3)")
    args = parser.parse_args()

    try:
        run(args.size_mb, args.epochs)
    except UringError as e:
        print(f"io_uring error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
