"""Errors for native io_uring bindings."""
from __future__ import annotations

import errno
import os
from typing import Optional


class UringError(OSError):
    """
    Raised when liburingwrap or io_uring operations fail.

    Subclasses :exc:`OSError`; ``errno`` and ``strerror`` match the usual
    kernel errno semantics. Use ``e.errno`` for branching (e.g. ``EAGAIN``,
    ``ENOENT``). The ``operation`` field names the Python/ctypes wrapper or
    stage (e.g. ``"uring_read_fixed_sync"``). Optional ``detail`` adds
    multi-line context (paths, hints).
    """

    operation: str
    detail: Optional[str]

    def __init__(
        self,
        errnum: int,
        operation: str,
        *,
        detail: Optional[str] = None,
    ) -> None:
        self.operation = operation
        self.detail = detail
        code = errnum if errnum > 0 else errno.EINVAL
        msg = f"{operation}: {os.strerror(code)}"
        if detail:
            msg = f"{msg}\n{detail}"
        super().__init__(code, msg)


def _raise_for_neg_errno(ret: int, operation: str) -> None:
    """If ``ret`` is negative, raise :exc:`UringError` with ``errno = -ret``."""
    if ret >= 0:
        return
    err = -int(ret)
    raise UringError(err, operation)
