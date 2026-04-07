"""
pyuring - Python bindings for io_uring with dynamic buffer size adjustment

This package provides Python bindings for io_uring operations with support for
dynamically adjusting buffer sizes at runtime.
"""

from pyuring._native import (
    UringError,
    UringCtx,
    BufferPool,
    copy_path,
    copy_path_dynamic,
    write_newfile,
    write_newfile_dynamic,
    write_manyfiles,
)
from pyuring._easy import copy, write, write_many

__version__ = "0.1.0"


class _DirectBindings(object):
    """Grouped access to ctypes-backed symbols (same objects as top-level exports)."""


direct = _DirectBindings()
direct.UringError = UringError
direct.UringCtx = UringCtx
direct.BufferPool = BufferPool
direct.copy_path = copy_path
direct.copy_path_dynamic = copy_path_dynamic
direct.write_newfile = write_newfile
direct.write_newfile_dynamic = write_newfile_dynamic
direct.write_manyfiles = write_manyfiles

# Backward-compatible alias
raw = direct

__all__ = [
    "copy",
    "write",
    "write_many",
    "direct",
    "raw",

    "UringError",
    "UringCtx",
    "BufferPool",
    "copy_path",
    "copy_path_dynamic",
    "write_newfile",
    "write_newfile_dynamic",
    "write_manyfiles",
]
