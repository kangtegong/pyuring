"""send, recv, shutdown, accept; bind, listen, connect when probed."""

from __future__ import annotations

import socket
import struct
import threading
import unittest

import tests._linux  # noqa: F401

from pyuring._native import (
    IORING_OP_ACCEPT,
    IORING_OP_BIND,
    IORING_OP_CONNECT,
    IORING_OP_LISTEN,
    IORING_OP_SOCKET,
    UringCtx,
)


def _sockaddr_in(host: str, port: int) -> tuple[bytes, int]:
    # struct sockaddr_in (16 bytes): sin_family (native u16), sin_port (network order), sin_addr, zero pad.
    # Do not use "!HH" for the first two shorts: that breaks sin_family on little-endian (EAFNOSUPPORT).
    return (
        struct.pack("<H", socket.AF_INET) + struct.pack("!H", port) + socket.inet_aton(host) + b"\x00" * 8,
        16,
    )


class TestSocketsStream(unittest.TestCase):
    def test_socketpair_send_recv_shutdown(self):
        s1, s2 = socket.socketpair()
        try:
            with UringCtx(entries=16) as ring:
                n = ring.send(s1.fileno(), b"ping", 0)
                self.assertEqual(n, 4)
                buf = bytearray(16)
                m = ring.recv(s2.fileno(), buf, 0)
                self.assertEqual(m, 4)
                self.assertEqual(bytes(buf[:4]), b"ping")
                ring.shutdown(s1.fileno(), socket.SHUT_WR)
        finally:
            s1.close()
            s2.close()

    def test_tcp_accept_connect(self):
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", 0))
        ls.listen(1)
        port = ls.getsockname()[1]
        ev = threading.Event()

        def client():
            ev.wait()
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                c.connect(("127.0.0.1", port))
                c.sendall(b"ok")
            finally:
                c.close()

        t = threading.Thread(target=client)
        t.start()
        try:
            with UringCtx(entries=16) as ring:
                if not ring.probe_opcode_supported(IORING_OP_ACCEPT):
                    self.skipTest("accept opcode not supported")
                ev.set()
                cfd, _ = ring.accept(ls.fileno(), 0)
                try:
                    buf = bytearray(8)
                    m = ring.recv(cfd, buf, 0)
                    self.assertEqual(m, 2)
                    self.assertEqual(bytes(buf[:2]), b"ok")
                finally:
                    ring.close_fd(cfd)
        finally:
            ls.close()
            t.join(timeout=5)

    def test_bind_listen_connect_roundtrip(self):
        with UringCtx(entries=32) as ring:
            for op in (
                IORING_OP_SOCKET,
                IORING_OP_BIND,
                IORING_OP_LISTEN,
                IORING_OP_CONNECT,
                IORING_OP_ACCEPT,
            ):
                if not ring.probe_opcode_supported(op):
                    self.skipTest(f"opcode {op} not supported")
            tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tmp.bind(("127.0.0.1", 0))
            port = tmp.getsockname()[1]
            tmp.close()
            addr, alen = _sockaddr_in("127.0.0.1", port)
            srv = ring.socket(socket.AF_INET, socket.SOCK_STREAM, 0, 0)
            client_result: list[tuple[int, bytes]] = []

            def client_connect():
                with UringCtx(entries=32) as cr:
                    c = cr.socket(socket.AF_INET, socket.SOCK_STREAM, 0, 0)
                    try:
                        cr.connect(c, addr, alen)
                        buf = bytearray(8)
                        n = cr.recv(c, buf, 0)
                        client_result.append((n, bytes(buf[:n])))
                    finally:
                        cr.close_fd(c)

            try:
                ring.bind(srv, addr, alen)
                ring.listen(srv, 4)
                t = threading.Thread(target=client_connect)
                t.start()
                try:
                    cfd, _ = ring.accept(srv, 0)
                    try:
                        ring.send(cfd, b"yo", 0)
                    finally:
                        ring.close_fd(cfd)
                finally:
                    t.join(timeout=10)
                    self.assertFalse(t.is_alive())
                    self.assertEqual(client_result, [(2, b"yo")])
            finally:
                ring.close_fd(srv)


if __name__ == "__main__":
    unittest.main()
