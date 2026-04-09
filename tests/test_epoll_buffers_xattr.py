"""epoll_ctl, provide_buffers / remove_buffers, xattr."""

from __future__ import annotations

import os
import select
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    EpollEvent,
    IORING_OP_EPOLL_CTL,
    IORING_OP_FGETXATTR,
    IORING_OP_FSETXATTR,
    IORING_OP_GETXATTR,
    IORING_OP_PROVIDE_BUFFERS,
    IORING_OP_REMOVE_BUFFERS,
    IORING_OP_SETXATTR,
    UringCtx,
)

_EPOLL_CTL_ADD = 1
_EPOLL_CTL_DEL = 2


class TestEpollBuffers(unittest.TestCase):
    def test_epoll_ctl_del_smoke(self):
        if not hasattr(select, "epoll"):
            self.skipTest("no epoll")
        ep = select.epoll()
        r, w = os.pipe()
        try:
            with UringCtx(entries=16) as ring:
                if not ring.probe_opcode_supported(IORING_OP_EPOLL_CTL):
                    self.skipTest("epoll_ctl not supported")
                ev = EpollEvent()
                ev.events = getattr(select, "EPOLLIN", 1)
                ev.data = 0
                ring.epoll_ctl(ep.fileno(), r, _EPOLL_CTL_ADD, ev)
                ring.epoll_ctl(ep.fileno(), r, _EPOLL_CTL_DEL, None)
        finally:
            os.close(r)
            os.close(w)
            ep.close()

    def test_provide_remove_buffers(self):
        pool = bytearray(4096)
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_PROVIDE_BUFFERS):
                self.skipTest("provide_buffers not supported")
            ring.provide_buffers(pool, 512, 8, bgid=3, bid=0)
            if ring.probe_opcode_supported(IORING_OP_REMOVE_BUFFERS):
                ring.remove_buffers(8, bgid=3)


class TestXattr(unittest.TestCase):
    def test_set_get_xattr(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            path = f.name
            f.write("x")
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                with UringCtx(entries=16) as ring:
                    if not ring.probe_opcode_supported(IORING_OP_SETXATTR):
                        self.skipTest("setxattr not supported")
                    try:
                        ring.setxattr(path, "user.pyuring_test", b"hi", 0)
                    except OSError:
                        self.skipTest("xattr not supported on fs")
                    if not ring.probe_opcode_supported(IORING_OP_GETXATTR):
                        self.skipTest("getxattr not supported")
                    out = bytearray(64)
                    ln = ring.getxattr(path, "user.pyuring_test", out)
                    self.assertGreaterEqual(ln, 0)
                    if ring.probe_opcode_supported(IORING_OP_FGETXATTR) and ring.probe_opcode_supported(
                        IORING_OP_FSETXATTR
                    ):
                        ring.fsetxattr(fd, "user.pyuring_f", b"z", 0)
                        out2 = bytearray(64)
                        ring.fgetxattr(fd, "user.pyuring_f", out2)
            finally:
                os.close(fd)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
