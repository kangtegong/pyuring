"""asyncio completion integration (:class:`pyuring.aio.UringAsync`)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import UringCtx
from pyuring.aio import UringAsync, wait_completion_in_executor
from pyuring.native.errors import UringError


class TestUringAsync(unittest.TestCase):
    def test_ring_fd_positive(self):
        with UringCtx(entries=8) as ctx:
            fd = ctx.ring_fd
            self.assertIsInstance(fd, int)
            self.assertGreaterEqual(fd, 0)

    def test_async_read_one_completion(self):
        async def run():
            data = b"hello asyncio"
            with tempfile.NamedTemporaryFile(delete=False) as f:
                path = f.name
                f.write(data)
                f.flush()
            try:
                with UringCtx(entries=32) as ctx:
                    fd = os.open(path, os.O_RDONLY)
                    try:
                        buf = bytearray(len(data))
                        ctx.read_async(fd, buf, offset=0, user_data=42)
                        async with UringAsync(ctx) as ua:
                            ud, res = await ua.wait_completion()
                        self.assertEqual(ud, 42)
                        self.assertEqual(res, len(data))
                        self.assertEqual(bytes(buf), data)
                    finally:
                        os.close(fd)
            finally:
                os.unlink(path)

        asyncio.run(run())

    def test_wait_completion_in_executor(self):
        async def run():
            data = b"executor path"
            with tempfile.NamedTemporaryFile(delete=False) as f:
                path = f.name
                f.write(data)
                f.flush()
            try:
                with UringCtx(entries=32) as ctx:
                    fd = os.open(path, os.O_RDONLY)
                    try:
                        buf = bytearray(len(data))
                        ctx.read_async(fd, buf, offset=0, user_data=7)
                        ud, res = await wait_completion_in_executor(ctx)
                        self.assertEqual(ud, 7)
                        self.assertEqual(res, len(data))
                        self.assertEqual(bytes(buf), data)
                    finally:
                        os.close(fd)
            finally:
                os.unlink(path)

        asyncio.run(run())

    def test_reject_closed_ctx_at_init(self):
        ctx = UringCtx(entries=8)
        ctx.close()
        with self.assertRaises(UringError):
            UringAsync(ctx)


if __name__ == "__main__":
    unittest.main()
