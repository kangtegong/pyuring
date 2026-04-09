#!/usr/bin/env python3
"""
Example: same goal as asyncio/before (non-blocking file read) using UringAsync.

The io_uring completion-queue fd is registered with the event loop (add_reader),
so kernel completions are delivered as loop callbacks without a thread pool
on the read path.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringAsync, UringCtx, UringError


async def read_file_via_uring(path: str, ctx: UringCtx, ua: UringAsync) -> bytes:
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        if size == 0:
            return b""

        block = min(size, 64 * 1024)
        nblocks = (size + block - 1) // block
        bufs: list[bytearray] = []
        for i in range(nblocks):
            off = i * block
            ln = min(block, size - off)
            b = bytearray(ln)
            bufs.append(b)
            ctx.read_async(fd, b, offset=off, user_data=i)
        ctx.submit()

        got: dict[int, int] = {}
        for _ in range(nblocks):
            user_data, n_bytes = await ua.wait_completion()
            if n_bytes < 0:
                raise UringError(-n_bytes, "read_file_via_uring")
            got[user_data] = n_bytes

        parts = [bytes(bufs[i][: got[i]]) for i in range(nblocks)]
        return b"".join(parts)
    finally:
        os.close(fd)


async def main() -> None:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello from asyncio (io_uring)\n" * 100)
        path = f.name

    ctx = UringCtx(entries=64)
    ua = UringAsync(ctx)
    try:
        data = await read_file_via_uring(path, ctx, ua)
        print(f"read {len(data)} bytes via UringAsync")
    finally:
        ua.close()
        ctx.close()
        os.unlink(path)


if __name__ == "__main__":
    asyncio.run(main())
