"""High-level buffer group helper for :meth:`~pyuring.native.uring_ctx.UringCtx.provide_buffers`."""

from __future__ import annotations

from typing import Optional

from pyuring.native.uring_ctx import UringCtx


class BufferRing:
    """
    Owns a contiguous slab and registers it with ``IORING_OP_PROVIDE_BUFFERS`` for *bgid*.

    Use with :meth:`~pyuring.native.uring_ctx.UringCtx.recv_multishot_buffer_group_submit`
    (zero-copy recv into provided pool) or other buffer-selection opcodes targeting *bgid*.
    """

    __slots__ = ("_ring", "_storage", "buf_len", "nr_buffers", "bgid", "bid")

    def __init__(
        self,
        ring: UringCtx,
        buf_len: int,
        nr_buffers: int,
        bgid: int,
        bid: int = 0,
    ) -> None:
        if buf_len <= 0 or nr_buffers <= 0:
            raise ValueError("buf_len and nr_buffers must be positive")
        self._ring = ring
        self.buf_len = int(buf_len)
        self.nr_buffers = int(nr_buffers)
        self.bgid = int(bgid)
        self.bid = int(bid)
        need = self.buf_len * self.nr_buffers
        self._storage = bytearray(need)
        ring.provide_buffers(self._storage, self.buf_len, self.nr_buffers, self.bgid, self.bid)

    @property
    def storage(self) -> bytearray:
        """Backing memory (slice ``[i * buf_len : (i+1) * buf_len]`` is buffer *i*)."""
        return self._storage

    def remove(self, nr: Optional[int] = None) -> None:
        """``IORING_OP_REMOVE_BUFFERS`` for this group (default: all *nr_buffers*)."""
        n = self.nr_buffers if nr is None else int(nr)
        self._ring.remove_buffers(n, self.bgid)

    def close(self) -> None:
        """Alias for :meth:`remove` (idempotent enough for typical use)."""
        try:
            self.remove()
        except Exception:
            pass


__all__ = ["BufferRing"]
