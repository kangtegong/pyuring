"""UringCtx / BufferPool lifecycle and thread checks."""
from __future__ import annotations

import threading
import unittest

import tests._linux  # noqa: F401

from pyuring import BufferPool, UringCtx
from pyuring.native.errors import UringError


class TestUringCtxLifecycle(unittest.TestCase):
    def test_closed_raises_on_nop(self):
        ctx = UringCtx(entries=8)
        ctx.close()
        with self.assertRaises(UringError) as cm:
            ctx.nop()
        self.assertIn("closed", (cm.exception.detail or "").lower())

    def test_wrong_thread_raises(self):
        ctx = UringCtx(entries=8)
        err: list[BaseException] = []

        def run():
            try:
                ctx.nop()
            except BaseException as e:
                err.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join()
        self.assertEqual(len(err), 1)
        self.assertIsInstance(err[0], UringError)
        self.assertIn("thread", (err[0].detail or "").lower())
        ctx.close()

    def test_single_thread_check_disabled_skips_owner_id(self):
        ctx = UringCtx(entries=8, single_thread_check=False)
        self.assertIsNone(ctx._owner_thread_id)
        ctx.close()


class TestBufferPoolLifecycle(unittest.TestCase):
    def test_closed_raises_on_get(self):
        pool = BufferPool.create(initial_count=2, initial_size=64)
        pool.close()
        with self.assertRaises(UringError) as cm:
            pool.get(0)
        self.assertIn("closed", (cm.exception.detail or "").lower())


if __name__ == "__main__":
    unittest.main()
