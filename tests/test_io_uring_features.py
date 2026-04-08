"""
Tests for ring registration, setup flags, and opcode probe (requires Linux + io_uring).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest


if sys.platform != "linux":
    raise unittest.SkipTest("io_uring is Linux-only")

from pyuring import (
    IORING_OP_READ,
    IORING_OP_READ_FIXED,
    IORING_OP_WRITE,
    IORING_OP_WRITE_FIXED,
    IORING_SETUP_COOP_TASKRUN,
    IORING_SETUP_SINGLE_ISSUER,
    UringCtx,
    UringError,
)


class TestProbe(unittest.TestCase):
    def test_probe_read_write_supported(self):
        with UringCtx(entries=64) as ring:
            self.assertTrue(ring.probe_opcode_supported(IORING_OP_READ))
            self.assertTrue(ring.probe_opcode_supported(IORING_OP_WRITE))
            lo = ring.probe_last_op()
            self.assertGreaterEqual(lo, IORING_OP_WRITE)

    def test_probe_fixed_supported(self):
        with UringCtx(entries=64) as ring:
            self.assertTrue(ring.probe_opcode_supported(IORING_OP_READ_FIXED))
            self.assertTrue(ring.probe_opcode_supported(IORING_OP_WRITE_FIXED))

    def test_probe_mask_matches_per_opcode(self):
        with UringCtx(entries=64) as ring:
            mask = ring.probe_supported_mask()
            lo = ring.probe_last_op()
            self.assertEqual(len(mask), lo + 1)
            for i in range(lo + 1):
                self.assertEqual(mask[i], 1 if ring.probe_opcode_supported(i) else 0)


class TestSetupFlags(unittest.TestCase):
    def test_single_issuer_coop_taskrun_readable(self):
        flags = IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_COOP_TASKRUN
        try:
            ring = UringCtx(entries=8, setup_flags=flags)
        except UringError as e:
            self.skipTest(f"kernel rejected setup flags: {e}")
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
            f.write(b"abc")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with ring:
                    out = ring.read(fd, 3, 0)
                    self.assertEqual(out, b"abc")
            finally:
                os.close(fd)
        finally:
            os.unlink(path)


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
