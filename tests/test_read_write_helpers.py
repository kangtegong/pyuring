"""UringCtx read, write, read_batch, read_offsets, submit/peek, async read + wait_completion."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import UringCtx


class TestReadWriteHelpers(unittest.TestCase):
    def test_read_write_simple(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"hello-read-write")
            f.flush()
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                with UringCtx(entries=8) as ring:
                    data = ring.read(fd, 5, 0)
                    self.assertEqual(data, b"hello")
                    n = ring.write(fd, b"ZZ", 16)
                    self.assertEqual(n, 2)
            finally:
                os.close(fd)
            with open(path, "rb") as rf:
                raw = rf.read()
            self.assertTrue(raw.startswith(b"hello"))
            self.assertTrue(raw.endswith(b"ZZ"))
        finally:
            os.unlink(path)

    def test_read_batch_and_offsets(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"abcdefghijklmnop")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with UringCtx(entries=16) as ring:
                    batch = ring.read_batch(fd, 4, 4, offset=0)
                    self.assertEqual(batch, b"abcdefghijklmnop")
                    off = ring.read_offsets(fd, 4, [0, 12], offset_bytes=True)
                    self.assertEqual(off, b"abcdmnop")
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_read_async_wait_completion(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"async-read-me")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with UringCtx(entries=8) as ring:
                    buf = bytearray(32)
                    ud = 99_001
                    ring.read_async(fd, buf, offset=0, user_data=ud)
                    ring.submit()
                    u2, res = ring.wait_completion()
                    self.assertEqual(u2, ud)
                    self.assertEqual(res, 13)
                    self.assertEqual(bytes(buf[:13]), b"async-read-me")
                    self.assertIsNone(ring.peek_completion())
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_submit_after_nop(self):
        with UringCtx(entries=8) as ring:
            ring.nop()
            n = ring.submit()
            self.assertGreaterEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
