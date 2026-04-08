"""
ctypes bindings to ``liburingwrap.so`` (Linux io_uring).

Submodules split responsibilities: :mod:`pyuring.native.constants` (UAPI ints),
:mod:`pyuring.native.structs` (ctypes layouts), :mod:`pyuring.native.uring_ctx``
(:class:`UringCtx`), :mod:`pyuring.native.c_api` (high-level C helpers).

The compatibility module :mod:`pyuring._native` re-exports this package.
"""

from __future__ import annotations

from .buffer_pool import BufferPool
from .c_api import (
    BufferSizeCallback,
    copy_path,
    copy_path_dynamic,
    write_manyfiles,
    write_newfile,
    write_newfile_dynamic,
)
from .constants import *  # noqa: F403
from .errors import UringError, _raise_for_neg_errno
from .structs import *  # noqa: F403
from .structs import _IOVec  # noqa: F401
from .uring_ctx import UringCtx
