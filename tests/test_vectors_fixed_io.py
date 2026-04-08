"""readv_fixed / writev_fixed (registered buffers + fixed file indices)."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import IORING_OP_READV_FIXED, IORING_OP_WRITEV_FIXED, UringCtx


class TestVectorFixedIO(unittest.TestCase):
    def test_readv_fixed_writev_fixed_roundtrip(self):
        payload = b"vec-fixed-single-block"
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(payload)
            f.flush()
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                with UringCtx(entries=16) as ring:
                    if not ring.probe_opcode_supported(IORING_OP_READV_FIXED):
                        self.skipTest("readv_fixed not supported")
                    if not ring.probe_opcode_supported(IORING_OP_WRITEV_FIXED):
                        self.skipTest("writev_fixed not supported")
                    buf = bytearray(64)
                    ring.register_buffers([buf])
                    n = ring.readv_fixed(fd, [memoryview(buf)[: len(payload)]], 0, 0, 0)
                    self.assertEqual(n, len(payload))
                    self.assertEqual(bytes(buf[: len(payload)]), payload)
                    os.ftruncate(fd, 0)
                    out = bytearray(8)
                    out[:4] = b"ABCD"
                    ring.unregister_buffers()
                    ring.register_buffers([out])
                    n2 = ring.writev_fixed(fd, [memoryview(out)[:4]], 0, 0, 0)
                    self.assertEqual(n2, 4)
                    ring.unregister_buffers()
            finally:
                os.close(fd)
            with open(path, "rb") as rf:
                self.assertEqual(rf.read(), b"ABCD")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
