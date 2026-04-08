"""pyuring._easy (copy, write, write_many) and C helpers (copy_path, copy_path_dynamic, write_newfile)."""

from __future__ import annotations

import os
import tempfile
import unittest

import tests._linux  # noqa: F401

import pyuring
from pyuring import copy_path, copy_path_dynamic, write_newfile


class TestCopyPath(unittest.TestCase):
    def test_copy_path_roundtrip(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as src:
            src.write(b"copy-path-data")
            sp = src.name
        dp = sp + ".dst"
        try:
            n = copy_path(sp, dp, qd=8, block_size=4096)
            self.assertEqual(n, 14)
            with open(dp, "rb") as f:
                self.assertEqual(f.read(), b"copy-path-data")
        finally:
            os.unlink(sp)
            if os.path.exists(dp):
                os.unlink(dp)

    def test_copy_path_dynamic_roundtrip(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as src:
            src.write(b"dynamic-copy")
            sp = src.name
        dp = sp + ".dst2"
        try:
            n = copy_path_dynamic(
                sp,
                dp,
                qd=8,
                block_size=4096,
                fsync=True,
                buffer_size_cb=lambda _o, _t, d: d,
            )
            self.assertEqual(n, 12)
            with open(dp, "rb") as f:
                self.assertEqual(f.read(), b"dynamic-copy")
        finally:
            os.unlink(sp)
            if os.path.exists(dp):
                os.unlink(dp)


class TestWriteNewfile(unittest.TestCase):
    def test_write_newfile_small(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)
            n = write_newfile(path, total_mb=1, block_size=4096, qd=32, fsync=True, dsync=False)
            self.assertGreater(n, 0)
            self.assertEqual(os.path.getsize(path), 1024 * 1024)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestEasyAPI(unittest.TestCase):
    def test_pyuring_copy_safe(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as src:
            src.write(b"easy-copy")
            sp = src.name
        dp = sp + ".easy"
        try:
            n = pyuring.copy(sp, dp, mode="safe", fsync=False)
            self.assertEqual(n, 9)
            with open(dp, "rb") as f:
                self.assertEqual(f.read(), b"easy-copy")
        finally:
            os.unlink(sp)
            if os.path.exists(dp):
                os.unlink(dp)

    def test_pyuring_write_safe(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.bin")
            n = pyuring.write(path, total_mb=1, mode="safe", qd=32, block_size=4096)
            self.assertGreater(n, 0)
            self.assertEqual(os.path.getsize(path), 1024 * 1024)

    def test_pyuring_write_many(self):
        with tempfile.TemporaryDirectory() as td:
            n = pyuring.write_many(td, nfiles=2, mb_per_file=1, mode="safe", qd=32, block_size=4096)
            self.assertGreater(n, 0)
            names = os.listdir(td)
            self.assertEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
