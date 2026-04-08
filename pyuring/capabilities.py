"""
Cached io_uring opcode probe results and helpers for capability checks.

Probe data is obtained via :class:`~pyuring.native.uring_ctx.UringCtx` and cached
for the process lifetime (see :func:`get_probe_info`).
"""
from __future__ import annotations

import errno
from dataclasses import dataclass
from typing import Final, Optional

# Stable documentation links (kernel io_uring guide, liburing project).
IO_URING_KERNEL_DOC: Final[str] = "https://www.kernel.org/doc/html/latest/io_uring/index.html"
LIBURING_PROJECT: Final[str] = "https://github.com/axboe/liburing"

_cached_probe: Optional["IoUringProbeInfo"] = None


@dataclass(frozen=True)
class IoUringProbeInfo:
    """Snapshot of ``IORING_REGISTER_PROBE`` / opcode mask for the running kernel."""

    last_op: int
    opcode_mask: bytes
    """Length ``last_op + 1``; byte *i* is ``1`` if opcode *i* is supported."""


def get_probe_info(*, refresh: bool = False) -> IoUringProbeInfo:
    """
    Return cached opcode support (opens a short-lived :class:`UringCtx` on first call).

    Use :func:`opcode_supported` for a single opcode check, or read :attr:`IoUringProbeInfo.opcode_mask`.
    """
    global _cached_probe
    if _cached_probe is not None and not refresh:
        return _cached_probe
    from pyuring.native.uring_ctx import UringCtx

    with UringCtx(entries=8) as ctx:
        lo = ctx.probe_last_op()
        mask = ctx.probe_supported_mask()
    _cached_probe = IoUringProbeInfo(last_op=lo, opcode_mask=bytes(mask))
    return _cached_probe


def opcode_supported(opcode: int, *, refresh: bool = False) -> bool:
    """Return True if the kernel probe reports *opcode* as supported."""
    info = get_probe_info(refresh=refresh)
    if opcode < 0 or opcode > info.last_op:
        return False
    return info.opcode_mask[opcode] != 0


def require_opcode_supported(opcode: int, operation: str = "require_opcode_supported") -> None:
    """
    Raise :exc:`~pyuring.native.errors.UringError` with ``errno.EOPNOTSUPP`` if *opcode*
    is not available on this kernel. *operation* is the :attr:`~pyuring.native.errors.UringError.operation` field.
    """
    from pyuring.native.errors import UringError

    if opcode_supported(opcode):
        return
    detail = (
        f"io_uring opcode {opcode} is not supported on this kernel.\n"
        f"See {IO_URING_KERNEL_DOC} and probe helpers (get_probe_info, UringCtx.probe_opcode_supported)."
    )
    raise UringError(errno.EOPNOTSUPP, operation, detail=detail)


__all__ = [
    "IO_URING_KERNEL_DOC",
    "LIBURING_PROJECT",
    "IoUringProbeInfo",
    "get_probe_info",
    "opcode_supported",
    "require_opcode_supported",
]
