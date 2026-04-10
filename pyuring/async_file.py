"""
High-level asyncio file I/O with optional io_uring and threaded fallback.

Use :func:`open` (or :func:`async_open`, same object) for
``async with pyuring.open(path, "rb") as f: data = await f.read()``.
"""

from __future__ import annotations

import asyncio
import builtins
import errno
import itertools
import os
from concurrent.futures import Executor
from typing import Optional, Union

from pyuring.aio import UringAsync
from pyuring.native.errors import UringError
from pyuring.native.uring_ctx import UringCtx

# Max bytes per single read(2)/io_uring read op (matches common buffer sizing).
_READ_SLICE = 256 * 1024

_URING_AVAILABLE: Optional[bool] = None


def _probe_io_uring() -> bool:
    """
    Return whether a minimal io_uring queue can be created.

    Caches success (``True``). Caches ``False`` only for errno values that
    indicate the ring is unavailable for this process (permissions, no io_uring,
    unsupported flags on this kernel). Other errors propagate — they may be
    transient or bugs worth surfacing.
    """
    global _URING_AVAILABLE
    if _URING_AVAILABLE is not None:
        return _URING_AVAILABLE
    try:
        r = UringCtx(entries=8)
        r.close()
    except UringError as e:
        if e.errno in (
            errno.EPERM,
            errno.EACCES,
            errno.EINVAL,
            errno.EOPNOTSUPP,
            errno.ENOSYS,
            errno.ENODEV,
        ):
            _URING_AVAILABLE = False
            return False
        raise
    _URING_AVAILABLE = True
    return True


_VALID_BINARY_MODES = frozenset(
    {
        "rb",
        "wb",
        "ab",
        "r+b",
        "rb+",
        "w+b",
        "wb+",
        "a+b",
        "ab+",
    }
)


def _normalize_mode(mode: str) -> str:
    """Validate *mode* (strip; same spellings as :func:`open` for binary modes)."""
    m = mode.strip()
    if m not in _VALID_BINARY_MODES:
        if not m:
            raise ValueError("empty mode")
        if "b" not in m:
            raise ValueError("pyuring.async_file only supports binary modes (e.g. 'rb', 'wb')")
        if "t" in m:
            raise ValueError("text mode is not supported; use a binary mode such as 'rb'")
        raise ValueError(f"invalid mode {mode!r}")
    return m


def _mode_to_flags(mode: str) -> int:
    """Map normalized binary mode to ``os.open`` flags."""
    cm = mode.replace("b", "")
    if cm == "r":
        return os.O_RDONLY
    if cm == "w":
        return os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if cm == "a":
        return os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if cm == "r+":
        return os.O_RDWR
    if cm == "w+":
        return os.O_RDWR | os.O_CREAT | os.O_TRUNC
    if cm == "a+":
        return os.O_RDWR | os.O_APPEND | os.O_CREAT
    raise ValueError(f"unsupported mode {mode!r}")


class AsyncFile:
    """
    Async file object: ``async with`` context manager; ``await read()`` /
    ``await write()``.

    **Concurrency:** A single :class:`AsyncFile` must not be used concurrently
    from multiple tasks — operations are serialized with an internal lock (and
    ``user_data`` tags are single-flight for the io_uring path).

    Uses io_uring + :class:`UringAsync` when queue creation succeeds; otherwise
    ``builtins.open`` + :meth:`asyncio.loop.run_in_executor`.
    """

    __slots__ = (
        "_path",
        "_mode",
        "_flags",
        "_executor",
        "_prefer_uring",
        "_use_uring",
        "_fd",
        "_fp",
        "_ring",
        "_ua",
        "_pos",
        "_ud",
        "_closed",
        "_lock",
    )

    def __init__(
        self,
        path: Union[str, bytes, os.PathLike],
        mode: str = "rb",
        *,
        prefer_uring: bool = True,
        executor: Optional[Executor] = None,
    ) -> None:
        self._path = os.fsdecode(os.fspath(path))
        self._mode = _normalize_mode(mode)
        self._flags = _mode_to_flags(self._mode)
        self._executor = executor
        self._prefer_uring = prefer_uring
        self._use_uring = False
        self._fd: Optional[int] = None
        self._fp: Optional[object] = None
        self._ring: Optional[UringCtx] = None
        self._ua: Optional[UringAsync] = None
        self._pos = 0
        self._ud = itertools.count(1)
        self._closed = True
        self._lock: Optional[asyncio.Lock] = None

    async def __aenter__(self) -> AsyncFile:
        self._lock = asyncio.Lock()
        use = self._prefer_uring and _probe_io_uring()
        loop = asyncio.get_running_loop()
        if use:
            try:
                self._fd = os.open(self._path, self._flags, 0o666)
            except OSError:
                raise
            try:
                self._ring = UringCtx(entries=64)
                self._ua = UringAsync(self._ring)
                self._use_uring = True
                if self._flags & os.O_APPEND:
                    self._pos = os.lseek(self._fd, 0, os.SEEK_END)
                else:
                    self._pos = 0
            except UringError:
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None
                self._ring = None
                self._ua = None
                self._use_uring = False
        if not self._use_uring:

            def _open_sync() -> object:
                return builtins.open(self._path, self._mode)

            self._fp = await loop.run_in_executor(self._executor, _open_sync)
            self._fd = None
            self._pos = 0
        self._closed = False
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def _ensure_open(self) -> None:
        if self._lock is None:
            raise RuntimeError("AsyncFile must be used with 'async with pyuring.open(...)' (call __aenter__ first)")
        if self._closed:
            raise ValueError("I/O operation on closed file")

    async def read(self, n: int = -1) -> bytes:
        if not isinstance(n, int):
            raise TypeError("read length must be int")
        if n < -1:
            raise ValueError("invalid read length")
        self._ensure_open()
        async with self._lock:
            if self._fp is not None:
                return await asyncio.get_running_loop().run_in_executor(self._executor, self._fp.read, n)
            assert self._fd is not None and self._ring is not None and self._ua is not None
            if n == 0:
                return b""
            if n < 0:
                return await self._read_uring_until_eof()
            return await self._read_uring_up_to(n)

    async def _read_uring_until_eof(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            piece = await self._read_uring_once(_READ_SLICE)
            if not piece:
                break
            chunks.append(piece)
            if len(piece) < _READ_SLICE:
                break
        return b"".join(chunks)

    async def _read_uring_up_to(self, n: int) -> bytes:
        """POSIX semantics: at most *n* bytes, fewer if EOF (or short read)."""
        if n <= 0:
            return b""
        out = bytearray()
        remaining = n
        while remaining > 0:
            chunk_sz = min(remaining, _READ_SLICE)
            piece = await self._read_uring_once(chunk_sz)
            if not piece:
                break
            out.extend(piece)
            remaining -= len(piece)
            if len(piece) < chunk_sz:
                break
        return bytes(out)

    async def _read_uring_once(self, n: int) -> bytes:
        assert self._fd is not None and self._ring is not None and self._ua is not None
        if n <= 0:
            return b""
        buf = bytearray(n)
        ud = next(self._ud)
        self._ring.read_async(self._fd, buf, offset=self._pos, user_data=ud)
        got_ud, res = await self._ua.wait_completion()
        if got_ud != ud:
            raise UringError(
                errno.EIO,
                "AsyncFile.read",
                detail=f"completion user_data mismatch (expected {ud}, got {got_ud})",
                filename=self._path,
                offset=self._pos,
                length=n,
            )
        if res < 0:
            raise UringError(-res, "AsyncFile.read", filename=self._path, offset=self._pos, length=n)
        nbytes = int(res)
        self._pos += nbytes
        return bytes(buf[:nbytes])

    async def write(self, data: Union[bytes, bytearray, memoryview]) -> int:
        self._ensure_open()
        mv = memoryview(data)
        if mv.nbytes == 0:
            return 0
        b = mv.tobytes()
        async with self._lock:
            if self._fp is not None:
                fp = self._fp

                def _w() -> int:
                    return fp.write(b)

                return await asyncio.get_running_loop().run_in_executor(self._executor, _w)
            assert self._fd is not None and self._ring is not None and self._ua is not None
            ud = next(self._ud)
            self._ring.write_async(self._fd, b, offset=self._pos, user_data=ud)
            got_ud, res = await self._ua.wait_completion()
            if got_ud != ud:
                raise UringError(
                    errno.EIO,
                    "AsyncFile.write",
                    detail=f"completion user_data mismatch (expected {ud}, got {got_ud})",
                    filename=self._path,
                    offset=self._pos,
                    length=len(b),
                )
            if res < 0:
                raise UringError(-res, "AsyncFile.write", filename=self._path, offset=self._pos, length=len(b))
            nw = int(res)
            self._pos += nw
            return nw

    async def aclose(self) -> None:
        if self._closed:
            return
        lock = self._lock
        if lock is not None:
            async with lock:
                await self._aclose_unlocked()
        else:
            await self._aclose_unlocked()

    async def _aclose_unlocked(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ua is not None:
            self._ua.close()
            self._ua = None
        if self._ring is not None:
            self._ring.close()
            self._ring = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        if self._fp is not None:
            fp = self._fp
            self._fp = None

            def _cl() -> None:
                fp.close()

            await asyncio.get_running_loop().run_in_executor(self._executor, _cl)


def open(  # noqa: A001 — intentional parallel to builtin for `async with pyuring.open(...)`
    path: Union[str, bytes, os.PathLike],
    mode: str = "rb",
    *,
    prefer_uring: bool = True,
    executor: Optional[Executor] = None,
) -> AsyncFile:
    """Return an :class:`AsyncFile` for use with ``async with`` (enter opens the file)."""
    return AsyncFile(path, mode, prefer_uring=prefer_uring, executor=executor)


async_open = open

__all__ = ["AsyncFile", "open", "async_open"]
