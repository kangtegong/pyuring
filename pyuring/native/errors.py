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

    When available, ``filename`` (path), ``offset``, and ``length`` (buffer /
    I/O size) are set for easier logging and debugging.
    """

    operation: str
    detail: Optional[str]
    filename: Optional[str]
    offset: Optional[int]
    length: Optional[int]

    def __init__(
        self,
        errnum: int,
        operation: str,
        *,
        detail: Optional[str] = None,
        filename: Optional[str] = None,
        offset: Optional[int] = None,
        length: Optional[int] = None,
    ) -> None:
        self.operation = operation
        self.detail = detail
        self.filename = filename
        self.offset = offset
        self.length = length
        code = errnum if errnum > 0 else errno.EINVAL
        base = os.strerror(code)
        msg = f"{operation}: {base}"
        bits: list[str] = []
        if filename is not None:
            bits.append(f"path={filename!r}")
        if offset is not None:
            bits.append(f"offset={offset}")
        if length is not None:
            bits.append(f"length={length}")
        if bits:
            msg = f"{msg} ({', '.join(bits)})"
        if detail:
            msg = f"{msg}\n{detail}"
        if filename is not None:
            super().__init__(code, msg, filename)
        else:
            super().__init__(code, msg)


def _raise_for_neg_errno(
    ret: int,
    operation: str,
    *,
    filename: Optional[str] = None,
    offset: Optional[int] = None,
    length: Optional[int] = None,
) -> None:
    """If ``ret`` is negative, raise :exc:`UringError` with ``errno = -ret``."""
    if ret >= 0:
        return
    err = -int(ret)
    raise UringError(err, operation, filename=filename, offset=offset, length=length)
