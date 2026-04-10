"""Multiple :class:`~pyuring.native.uring_ctx.UringCtx` instances for thread-per-core patterns."""

from __future__ import annotations

from typing import Any, List

from pyuring.native.uring_ctx import UringCtx


class UringPool:
    """
    Fixed pool of independent rings. Each ring must be used from **one** thread only
    (see ``single_thread_check`` on :class:`~pyuring.native.uring_ctx.UringCtx`).

    Typical pattern: ``pool[i % len(pool)]`` on thread *i* or one ring per asyncio loop.
    """

    __slots__ = ("_rings",)

    def __init__(self, n: int, **ctx_kwargs: Any) -> None:
        if n <= 0:
            raise ValueError("n must be positive")
        self._rings: List[UringCtx] = [UringCtx(**ctx_kwargs) for _ in range(n)]

    def __len__(self) -> int:
        return len(self._rings)

    def __getitem__(self, index: int) -> UringCtx:
        return self._rings[index % len(self._rings)]

    def rings(self) -> List[UringCtx]:
        """Copy of the underlying list (callers must respect per-ring thread rules)."""
        return list(self._rings)

    def close(self) -> None:
        for r in self._rings:
            try:
                r.close()
            except Exception:
                pass
        self._rings.clear()

    def __enter__(self) -> UringPool:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["UringPool"]
