"""API/usability: async file, UringError context, ResourceWarning on leaked native handles."""

from __future__ import annotations

import asyncio
import errno
import gc
import os
import tempfile
import unittest
import warnings

import tests._linux  # noqa: F401

import pyuring
from pyuring import UringCtx, UringError
from pyuring.native.errors import UringError as NUringError


class TestAsyncFileOpen(unittest.TestCase):
    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            pyuring.open("/tmp/x", "rt")

    def test_read_before_enter_raises(self):
        async def main():
            f = pyuring.open(__file__, "rb")
            with self.assertRaises(RuntimeError) as cm:
                await f.read()
            self.assertIn("async with", str(cm.exception))

        asyncio.run(main())

    def test_read_at_most_n_bytes(self):
        async def main():
            with tempfile.NamedTemporaryFile("w+b", delete=False) as tf:
                path = tf.name
                tf.write(b"abcdefghij")
                tf.flush()
            try:
                async with pyuring.open(path, "rb", prefer_uring=False) as af:
                    a = await af.read(4)
                    b = await af.read(4)
                    c = await af.read(4)
                self.assertEqual(a, b"abcd")
                self.assertEqual(b, b"efgh")
                self.assertEqual(c, b"ij")
            finally:
                os.unlink(path)

        asyncio.run(main())

    def test_read_roundtrip_rb(self):
        async def main():
            with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
                path = f.name
                f.write(b"hello-async")
                f.flush()
            try:
                async with pyuring.open(path, "rb") as af:
                    data = await af.read()
                self.assertEqual(data, b"hello-async")
            finally:
                os.unlink(path)

        asyncio.run(main())

    def test_write_wb(self):
        async def main():
            path = None
            try:
                fd, path = tempfile.mkstemp(suffix=".dat")
                os.close(fd)
                async with pyuring.open(path, "wb") as af:
                    n = await af.write(b"xyz")
                self.assertEqual(n, 3)
                with open(path, "rb") as rf:
                    self.assertEqual(rf.read(), b"xyz")
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        asyncio.run(main())

    def test_fallback_when_uring_disabled(self):
        async def main():
            with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
                path = f.name
                f.write(b"fb")
                f.flush()
            try:
                async with pyuring.open(path, "rb", prefer_uring=False) as af:
                    data = await af.read()
                self.assertEqual(data, b"fb")
            finally:
                os.unlink(path)

        asyncio.run(main())


class TestUringErrorContext(unittest.TestCase):
    def test_filename_offset_length(self):
        e = NUringError(errno.ENOENT, "uring_openat_sync", filename="/no/such", offset=10, length=4096)
        self.assertEqual(e.filename, "/no/such")
        self.assertEqual(e.offset, 10)
        self.assertEqual(e.length, 4096)
        self.assertIn("/no/such", str(e))
        self.assertIn("offset=10", str(e))


class TestResourceWarningNative(unittest.TestCase):
    def test_uring_ctx_warns_if_not_closed(self):
        r = UringCtx(entries=8)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", ResourceWarning)
            del r
            gc.collect()
        self.assertTrue(any(issubclass(x.category, ResourceWarning) for x in w))


if __name__ == "__main__":
    unittest.main()
