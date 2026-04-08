"""splice, timeouts, link_timeout, link_read_write, timeout_remove (invalid target)."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    IORING_OP_SPLICE,
    IORING_OP_TIMEOUT,
    IORING_OP_TIMEOUT_REMOVE,
    SPLICE_F_MOVE,
    UringCtx,
    UringError,
)


class TestSpliceTimeoutsLinks(unittest.TestCase):
    def test_splice_file_to_pipe(self):
        with UringCtx(entries=16) as r:
            if not r.probe_opcode_supported(IORING_OP_SPLICE):
                self.skipTest("splice not supported")
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"spliceme")
            f.flush()
        try:
            fd = os.open(path, os.O_RDONLY)
            pr, pw = os.pipe()
            try:
                with UringCtx(entries=16) as ring:
                    n = ring.splice(fd, 0, pw, -1, 8, SPLICE_F_MOVE)
                    self.assertEqual(n, 8)
                self.assertEqual(os.read(pr, 16), b"spliceme")
            finally:
                os.close(fd)
                os.close(pr)
                os.close(pw)
        finally:
            os.unlink(path)

    def test_relative_timeout_completes(self):
        with UringCtx(entries=8) as ring:
            ring.timeout(0, 50_000_000, user_data=777)

    def test_timeout_arm_remove_pair(self):
        with UringCtx(entries=8) as ring:
            ring.timeout_arm_remove_pair(120, 0, user_data=4242)

    def test_link_timeout_smoke(self):
        with UringCtx(entries=8) as ring:
            try:
                ring.link_timeout(0, 1_000_000, flags=0)
            except UringError:
                pass

    def test_timeout_remove_missing_target(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_TIMEOUT_REMOVE):
                self.skipTest("timeout_remove not supported")
            try:
                ring.timeout_remove(0x1234_5678_ABCD_BEEF, flags=0)
            except UringError:
                pass

    def test_link_read_write(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as fa:
            pa = fa.name
            fa.write(b"linked-data")
            fa.flush()
        pb = pa + ".out"
        try:
            fda = os.open(pa, os.O_RDONLY)
            fdb = os.open(pb, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            try:
                buf = bytearray(11)
                with UringCtx(entries=8) as ring:
                    n = ring.link_read_write(fda, buf, 0, fdb, 0)
                    self.assertEqual(n, 11)
            finally:
                os.close(fda)
                os.close(fdb)
            with open(pb, "rb") as rf:
                self.assertEqual(rf.read(), b"linked-data")
        finally:
            os.unlink(pa)
            os.unlink(pb)


if __name__ == "__main__":
    unittest.main()
