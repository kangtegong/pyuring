"""sync_file_range, fadvise, madvise, async_cancel_fd."""

from __future__ import annotations

import mmap
import os
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    IORING_OP_FADVISE,
    IORING_OP_MADVISE,
    IORING_OP_SYNC_FILE_RANGE,
    MADV_WILLNEED,
    POSIX_FADV_SEQUENTIAL,
    SYNC_FILE_RANGE_WRITE,
    UringCtx,
    UringError,
)


class TestSyncAdvice(unittest.TestCase):
    def test_sync_file_range_and_fadvise(self):
        with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
            path = f.name
            f.write(b"\0" * 8192)
            f.flush()
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                with UringCtx(entries=8) as ring:
                    if ring.probe_opcode_supported(IORING_OP_SYNC_FILE_RANGE):
                        ring.sync_file_range(fd, 4096, 0, SYNC_FILE_RANGE_WRITE)
                    else:
                        self.skipTest("sync_file_range not supported")
                    if ring.probe_opcode_supported(IORING_OP_FADVISE):
                        ring.fadvise(fd, 0, 8192, POSIX_FADV_SEQUENTIAL)
                    else:
                        self.skipTest("fadvise not supported")
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_madvise(self):
        m = mmap.mmap(-1, 4096)
        try:
            with UringCtx(entries=8) as ring:
                if not ring.probe_opcode_supported(IORING_OP_MADVISE):
                    self.skipTest("madvise op not supported")
                ring.madvise(m, MADV_WILLNEED)
        finally:
            m.close()


class TestCancelFd(unittest.TestCase):
    def test_cancel_fd_smoke(self):
        with UringCtx(entries=8) as ring:
            r, w = os.pipe()
            try:
                try:
                    ring.async_cancel_fd(r, flags=0)
                except UringError:
                    pass
            finally:
                os.close(r)
                os.close(w)


if __name__ == "__main__":
    unittest.main()
