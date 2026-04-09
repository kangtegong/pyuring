"""
asyncio integration for :class:`~pyuring.native.uring_ctx.UringCtx` completion waits.

Waits are driven by the kernel io_uring completion-queue file descriptor
(:attr:`UringCtx.ring_fd`) via :meth:`asyncio.loop.add_reader`. For workloads that
cannot use the event loop (or for debugging), :func:`wait_completion_in_executor`
runs the blocking :meth:`~pyuring.native.uring_ctx.UringCtx.wait_completion` in a
thread pool.
"""
from __future__ import annotations

import asyncio
import collections
import errno
from concurrent.futures import Executor
from typing import Optional, Tuple

from pyuring.native.errors import UringError
from pyuring.native.uring_ctx import UringCtx


class UringAsync:
    """
    asyncio-driven completion delivery for a single :class:`UringCtx`.

    One instance is tied to **one** :class:`asyncio.AbstractEventLoop`: the first
    :meth:`wait_completion` records the running loop; later calls must run on the
    same loop or :exc:`RuntimeError` is raised.

    **Threading:** Use only from the thread that runs that loop. The underlying
    :class:`UringCtx` is not thread-safe; do not share it across threads.

    **Buffers:** For :meth:`~pyuring.native.uring_ctx.UringCtx.read_async` /
    :meth:`~pyuring.native.uring_ctx.UringCtx.write_async` (non-``*_ptr``), the
    :class:`~pyuring.native.uring_ctx.UringCtx` pins buffer objects until the
    matching CQE is returned from :meth:`wait_completion` or :meth:`~pyuring.native.uring_ctx.UringCtx.peek_completion`.
    Raw-pointer submissions still require the caller to keep memory valid.

    **Lifecycle:** Call :meth:`close` when done, or use ``async with UringAsync(ctx)``.
    Closing does not call :meth:`UringCtx.close` on the context object.
    """

    __slots__ = ("_ctx", "_waiters", "_reader_active", "_loop", "_closed")

    def __init__(self, ctx: UringCtx) -> None:
        if not getattr(ctx, "_ctx", None):
            raise UringError(errno.EINVAL, "UringAsync.__init__", detail="UringCtx is already closed")
        self._ctx = ctx
        self._waiters: collections.deque[asyncio.Future] = collections.deque()
        self._reader_active = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = False

    @property
    def ctx(self) -> UringCtx:
        return self._ctx

    @property
    def ring_fd(self) -> int:
        return self._ctx.ring_fd

    def _ensure_ctx_open(self) -> None:
        if self._closed:
            raise UringError(errno.EINVAL, "UringAsync", detail="UringAsync is closed")
        if self._ctx is None:
            raise UringError(errno.EINVAL, "UringAsync", detail="UringCtx is detached")
        if not getattr(self._ctx, "_ctx", None):
            raise UringError(errno.EINVAL, "UringAsync", detail="UringCtx is closed")

    def _bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("UringAsync is already bound to another event loop")

    def _remove_reader(self) -> None:
        if not self._reader_active or self._loop is None:
            return
        try:
            self._loop.remove_reader(self.ring_fd)
        except (ValueError, RuntimeError, OSError):
            pass
        self._reader_active = False

    def _fail_all(self, exc: BaseException) -> None:
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_exception(exc)
        self._remove_reader()

    def _deliver_peek_chain(self) -> None:
        while self._waiters:
            pair = self._ctx.peek_completion()
            if pair is None:
                return
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_result(pair)

    def _arm_reader(self) -> None:
        if self._closed or not self._waiters or self._reader_active or self._loop is None:
            return
        self._loop.add_reader(self.ring_fd, self._on_readable)
        self._reader_active = True

    def _on_readable(self) -> None:
        self._remove_reader()
        try:
            self._ensure_ctx_open()
        except UringError as e:
            self._fail_all(e)
            return
        if not self._waiters:
            return
        try:
            pair = self._ctx.wait_completion()
        except UringError as e:
            self._fail_all(e)
            return
        except Exception as e:  # pragma: no cover
            self._fail_all(e)
            return
        fut = self._waiters.popleft()
        if not fut.done():
            fut.set_result(pair)
        self._deliver_peek_chain()
        self._arm_reader()

    async def wait_completion(self) -> Tuple[int, int]:
        """
        Await the next I/O completion (``user_data``, ``result``), same semantics as
        :meth:`UringCtx.wait_completion`.

        Task cancellation removes this wait from the internal queue and drops the
        event-loop reader if no waiters remain; it does **not** cancel in-flight
        kernel operations.
        """
        self._ensure_ctx_open()
        loop = asyncio.get_running_loop()
        self._bind_loop(loop)

        fut = loop.create_future()
        self._waiters.append(fut)
        self._arm_reader()
        try:
            return await fut
        except asyncio.CancelledError:
            try:
                self._waiters.remove(fut)
            except ValueError:
                pass
            if not self._waiters:
                self._remove_reader()
            raise

    async def __aenter__(self) -> UringAsync:
        self._ensure_ctx_open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Unregister the CQ fd from the loop and cancel pending :meth:`wait_completion` futures."""
        if self._closed:
            return
        self._closed = True
        self._remove_reader()
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.cancel()


async def wait_completion_in_executor(
    ctx: UringCtx,
    executor: Optional[Executor] = None,
) -> Tuple[int, int]:
    """
    Run :meth:`UringCtx.wait_completion` in *executor* (default: loop's default executor).

    Cancellation only affects the outer task; the worker thread may remain
    blocked until a completion appears. Prefer :class:`UringAsync` for fd-integrated,
    cancellable coordination with the event loop.

    Because :meth:`~pyuring.native.uring_ctx.UringCtx.wait_completion` runs on a
    worker thread, construct *ctx* with ``single_thread_check=False`` if you use
    the default thread check (otherwise :exc:`~pyuring.native.errors.UringError`
    is raised when the worker is not the creating thread).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, ctx.wait_completion)


__all__ = ["UringAsync", "wait_completion_in_executor"]
