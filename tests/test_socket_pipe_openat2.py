"""IORING_OP_SOCKET / PIPE, sendmsg/recvmsg, openat2 + ftruncate."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    AT_FDCWD,
    IORING_OP_FTRUNCATE,
    IORING_OP_OPENAT2,
    IORING_OP_PIPE,
    IORING_OP_RECVMSG,
    IORING_OP_SENDMSG,
    IORING_OP_SOCKET,
    OpenHow,
    UringCtx,
)


class TestSocketPipe(unittest.TestCase):
    def test_socket_and_pipe(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_SOCKET):
                self.skipTest("socket op not supported")
            if not ring.probe_opcode_supported(IORING_OP_PIPE):
                self.skipTest("pipe op not supported")
            sfd = ring.socket(socket.AF_INET, socket.SOCK_DGRAM, 0, 0)
            os.close(sfd)
            r, w = ring.pipe(0)
            os.close(r)
            os.close(w)


class TestSendmsgRecvmsg(unittest.TestCase):
    def test_socketpair_roundtrip(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        try:
            with UringCtx(entries=16) as ring:
                if not ring.probe_opcode_supported(IORING_OP_SENDMSG) or not ring.probe_opcode_supported(
                    IORING_OP_RECVMSG
                ):
                    self.skipTest("sendmsg/recvmsg not supported")
                n = ring.sendmsg_iov(a.fileno(), [b"ping"], 0)
                self.assertGreater(n, 0)
                buf = bytearray(16)
                m = ring.recvmsg_iov(b.fileno(), [buf], 0)
                self.assertGreater(m, 0)
                self.assertEqual(bytes(buf[:m]), b"ping")
        finally:
            a.close()
            b.close()


class TestOpenat2Ftruncate(unittest.TestCase):
    def test_openat2_and_ftruncate(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            path = f.name
            f.write("truncate-me")
        try:
            with UringCtx(entries=16) as ring:
                if not ring.probe_opcode_supported(IORING_OP_OPENAT2):
                    self.skipTest("openat2 not supported")
                how = OpenHow()
                how.flags = os.O_RDONLY
                how.mode = 0
                how.resolve = 0
                fd = ring.openat2(path, how, dir_fd=AT_FDCWD)
                try:
                    if ring.probe_opcode_supported(IORING_OP_FTRUNCATE):
                        ring.ftruncate(fd, 4)
                finally:
                    os.close(fd)
            with open(path, "rb") as rf:
                data = rf.read()
            if len(data) == 4:
                self.assertEqual(data, b"trun")
            else:
                self.assertEqual(data, b"truncate-me")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
