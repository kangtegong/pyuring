"""
Regression: cooperative cancel (asyncio), timeout path, empty CQ peek (partial / no CQE).

These complement test_splice_timeouts_links and test_aio: fixed scenarios for
TODO “취소·타임아웃·부분 완료(EAGAIN 계열)”.
"""

from __future__ import annotations

import asyncio
import unittest

import tests._linux  # noqa: F401

from pyuring import UringAsync, UringCtx
from pyuring._native import IORING_OP_ASYNC_CANCEL, IORING_OP_TIMEOUT, UringError


class TestRegressionPeekPartial(unittest.TestCase):
    def test_peek_completion_empty_before_any_op(self):
        """No completion queued yet → peek returns None (non-blocking)."""
        with UringCtx(entries=8) as ctx:
            self.assertIsNone(ctx.peek_completion())


class TestRegressionTimeout(unittest.TestCase):
    def test_relative_timeout_completes_without_unhandled_error(self):
        """Short relative timeout; kernel may report -ETIME which wrapper tolerates."""
        with UringCtx(entries=8) as ctx:
            if not ctx.probe_opcode_supported(IORING_OP_TIMEOUT):
                self.skipTest("timeout opcode")
            ctx.timeout(0, 1_000_000, user_data=4242)  # 1ms


class TestRegressionAsyncCancel(unittest.TestCase):
    def test_async_cancel_nonexistent_user_data_raises_uring_error(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_ASYNC_CANCEL):
                self.skipTest("async_cancel")
            with self.assertRaises(UringError) as cm:
                ring.async_cancel(0xDEADBEEFCAFE)
            self.assertNotEqual(cm.exception.errno, 0)


class TestRegressionAioCancel(unittest.TestCase):
    def test_wait_completion_task_cancelled(self):
        """asyncio.CancelledError when the waiting task is cancelled (no kernel op required)."""

        async def run():
            with UringCtx(entries=8) as ctx:
                async with UringAsync(ctx) as ua:
                    wait = asyncio.create_task(ua.wait_completion())
                    await asyncio.sleep(0)
                    wait.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await wait

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
