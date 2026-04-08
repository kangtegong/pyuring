"""UringError errno, OSError mapping, and message shape."""
from __future__ import annotations

import errno
import unittest

import tests._linux  # noqa: F401

from pyuring.native.errors import UringError, _raise_for_neg_errno


class TestUringError(unittest.TestCase):
    def test_subclass_oserror(self):
        e = UringError(errno.ENOENT, "uring_openat_sync")
        self.assertIsInstance(e, OSError)
        self.assertIsInstance(e, UringError)

    def test_errno_branch(self):
        e = UringError(errno.EAGAIN, "uring_submit")
        self.assertEqual(e.errno, errno.EAGAIN)
        self.assertEqual(e.operation, "uring_submit")
        self.assertIsNone(e.detail)

    def test_raise_for_neg_errno(self):
        with self.assertRaises(UringError) as cm:
            _raise_for_neg_errno(-errno.EINVAL, "uring_nop_sync")
        self.assertEqual(cm.exception.errno, errno.EINVAL)
        self.assertEqual(cm.exception.operation, "uring_nop_sync")

    def test_detail_appended(self):
        e = UringError(errno.ENOENT, "_find_library", detail="extra line")
        self.assertIn("extra line", str(e))
        self.assertEqual(e.detail, "extra line")

    def test_nonpositive_errno_maps_to_einval(self):
        e = UringError(0, "test_op")
        self.assertEqual(e.errno, errno.EINVAL)


if __name__ == "__main__":
    unittest.main()
