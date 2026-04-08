"""openat, close, fsync, fallocate, statx, renameat, unlinkat, mkdirat."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import AT_REMOVEDIR, FALLOC_FL_KEEP_SIZE, FALLOC_FL_ZERO_RANGE, UringCtx


class TestVfsOps(unittest.TestCase):
    def test_openat_close_mkdir_rename_unlink_statx_fallocate_fsync(self):
        td = tempfile.mkdtemp()
        try:
            sub = os.path.join(td, "d1")
            p1 = os.path.join(sub, "a.txt")
            p2 = os.path.join(sub, "b.txt")
            with UringCtx(entries=32) as ring:
                ring.mkdirat(sub, 0o755)
                fd = ring.openat(p1, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o644)
                try:
                    os.write(fd, b"hello-statx")
                    ring.fsync_fd(fd)
                    ring.fsync_fd(fd, datasync=True)
                    sz = ring.statx(p1)
                    self.assertEqual(sz, 11)
                    ring.fallocate_fd(fd, FALLOC_FL_ZERO_RANGE | FALLOC_FL_KEEP_SIZE, 11, 4096)
                finally:
                    ring.close_fd(fd)
                ring.renameat(p1, p2)
                self.assertFalse(os.path.exists(p1))
                self.assertTrue(os.path.isfile(p2))
                ring.unlinkat(p2)
                ring.unlinkat(sub, flags=AT_REMOVEDIR)
                self.assertFalse(os.path.exists(sub))
        finally:
            try:
                os.rmdir(td)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
