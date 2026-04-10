"""Type stubs for pyuring package exports."""
from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Final, Literal, Optional

from pyuring.aio import UringAsync as UringAsync
from pyuring.aio import iter_multishot_accept as iter_multishot_accept
from pyuring.aio import sendfile_splice as sendfile_splice
from pyuring.aio import wait_completion_in_executor as wait_completion_in_executor
from pyuring.buffer_ring import BufferRing as BufferRing
from pyuring.native.errors import UringError as UringError
from pyuring.pool import UringPool as UringPool
import pyuring.ring_presets as ring_presets

CopySyncPolicy = Literal["default", "none", "end"]
WriteSyncPolicy = Literal["default", "none", "end", "data", "end_and_data"]
ProgressFn = Callable[[int, int], bool]

IO_URING_KERNEL_DOC: Final[str]
LIBURING_PROJECT: Final[str]

class IoUringProbeInfo:
    last_op: int
    opcode_mask: bytes

def get_probe_info(*, refresh: bool = ...) -> IoUringProbeInfo: ...
def opcode_supported(opcode: int, *, refresh: bool = ...) -> bool: ...
def require_opcode_supported(opcode: int, operation: str = ...) -> None: ...

__version__: Final[str]

SIGINFO_T_SIZE: Final[int]
UAPI_CONSTANT_NAMES: Final[list[str]]

def copy(
    src_path: str,
    dst_path: str,
    *,
    mode: str = ...,
    qd: int = ...,
    block_size: int = ...,
    fsync: bool = ...,
    sync_policy: CopySyncPolicy = ...,
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = ...,
    progress_cb: Optional[ProgressFn] = ...,
) -> int: ...

def write(
    dst_path: str,
    *,
    total_mb: int,
    mode: str = ...,
    qd: int = ...,
    block_size: int = ...,
    fsync: bool = ...,
    dsync: bool = ...,
    sync_policy: WriteSyncPolicy = ...,
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = ...,
    progress_cb: Optional[ProgressFn] = ...,
) -> int: ...

def write_many(
    dir_path: str,
    *,
    nfiles: int,
    mb_per_file: int,
    mode: str = ...,
    qd: int = ...,
    block_size: int = ...,
    fsync_end: bool = ...,
    sync_policy: CopySyncPolicy = ...,
) -> int: ...

def copy_path(src_path: str, dst_path: str, *, qd: int = ..., block_size: int = ...) -> int: ...
def copy_path_dynamic(
    src_path: str,
    dst_path: str,
    *,
    qd: int = ...,
    block_size: int = ...,
    buffer_size_cb: Optional[Callable[..., int]] = ...,
    fsync: bool = ...,
    progress_cb: Optional[ProgressFn] = ...,
) -> int: ...
def write_newfile(
    dst_path: str,
    *,
    total_mb: int,
    block_size: int = ...,
    qd: int = ...,
    fsync: bool = ...,
    dsync: bool = ...,
) -> int: ...
def write_newfile_dynamic(
    dst_path: str,
    *,
    total_mb: int,
    block_size: int = ...,
    qd: int = ...,
    fsync: bool = ...,
    dsync: bool = ...,
    buffer_size_cb: Optional[Callable[..., int]] = ...,
    progress_cb: Optional[ProgressFn] = ...,
) -> int: ...
def write_manyfiles(
    dir_path: str,
    *,
    nfiles: int,
    mb_per_file: int,
    block_size: int = ...,
    qd: int = ...,
    fsync_end: bool = ...,
) -> int: ...

async def sendfile_splice(
    ua: UringAsync,
    file_fd: int,
    sock_fd: int,
    *,
    offset: int = ...,
    count: Optional[int] = ...,
    chunk: int = ...,
    user_data: int = ...,
) -> int: ...
async def iter_multishot_accept(
    ua: UringAsync,
    listen_fd: int,
    *,
    flags: int = ...,
    user_data: int = ...,
) -> AsyncIterator[int]: ...

class _DirectBindings:
    UringError: type[UringError]
    UringCtx: type[Any]
    UringAsync: type[Any]
    BufferPool: type[Any]
    copy_path: Callable[..., int]
    copy_path_dynamic: Callable[..., int]
    write_newfile: Callable[..., int]
    write_newfile_dynamic: Callable[..., int]
    write_manyfiles: Callable[..., int]

direct: _DirectBindings
raw: _DirectBindings

__all__: list[str]
