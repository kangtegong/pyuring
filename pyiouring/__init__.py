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

__version__ = "0.1.0"
__all__ = [
    "UringError",
    "UringCtx",
    "BufferPool",
    "copy_path",
    "copy_path_dynamic",
    "write_newfile",
    "write_newfile_dynamic",
    "write_manyfiles",
]

