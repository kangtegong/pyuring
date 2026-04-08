"""Top-level pyuring exports and UAPI_CONSTANT_NAMES."""

from __future__ import annotations

import unittest

import tests._linux  # noqa: F401

import pyuring
from pyuring import IORING_OP_NOP, UAPI_CONSTANT_NAMES, direct


class TestPackageExports(unittest.TestCase):
    def test_version(self):
        self.assertTrue(isinstance(pyuring.__version__, str))
        self.assertGreater(len(pyuring.__version__), 0)

    def test_uapi_constant_names_nonempty(self):
        self.assertGreater(len(UAPI_CONSTANT_NAMES), 10)
        self.assertIn("IORING_OP_NOP", UAPI_CONSTANT_NAMES)

    def test_constants_reexported(self):
        self.assertEqual(IORING_OP_NOP, 0)

    def test_direct_alias(self):
        self.assertIs(direct.UringCtx, pyuring.UringCtx)


if __name__ == "__main__":
    unittest.main()
