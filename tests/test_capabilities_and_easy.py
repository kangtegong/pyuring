"""Probe cache, high-level sync_policy, and progress/cancel on copy/write pipelines."""
from __future__ import annotations

import errno
import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring import (
    IORING_OP_NOP,
    IORING_OP_READ,
    copy,
    get_probe_info,
    opcode_supported,
    require_opcode_supported,
    write,
)
from pyuring.native.errors import UringError


class TestProbeCache(unittest.TestCase):
    def test_get_probe_info_cached(self):
        a = get_probe_info()
        b = get_probe_info()
        self.assertEqual(a.last_op, b.last_op)
        self.assertEqual(a.opcode_mask, b.opcode_mask)

    def test_get_probe_info_refresh(self):
        a = get_probe_info()
        c = get_probe_info(refresh=True)
        self.assertEqual(a.last_op, c.last_op)

    def test_opcode_supported_matches_read(self):
        self.assertTrue(opcode_supported(IORING_OP_READ))
        self.assertTrue(opcode_supported(IORING_OP_NOP))

    def test_require_opcode_supported_ok(self):
        require_opcode_supported(IORING_OP_READ)

    def test_require_opcode_supported_fail(self):
        bad = 1 << 20
        with self.assertRaises(UringError) as cm:
            require_opcode_supported(bad, "test_op")
        self.assertEqual(cm.exception.errno, errno.EOPNOTSUPP)


class TestEasySyncPolicy(unittest.TestCase):
    def test_write_sync_policy_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.dat")
            n = write(path, total_mb=1, mode="safe", sync_policy="end")
            self.assertGreater(n, 0)


class TestProgressCancel(unittest.TestCase):
    def test_copy_progress_cancel(self):
        data = b"x" * (256 * 1024)

        def prog(done: int, total: int) -> bool:
            return done >= 8192

        with tempfile.NamedTemporaryFile(delete=False) as src:
            src.write(data)
            src.flush()
            src_path = src.name
        dst_path = src_path + ".dst"
        try:
            with self.assertRaises(UringError) as cm:
                copy(
                    src_path,
                    dst_path,
                    mode="auto",
                    qd=4,
                    block_size=4096,
                    sync_policy="none",
                    progress_cb=prog,
                )
            self.assertEqual(cm.exception.errno, errno.ECANCELED)
        finally:
            for p in (src_path, dst_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_write_progress_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.dat")

            def prog(done: int, total: int) -> bool:
                return done > 0

            with self.assertRaises(UringError) as cm:
                write(
                    path,
                    total_mb=2,
                    mode="auto",
                    qd=8,
                    block_size=65536,
                    sync_policy="none",
                    progress_cb=prog,
                )
            self.assertEqual(cm.exception.errno, errno.ECANCELED)


if __name__ == "__main__":
    unittest.main()
