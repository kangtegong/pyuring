#!/usr/bin/env python3
"""
Example: same /payload endpoint using UringAsync + UringCtx (one shared ring
for the app lifetime via lifespan).

Dependencies: pip install fastapi uvicorn
Run: uvicorn main:app --host 127.0.0.1 --port 8766
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Union

from fastapi import FastAPI

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import pyuring as iou
from pyuring import UringAsync, UringCtx, UringError

_PAYLOAD_BYTES = 32 * 1024 * 1024


async def read_file_uring(path: str, ctx: UringCtx, ua: UringAsync) -> bytes:
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
            ud, n = await ua.wait_completion()
            if n < 0:
                raise UringError(-n, "read_payload")
            got[ud] = n
        return b"".join(bytes(bufs[i][: got[i]]) for i in range(nblocks))
    finally:
        os.close(fd)


@asynccontextmanager
async def lifespan(app: FastAPI):
    root = Path(__file__).resolve().parent
    sample = root / "sample_payload.bin"
    sample.write_bytes(bytes(i % 256 for i in range(_PAYLOAD_BYTES)))

    ctx = iou.UringCtx(entries=128)
    ua = UringAsync(ctx)
    app.state.payload_path = str(sample)
    app.state.uring_ctx = ctx
    app.state.uring_async = ua

    yield

    ua.close()
    ctx.close()
    sample.unlink(missing_ok=True)


app = FastAPI(title="pyuring examples — FastAPI after", lifespan=lifespan)


@app.get("/payload")
async def read_payload() -> Dict[str, Union[int, str]]:
    path = app.state.payload_path
    ctx: UringCtx = app.state.uring_ctx
    ua: UringAsync = app.state.uring_async
    data = await read_file_uring(path, ctx, ua)
    return {"method": "UringAsync", "bytes": len(data)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8766, reload=False)
