"""poll_add / poll_remove, tee, symlinkat, linkat."""

from __future__ import annotations

import os
import select
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    IORING_OP_LINKAT,
    IORING_OP_POLL_ADD,
    IORING_OP_POLL_REMOVE,
    IORING_OP_SYMLINKAT,
    IORING_OP_TEE,
    UringCtx,
    UringError,
)


class TestPoll(unittest.TestCase):
    def test_poll_add_pipe_readable(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_POLL_ADD):
                self.skipTest("poll_add not supported")
            r, w = os.pipe()
            try:
                os.write(w, b"x")
                ev = ring.poll_add(r, select.POLLIN, user_data=77_001)
                self.assertTrue(ev & select.POLLIN)
            finally:
                os.close(r)
                os.close(w)

    def test_poll_remove_no_such_request(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_POLL_REMOVE):
                self.skipTest("poll_remove not supported")
            try:
                ring.poll_remove(0x1234_5678_ABCD)
            except UringError:
                pass


class TestTee(unittest.TestCase):
    def test_tee_between_pipes(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_TEE):
                self.skipTest("tee not supported")
            p1 = os.pipe()
            p2 = os.pipe()
            try:
                os.write(p1[1], b"ab")
                n = ring.tee(p1[0], p2[1], 2, 0)
                self.assertGreaterEqual(n, 0)
                out = os.read(p2[0], 8)
                self.assertEqual(out, b"ab")
            finally:
                for f in p1 + p2:
                    os.close(f)


class TestSymlinkLink(unittest.TestCase):
    def test_symlinkat_and_linkat(self):
        with tempfile.TemporaryDirectory() as tmp:
            with UringCtx(entries=8) as ring:
                if not ring.probe_opcode_supported(IORING_OP_SYMLINKAT):
                    self.skipTest("symlinkat not supported")
                dfd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    ring.symlinkat("target-name", "sym", new_dir_fd=dfd)
                finally:
                    os.close(dfd)
                self.assertTrue(os.path.islink(os.path.join(tmp, "sym")))

            pa = os.path.join(tmp, "hard_a")
            pb = os.path.join(tmp, "hard_b")
            with open(pa, "w") as f:
                f.write("x")
            with UringCtx(entries=8) as ring:
                if not ring.probe_opcode_supported(IORING_OP_LINKAT):
                    self.skipTest("linkat not supported")
                dfd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    ring.linkat("hard_a", "hard_b", old_dir_fd=dfd, new_dir_fd=dfd, flags=0)
                finally:
                    os.close(dfd)
            self.assertTrue(os.path.samefile(pa, pb))


if __name__ == "__main__":
    unittest.main()
