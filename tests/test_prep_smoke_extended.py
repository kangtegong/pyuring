"""
Probe-gated smoke tests for prep wrappers that need specific kernel features
or are exercised best as EINVAL / best-effort paths.
"""

from __future__ import annotations

import os
import socket
import struct
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    FutexWaitv,
    IORING_FILE_INDEX_ALLOC,
    IORING_OP_EPOLL_WAIT,
    IORING_OP_FILES_UPDATE,
    IORING_OP_FUTEX_WAIT,
    IORING_OP_FUTEX_WAITV,
    IORING_OP_FUTEX_WAKE,
    IORING_OP_NOP128,
    IORING_OP_POLL_ADD,
    IORING_OP_RECV,
    IORING_OP_RECV_ZC,
    IORING_OP_RECVMSG,
    IORING_OP_SEND_ZC,
    IORING_OP_TIMEOUT,
    IORING_OP_URING_CMD,
    IORING_OP_WAITID,
    SOCKET_URING_OP_SIOCINQ,
    SOCKET_URING_OP_SETSOCKOPT,
    UringCtx,
)


class TestPrepSmokeExtended(unittest.TestCase):
    def test_nop128_probe(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_NOP128):
                self.skipTest("nop128")
            try:
                ring.nop128()
            except Exception:
                pass

    def test_poll_update_bad_target(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_POLL_ADD):
                self.skipTest("poll")
            try:
                ring.poll_update(0xBEEF1234, 0xCAFE5678, 0, 0)
            except Exception:
                pass

    def test_timeout_update_bad_target(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_TIMEOUT):
                self.skipTest("timeout")
            try:
                ring.timeout_update(0xDEADBEEF, sec=0, nsec=1, flags=0)
            except Exception:
                pass

    def test_uring_cmd_socket_inq(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_URING_CMD):
                self.skipTest("uring_cmd")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                try:
                    ring.uring_cmd(SOCKET_URING_OP_SIOCINQ, s.fileno())
                except Exception:
                    pass
            finally:
                s.close()

    def test_uring_cmd128_smoke(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_URING_CMD):
                self.skipTest("uring_cmd")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                try:
                    ring.uring_cmd128(SOCKET_URING_OP_SIOCINQ, s.fileno())
                except Exception:
                    pass
            finally:
                s.close()

    def test_cmd_sock_setsockopt_smoke(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_URING_CMD):
                self.skipTest("uring_cmd")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                try:
                    ring.cmd_sock(
                        SOCKET_URING_OP_SETSOCKOPT,
                        s.fileno(),
                        socket.SOL_SOCKET,
                        socket.SO_REUSEADDR,
                        struct.pack("i", 1),
                        4,
                    )
                except Exception:
                    pass
            finally:
                s.close()

    def test_cmd_getsockname_tcp(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_URING_CMD):
                self.skipTest("uring_cmd")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", 0))
                buf = bytearray(256)
                try:
                    ring.cmd_getsockname(s.fileno(), buf, peer=0)
                except Exception:
                    pass
            finally:
                s.close()

    def test_files_update_requires_registration(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_FILES_UPDATE):
                self.skipTest("files_update")
            r, w = os.pipe()
            try:
                try:
                    ring.files_update([r], offset=0)
                except Exception:
                    pass
            finally:
                os.close(r)
                os.close(w)

    def test_futex_wake_invalid(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_FUTEX_WAKE):
                self.skipTest("futex_wake")
            w = bytearray(4)
            try:
                ring.futex_wake(memoryview(w), 0, 0xFFFFFFFFFFFFFFFF, 0, 0)
            except Exception:
                pass

    def test_futex_wait_invalid(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_FUTEX_WAIT):
                self.skipTest("futex_wait")
            w = bytearray(4)
            try:
                ring.futex_wait(memoryview(w), 0, 0xFFFFFFFFFFFFFFFF, 0, 0)
            except Exception:
                pass

    def test_futex_waitv_invalid(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_FUTEX_WAITV):
                self.skipTest("futex_waitv")
            e = FutexWaitv()
            e.val = 0
            e.uaddr = 0
            e.flags = 0
            e._reserved = 0
            try:
                ring.futex_waitv([e], flags=0)
            except Exception:
                pass

    def test_waitid_invalid(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_WAITID):
                self.skipTest("waitid")
            try:
                ring.waitid(0, 0, 0, 0, None)
            except Exception:
                pass

    def test_epoll_wait_invalid_epfd(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_EPOLL_WAIT):
                self.skipTest("epoll_wait")
            try:
                ring.epoll_wait(-1, 4, flags=0)
            except Exception:
                pass

    def test_recv_multishot_bad_fd(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_RECV):
                self.skipTest("recv")
            buf = bytearray(64)
            try:
                ring.recv_multishot(-1, buf, msg_flags=0)
            except Exception:
                pass

    def test_send_zc_bad_fd(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_SEND_ZC):
                self.skipTest("send_zc")
            try:
                ring.send_zc(-1, b"x", msg_flags=0, zc_flags=0)
            except Exception:
                pass

    def test_recv_zc_bad_fd(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_RECV_ZC):
                self.skipTest("recv_zc")
            buf = bytearray(64)
            try:
                ring.recv_zc(-1, buf, msg_flags=0, ioprio_zc=0)
            except Exception:
                pass

    def test_recvmsg_multishot_bad_fd(self):
        with UringCtx(entries=16) as ring:
            if not ring.probe_opcode_supported(IORING_OP_RECVMSG):
                self.skipTest("recvmsg multishot path")
            buf = bytearray(64)
            try:
                ring.recvmsg_multishot_iov(-1, [buf], flags=0)
            except Exception:
                pass

    def test_msg_ring_cqe_flags_bad_target_fd(self):
        with UringCtx(entries=16) as ring:
            try:
                ring.msg_ring_cqe_flags(-1, 1, 0, 0, 0)
            except Exception:
                pass

    def test_fixed_fd_install_bad_fd(self):
        with UringCtx(entries=16) as ring:
            try:
                ring.fixed_fd_install(-1, 0)
            except Exception:
                pass

    def test_socket_direct_alloc_smoke(self):
        with UringCtx(entries=16) as ring:
            try:
                ring.socket_direct_alloc(socket.AF_INET, socket.SOCK_DGRAM, 0, 0)
            except Exception:
                pass

    def test_pipe_direct_smoke(self):
        with UringCtx(entries=16) as ring:
            try:
                a, b = ring.pipe_direct(0, IORING_FILE_INDEX_ALLOC)
                os.close(a)
                os.close(b)
            except Exception:
                pass

    def test_send_bundle_bad_fd(self):
        with UringCtx(entries=16) as ring:
            try:
                ring.send_bundle(-1, 4, msg_flags=0)
            except Exception:
                pass

    def test_sendto_bad_fd(self):
        with UringCtx(entries=16) as ring:
            try:
                ring.sendto(-1, b"x", 0, b"", 0)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
