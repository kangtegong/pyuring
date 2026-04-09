#!/usr/bin/env python3
"""
Example: asyncio file read without blocking the loop (standard approach).

Offload synchronous read() to the loop's default executor — same idea as
asyncio.to_thread() on Python 3.9+:

    await loop.run_in_executor(None, read_sync)
"""

from __future__ import annotations

import asyncio
import os
import tempfile


async def read_file_via_executor(path: str) -> bytes:
    loop = asyncio.get_running_loop()

    def _read_sync() -> bytes:
        with open(path, "rb") as f:
            return f.read()

    return await loop.run_in_executor(None, _read_sync)


async def main() -> None:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello from asyncio (executor)\n" * 100)
        path = f.name
    try:
        data = await read_file_via_executor(path)
        print(f"read {len(data)} bytes via run_in_executor")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    asyncio.run(main())
