"""readv / writev."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import UringCtx


class TestVectorIO(unittest.TestCase):
    def test_readv_writev_roundtrip(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"abcdefghij")
            f.flush()
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                with UringCtx(entries=16) as ring:
                    a = bytearray(4)
                    b = bytearray(6)
                    n = ring.readv(fd, [a, b], 0)
                    self.assertEqual(n, 10)
                    self.assertEqual(bytes(a), b"abcd")
                    self.assertEqual(bytes(b), b"efghij")
                    os.ftruncate(fd, 0)
                    n2 = ring.writev(fd, [b"xy", b"zt"], 0)
                    self.assertEqual(n2, 4)
            finally:
                os.close(fd)
            with open(path, "rb") as rf:
                self.assertEqual(rf.read(), b"xyzt")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
