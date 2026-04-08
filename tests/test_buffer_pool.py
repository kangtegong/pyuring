"""BufferPool C helper."""

from __future__ import annotations

import unittest

import tests._linux  # noqa: F401

from pyuring import BufferPool


class TestBufferPool(unittest.TestCase):
    def test_create_get_resize_close(self):
        with BufferPool.create(initial_count=4, initial_size=256) as pool:
            pool.resize(0, 128)
            pool.set_size(0, 64)
            data = pool.get(0)
            self.assertEqual(len(data), 64)
            ptr, sz = pool.get_ptr(0)
            self.assertEqual(sz, 64)
            self.assertIsNotNone(ptr)


if __name__ == "__main__":
    unittest.main()
