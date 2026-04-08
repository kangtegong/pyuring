"""Import this module first so non-Linux hosts skip the whole test package."""

from __future__ import annotations

import sys
import unittest

if sys.platform != "linux":
    raise unittest.SkipTest("io_uring is Linux-only")
