"""
pyiouring - Python bindings for io_uring with dynamic buffer size adjustment

This package provides Python bindings for io_uring operations with support for
dynamically adjusting buffer sizes at runtime.
"""

from pyiouring._native import (
    UringError,
    UringCtx,
    BufferPool,
    copy_path,
    copy_path_dynamic,
    write_newfile,
    write_newfile_dynamic,
    write_manyfiles,
)
from pyiouring._easy import copy, write, write_many

__version__ = "0.1.0"

class _RawApi(object):
    """Namespace exposing the unchanged native API."""
    pass

# Full native API preserved under `pyiouring.raw`.
raw = _RawApi()
raw.UringError = UringError
raw.UringCtx = UringCtx
raw.BufferPool = BufferPool
raw.copy_path = copy_path
raw.copy_path_dynamic = copy_path_dynamic
raw.write_newfile = write_newfile
raw.write_newfile_dynamic = write_newfile_dynamic
raw.write_manyfiles = write_manyfiles

__all__ = [
    # Easy user entrypoints
    "copy",
    "write",
    "write_many",
    "raw",

    # Native API (backward compatibility)
    "UringError",
    "UringCtx",
    "BufferPool",
    "copy_path",
    "copy_path_dynamic",
    "write_newfile",
    "write_newfile_dynamic",
    "write_manyfiles",
]

