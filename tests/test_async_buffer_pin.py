"""read_async/write_async buffer pinning and user_data uniqueness."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import UringCtx


class TestAsyncBufferPin(unittest.TestCase):
    def test_duplicate_user_data_raises(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"aa")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with UringCtx(entries=8) as ring:
                    b1 = bytearray(4)
                    b2 = bytearray(4)
                    ring.read_async(fd, b1, offset=0, user_data=1)
                    with self.assertRaises(ValueError) as cm:
                        ring.read_async(fd, b2, offset=0, user_data=1)
                    self.assertIn("user_data", str(cm.exception))
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_keepalive_released_after_wait(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"x")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with UringCtx(entries=8) as ring:
                    buf = bytearray(8)
                    ring.read_async(fd, buf, offset=0, user_data=42)
                    ring.submit()
                    self.assertIn(42, ring._async_io_keepalive)
                    u, res = ring.wait_completion()
                    self.assertEqual(u, 42)
                    self.assertEqual(res, 1)
                    self.assertNotIn(42, ring._async_io_keepalive)
            finally:
                os.close(fd)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
