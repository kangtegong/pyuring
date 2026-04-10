"""
Preset flag combinations for :class:`~pyuring.native.uring_ctx.UringCtx`.

Prefer :meth:`~pyuring.native.uring_ctx.UringCtx.with_sqpoll` and
:meth:`~pyuring.native.uring_ctx.UringCtx.with_defer_taskrun` when constructing rings.
This module exposes the same bits as plain ints for custom merges.
"""

from __future__ import annotations

from typing import Any, Dict

from pyuring.native.constants import (
    IORING_SETUP_DEFER_TASKRUN,
    IORING_SETUP_SINGLE_ISSUER,
    IORING_SETUP_SQPOLL,
)


def sqpoll_setup_flags() -> int:
    """``IORING_SETUP_SQPOLL`` — combine with other flags via ``|`` if needed."""
    return IORING_SETUP_SQPOLL


def defer_taskrun_setup_flags() -> int:
    """``SINGLE_ISSUER | DEFER_TASKRUN`` (kernel 6.1+ typical asyncio / single-submitter tuning)."""
    return IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_DEFER_TASKRUN


def sqpoll_kwargs(
    *,
    sq_thread_idle: int = 2000,
    sq_thread_cpu: int = -1,
    extra_setup_flags: int = 0,
) -> Dict[str, Any]:
    """
    Keyword arguments for ``UringCtx(..., **sqpoll_kwargs())`` besides ``entries`` / ``lib_path``.

    *extra_setup_flags* is OR'd with ``IORING_SETUP_SQPOLL``.
    """
    return {
        "setup_flags": IORING_SETUP_SQPOLL | int(extra_setup_flags),
        "sq_thread_idle": int(sq_thread_idle),
        "sq_thread_cpu": int(sq_thread_cpu),
    }


def defer_taskrun_kwargs(*, extra_setup_flags: int = 0) -> Dict[str, Any]:
    """Keyword dict for ``SINGLE_ISSUER | DEFER_TASKRUN`` plus optional extra bits."""
    return {"setup_flags": defer_taskrun_setup_flags() | int(extra_setup_flags)}


__all__ = [
    "sqpoll_setup_flags",
    "defer_taskrun_setup_flags",
    "sqpoll_kwargs",
    "defer_taskrun_kwargs",
]
