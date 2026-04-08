"""Errors for native io_uring bindings."""
from __future__ import annotations

import os

class UringError(RuntimeError):
    """Exception raised for io_uring related errors."""
    pass


def _raise_for_neg_errno(ret: int, what: str) -> None:
    if ret >= 0:
        return
    err = -ret
    raise UringError(f"{what} failed: {-ret} ({os.strerror(err)})")
