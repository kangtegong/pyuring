"""Buffer pool helper (C-side buffer management)."""
from __future__ import annotations

import ctypes
import errno
import sys
import warnings
from ctypes import POINTER, byref, c_int, c_uint, c_void_p
from typing import Tuple

from .errors import UringError, _raise_for_neg_errno
from .library import _get_lib


class BufferPool:
    """
    Buffer pool for dynamic buffer size management (C-backed).

    **Lifetime:** Keep this object alive while any io_uring operation may still
    reference pool memory (e.g. in-flight ``read_async`` using :meth:`get_ptr`).
    After :meth:`close`, the native pool is destroyed; calling other methods
    raises :exc:`UringError`. Do not call :meth:`close` until completions have
    been drained for buffers handed to the ring.
    """

    def __init__(self, lib, pool_ptr: c_void_p):
        self._lib = lib
        self._pool = pool_ptr

    def _ensure_open(self) -> None:
        if not getattr(self, "_pool", None):
            raise UringError(
                errno.EINVAL,
                "BufferPool",
                detail="This BufferPool is closed; create a new pool or avoid using it after close().",
            )

    def _pool_live(self) -> c_void_p:
        self._ensure_open()
        return self._pool

    @classmethod
    def create(cls, initial_count: int = 8, initial_size: int = 4096):
        """Create a new buffer pool."""
        lib = _get_lib()
        lib.uring_buffer_pool_create.argtypes = [c_uint, c_uint]
        lib.uring_buffer_pool_create.restype = c_void_p

        lib.uring_buffer_pool_destroy.argtypes = [c_void_p]
        lib.uring_buffer_pool_destroy.restype = None

        lib.uring_buffer_pool_resize.argtypes = [c_void_p, c_uint, c_uint]
        lib.uring_buffer_pool_resize.restype = c_int

        lib.uring_buffer_pool_get.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        lib.uring_buffer_pool_get.restype = c_void_p

        lib.uring_buffer_pool_set_size.argtypes = [c_void_p, c_uint, c_uint]
        lib.uring_buffer_pool_set_size.restype = c_int

        pool_ptr = lib.uring_buffer_pool_create(initial_count, initial_size)
        if not pool_ptr:
            err = ctypes.get_errno() or errno.ENOMEM
            raise UringError(err, "uring_buffer_pool_create")
        return cls(lib, pool_ptr)

    def resize(self, index: int, new_size: int) -> None:
        """Resize a buffer in the pool."""
        ret = self._lib.uring_buffer_pool_resize(self._pool_live(), index, new_size)
        _raise_for_neg_errno(ret, "uring_buffer_pool_resize")

    def get(self, index: int) -> bytes:
        """Get buffer data as bytes."""
        size = c_uint()
        buf_ptr = self._lib.uring_buffer_pool_get(self._pool_live(), index, byref(size))
        if not buf_ptr:
            raise UringError(errno.EINVAL, "uring_buffer_pool_get", detail=f"invalid buffer index: {index}")
        return ctypes.string_at(buf_ptr, size.value)

    def get_ptr(self, index: int) -> Tuple[ctypes.c_void_p, int]:
        """Get buffer pointer and size (for use with async operations)."""
        size = c_uint()
        buf_ptr = self._lib.uring_buffer_pool_get(self._pool_live(), index, byref(size))
        if not buf_ptr:
            raise UringError(errno.EINVAL, "uring_buffer_pool_get", detail=f"invalid buffer index: {index}")
        return (buf_ptr, int(size.value))

    def set_size(self, index: int, size: int) -> None:
        """Set buffer size without reallocation (must be <= capacity)."""
        ret = self._lib.uring_buffer_pool_set_size(self._pool_live(), index, size)
        _raise_for_neg_errno(ret, "uring_buffer_pool_set_size")

    def close(self) -> None:
        """Destroy the buffer pool."""
        p = getattr(self, "_pool", None)
        if p:
            self._lib.uring_buffer_pool_destroy(p)
            self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self) -> None:
        if sys.is_finalizing():
            return
        if getattr(self, "_pool", None) is not None:
            warnings.warn(
                "BufferPool was garbage-collected without close(); native pool memory may leak",
                ResourceWarning,
                stacklevel=2,
                source=self,
            )

