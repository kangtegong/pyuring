"""IORING_REGISTER_FILES / REGISTER_BUFFERS and read_fixed / write_fixed."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import UringCtx


class TestRegisterFilesAndBuffers(unittest.TestCase):
    def test_read_fixed_registered(self):
        data = b"hello-fixed-io-uring"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
            f.write(data)
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                buf = bytearray(4096)
                with UringCtx(entries=8) as ring:
                    ring.register_files([fd])
                    ring.register_buffers([buf])
                    n = ring.read_fixed(0, buf, 0, 0)
                    self.assertEqual(n, len(data))
                    self.assertEqual(bytes(buf[:n]), data)
                    ring.unregister_buffers()
                    ring.unregister_files()
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_write_fixed_registered(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                payload = bytearray(b"write-fixed-test")
                with UringCtx(entries=8) as ring:
                    ring.register_files([fd])
                    ring.register_buffers([payload])
                    n = ring.write_fixed(0, payload, 0, 0)
                    self.assertEqual(n, len(payload))
                    ring.unregister_buffers()
                    ring.unregister_files()
                os.fsync(fd)
            finally:
                os.close(fd)
            with open(path, "rb") as rf:
                self.assertEqual(rf.read(), bytes(payload))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
