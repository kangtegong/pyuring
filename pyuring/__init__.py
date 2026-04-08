"""
pyuring - Python bindings for io_uring with dynamic buffer size adjustment

This package provides Python bindings for io_uring operations with support for
dynamically adjusting buffer sizes at runtime.
"""

from pyuring._native import (
    IORING_OP_NOP,
    IORING_OP_READ,
    IORING_OP_READ_FIXED,
    IORING_OP_READV,
    IORING_OP_WRITE,
    IORING_OP_WRITE_FIXED,
    IORING_OP_WRITEV,
    IORING_SETUP_COOP_TASKRUN,
    IORING_SETUP_DEFER_TASKRUN,
    IORING_SETUP_IOPOLL,
    IORING_SETUP_SINGLE_ISSUER,
    IORING_SETUP_SQPOLL,
    IORING_SETUP_SQ_AFF,
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

__version__ = "0.1.2"


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

    "IORING_OP_NOP",
    "IORING_OP_READ",
    "IORING_OP_READ_FIXED",
    "IORING_OP_READV",
    "IORING_OP_WRITE",
    "IORING_OP_WRITE_FIXED",
    "IORING_OP_WRITEV",
    "IORING_SETUP_COOP_TASKRUN",
    "IORING_SETUP_DEFER_TASKRUN",
    "IORING_SETUP_IOPOLL",
    "IORING_SETUP_SINGLE_ISSUER",
    "IORING_SETUP_SQPOLL",
    "IORING_SETUP_SQ_AFF",

    "UringError",
    "UringCtx",
    "BufferPool",
    "copy_path",
    "copy_path_dynamic",
    "write_newfile",
    "write_newfile_dynamic",
    "write_manyfiles",
]
