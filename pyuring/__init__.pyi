"""Type stubs for pyuring package exports."""
from __future__ import annotations

from typing import Any, Callable, Final, Optional

from pyuring.native.errors import UringError as UringError

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
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = ...,
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
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = ...,
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

class _DirectBindings:
    UringError: type[UringError]
    UringCtx: type[Any]
    BufferPool: type[Any]
    copy_path: Callable[..., int]
    copy_path_dynamic: Callable[..., int]
    write_newfile: Callable[..., int]
    write_newfile_dynamic: Callable[..., int]
    write_manyfiles: Callable[..., int]

direct: _DirectBindings
raw: _DirectBindings

__all__: list[str]
