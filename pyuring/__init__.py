"""
pyuring - Python bindings for io_uring with dynamic buffer size adjustment

This package provides Python bindings for io_uring operations with support for
dynamically adjusting buffer sizes at runtime.
"""

from pyuring._native import (
    BufferPool,
    EpollEvent,
    FutexWaitv,
    OpenHow,
    SIGINFO_T_SIZE,
    UAPI_CONSTANT_NAMES,
    UringCtx,
    UringError,
    copy_path,
    copy_path_dynamic,
    write_manyfiles,
    write_newfile,
    write_newfile_dynamic,
)
from pyuring._easy import (
    CopySyncPolicy,
    ProgressFn,
    WriteSyncPolicy,
    copy,
    write,
    write_many,
)
from pyuring.aio import UringAsync, iter_multishot_accept, sendfile_splice, wait_completion_in_executor
from pyuring.async_file import AsyncFile, async_open, open
from pyuring.buffer_ring import BufferRing
from pyuring.pool import UringPool
from pyuring.capabilities import (
    IO_URING_KERNEL_DOC,
    LIBURING_PROJECT,
    IoUringProbeInfo,
    get_probe_info,
    opcode_supported,
    require_opcode_supported,
)

import pyuring.ring_presets as ring_presets

import pyuring._native as _native

for _name in UAPI_CONSTANT_NAMES:
    globals()[_name] = getattr(_native, _name)
del _name, _native

__version__ = "0.3.3"


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
direct.UringAsync = UringAsync

# Backward-compatible alias
raw = direct

__all__ = (
    [
        "copy",
        "write",
        "write_many",
        "CopySyncPolicy",
        "WriteSyncPolicy",
        "ProgressFn",
        "direct",
        "raw",
        "UAPI_CONSTANT_NAMES",
        "EpollEvent",
        "FutexWaitv",
        "OpenHow",
        "SIGINFO_T_SIZE",
        "UringError",
        "UringCtx",
        "BufferPool",
        "copy_path",
        "copy_path_dynamic",
        "write_newfile",
        "write_newfile_dynamic",
        "write_manyfiles",
        "UringAsync",
        "sendfile_splice",
        "iter_multishot_accept",
        "wait_completion_in_executor",
        "BufferRing",
        "UringPool",
        "ring_presets",
        "IO_URING_KERNEL_DOC",
        "LIBURING_PROJECT",
        "IoUringProbeInfo",
        "get_probe_info",
        "opcode_supported",
        "require_opcode_supported",
        "AsyncFile",
        "open",
        "async_open",
    ]
    + list(UAPI_CONSTANT_NAMES)
)
