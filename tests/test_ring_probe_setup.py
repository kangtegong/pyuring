"""UAPI opcode constants, nop, probe, optional setup flags."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import (
    IORING_OP_FSYNC,
    IORING_OP_READ,
    IORING_OP_READ_FIXED,
    IORING_OP_SHUTDOWN,
    IORING_OP_SPLICE,
    IORING_OP_WRITE,
    IORING_OP_WRITE_FIXED,
    IORING_SETUP_COOP_TASKRUN,
    IORING_SETUP_SINGLE_ISSUER,
    UringCtx,
    UringError,
)


class TestUapiConstants(unittest.TestCase):
    def test_opcode_values_match_kernel_enum(self):
        self.assertEqual(IORING_OP_FSYNC, 3)
        self.assertEqual(IORING_OP_READ_FIXED, 4)
        self.assertEqual(IORING_OP_WRITE_FIXED, 5)
        self.assertEqual(IORING_OP_SPLICE, 30)
        self.assertEqual(IORING_OP_SHUTDOWN, 34)


class TestNop(unittest.TestCase):
    def test_nop_completes(self):
        with UringCtx(entries=8) as ring:
            ring.nop()


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


if __name__ == "__main__":
    unittest.main()
