"""IORING_OP_ASYNC_CANCEL (nonexistent user_data)."""

from __future__ import annotations

import unittest

import tests._linux  # noqa: F401

from pyuring._native import IORING_OP_ASYNC_CANCEL, UringCtx, UringError


class TestAsyncCancel(unittest.TestCase):
    def test_cancel_nonexistent_user_data(self):
        with UringCtx(entries=8) as ring:
            if not ring.probe_opcode_supported(IORING_OP_ASYNC_CANCEL):
                self.skipTest("async_cancel not supported")
            try:
                ring.async_cancel(0xDEADBEEFCAFE)
            except UringError:
                pass


if __name__ == "__main__":
    unittest.main()
