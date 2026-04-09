#!/usr/bin/env python3
"""
Example: FastAPI route that reads a file via run_in_executor (typical pattern).

Dependencies: pip install fastapi uvicorn
Run: uvicorn main:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Union

from fastapi import FastAPI

# Large enough that one GET /payload is dominated by file read, not tiny-buffer noise.
_PAYLOAD_BYTES = 32 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    root = Path(__file__).resolve().parent
    sample = root / "sample_payload.bin"
    sample.write_bytes(bytes(i % 256 for i in range(_PAYLOAD_BYTES)))
    app.state.payload_path = str(sample)
    yield
    sample.unlink(missing_ok=True)


app = FastAPI(title="pyuring examples — FastAPI before", lifespan=lifespan)


@app.get("/payload")
async def read_payload() -> Dict[str, Union[int, str]]:
    path = app.state.payload_path
    loop = asyncio.get_running_loop()

    def _read() -> bytes:
        return Path(path).read_bytes()

    data: bytes = await loop.run_in_executor(None, _read)
    return {"method": "run_in_executor", "bytes": len(data)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
