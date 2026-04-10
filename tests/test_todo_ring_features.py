"""Features from TODO: presets, BufferRing, pool, multishot/splice async helpers."""

from __future__ import annotations

import asyncio
import errno
import os
import socket
import tempfile
import threading
import unittest

import tests._linux  # noqa: F401

import pyuring.ring_presets as ring_presets
from pyuring import (
    BufferRing,
    UringAsync,
    UringCtx,
    UringError,
    UringPool,
    iter_multishot_accept,
    sendfile_splice,
)
from pyuring.native.constants import IORING_OP_ACCEPT, IORING_OP_PROVIDE_BUFFERS, IORING_SETUP_COOP_TASKRUN


class TestRingPresets(unittest.TestCase):
    def test_defer_taskrun_ring_nop(self):
        try:
            ring = UringCtx.with_defer_taskrun(entries=32)
        except OSError as e:
            if e.errno in (errno.EOPNOTSUPP, errno.EINVAL, errno.ENODEV):
                self.skipTest(f"SINGLE_ISSUER|DEFER_TASKRUN not supported: {e}")
            raise
        try:
            ring.nop()
            self.assertGreater(ring.ring_fd, 0)
        finally:
            ring.close()

    def test_sqpoll_ring_or_skip(self):
        try:
            ring = UringCtx.with_sqpoll(entries=16, sq_thread_idle=100)
        except Exception as e:
            if isinstance(e, OSError) and e.errno in (
                errno.EPERM,
                errno.EACCES,
                errno.EINVAL,
                errno.ENODEV,
                errno.ENOTSUP,
            ):
                self.skipTest(f"SQPOLL not available: {e}")
            raise
        try:
            ring.nop()
        finally:
            ring.close()

    def test_ring_presets_module(self):
        self.assertEqual(
            ring_presets.defer_taskrun_setup_flags() & ring_presets.sqpoll_setup_flags(),
            0,
        )
        kw = ring_presets.defer_taskrun_kwargs(extra_setup_flags=IORING_SETUP_COOP_TASKRUN)
        self.assertIn("setup_flags", kw)


class TestBufferRing(unittest.TestCase):
    def test_provide_and_remove(self):
        with UringCtx(entries=32) as ring:
            if not ring.probe_opcode_supported(IORING_OP_PROVIDE_BUFFERS):
                self.skipTest("PROVIDE_BUFFERS")
            br = BufferRing(ring, buf_len=64, nr_buffers=4, bgid=11)
            self.assertEqual(br.bgid, 11)
            self.assertEqual(len(br.storage), 64 * 4)
            br.remove()


class TestUringPool(unittest.TestCase):
    def test_distinct_rings(self):
        with UringPool(3, entries=16) as pool:
            self.assertEqual(len(pool), 3)
            a = pool[0]
            b = pool[1]
            self.assertIsNot(a, b)
            a.nop()
            b.nop()


class TestAsyncHelpers(unittest.TestCase):
    def test_sendfile_splice_to_pipe(self):
        """Splice regular file → pipe (portable; file→socket splice may return EINVAL on some kernels)."""

        async def run():
            with tempfile.NamedTemporaryFile("w+b", delete=False) as f:
                path = f.name
                f.write(b"hello-splice")
                f.flush()
            try:
                fd = os.open(path, os.O_RDONLY)
                pr, pw = os.pipe()
                try:
                    with UringCtx(entries=16) as ring:
                        ua = UringAsync(ring)
                        n = await sendfile_splice(ua, fd, pw, count=64, chunk=8, user_data=5001)
                        self.assertEqual(n, 12)
                        os.close(pw)
                        data = os.read(pr, 64)
                        self.assertEqual(data, b"hello-splice")
                        ua.close()
                finally:
                    for xfd in (pr, pw, fd):
                        try:
                            os.close(xfd)
                        except OSError:
                            pass
            finally:
                os.unlink(path)

        asyncio.run(run())

    def test_iter_multishot_accept_one_client(self):
        _probe = UringCtx(entries=8)
        try:
            if not _probe.probe_opcode_supported(IORING_OP_ACCEPT):
                self.skipTest("ACCEPT")
        finally:
            _probe.close()

        async def run():
            ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ls.bind(("127.0.0.1", 0))
            ls.listen(1)
            host, port = ls.getsockname()
            if host in ("0.0.0.0", ""):
                host = "127.0.0.1"
            sync = threading.Barrier(2)

            def client():
                sync.wait()
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    c.connect((host, port))
                    c.sendall(b"hi")
                finally:
                    c.close()

            th = threading.Thread(target=client)
            th.start()
            try:
                sync.wait()
                with UringCtx(entries=32) as ring:
                    ua = UringAsync(ring)
                    cfd = None
                    try:
                        async for fd in iter_multishot_accept(ua, ls.fileno(), user_data=8801):
                            cfd = fd
                            break
                    except UringError as e:
                        if e.errno == errno.EINVAL:
                            self.skipTest("multishot accept not supported on this kernel")
                        raise
                    self.assertIsNotNone(cfd)
                    chunk = os.read(cfd, 16)
                    self.assertEqual(chunk, b"hi")
                    os.close(cfd)
                    ua.close()
            finally:
                th.join(timeout=5.0)
                ls.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
