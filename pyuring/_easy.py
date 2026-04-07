"""
Easy entrypoints for pyuring.

These helpers provide tuned file I/O entry points; the same operations are
available without preset tuning via `pyuring.direct` (or top-level exports).
"""

from __future__ import annotations

from typing import Callable, Optional

from pyuring._native import (
    copy_path,
    copy_path_dynamic,
    write_newfile,
    write_newfile_dynamic,
    write_manyfiles,
)


def _adaptive_buffer_size(offset: int, total: int, default: int) -> int:
    """Default adaptive buffer strategy for mode='auto'."""
    if total <= 0:
        return default
    progress = offset / total
    if progress < 0.25:
        return default
    if progress < 0.5:
        return default * 2
    if progress < 0.75:
        return default * 4
    return default * 8


def _resolve_copy_tuning(mode: str, qd: int, block_size: int) -> tuple[int, int]:
    if mode == "safe":
        return min(qd, 16), min(block_size, 1 << 20)
    if mode == "fast":
        return max(qd, 64), max(block_size, 1 << 20)
    return qd, block_size


def _resolve_write_tuning(mode: str, qd: int, block_size: int) -> tuple[int, int]:
    if mode == "safe":
        return min(qd, 128), min(block_size, 4096)
    if mode == "fast":
        return max(qd, 256), max(block_size, 1 << 16)
    return qd, block_size


def _validate_mode(mode: str) -> None:
    if mode not in ("safe", "fast", "auto"):
        raise ValueError("mode must be one of: 'safe', 'fast', 'auto'")


def copy(
    src_path: str,
    dst_path: str,
    *,
    mode: str = "auto",
    qd: int = 32,
    block_size: int = 1 << 20,
    fsync: bool = False,
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = None,
) -> int:
    """
    Copy a file with a simple mode-based API.

    mode:
      - safe: conservative queue depth / buffer size
      - fast: aggressive queue depth / buffer size
      - auto: uses dynamic buffer copy with built-in adaptive callback
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_copy_tuning(mode, qd, block_size)

    if mode == "auto":
        return copy_path_dynamic(
            src_path,
            dst_path,
            qd=tuned_qd,
            block_size=tuned_block,
            buffer_size_cb=buffer_size_cb or _adaptive_buffer_size,
            fsync=fsync,
        )

    return copy_path(src_path, dst_path, qd=tuned_qd, block_size=tuned_block)


def write(
    dst_path: str,
    *,
    total_mb: int,
    mode: str = "auto",
    qd: int = 256,
    block_size: int = 4096,
    fsync: bool = False,
    dsync: bool = False,
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = None,
) -> int:
    """
    Write a new file with a simple mode-based API.

    mode:
      - safe: conservative queue depth / buffer size
      - fast: aggressive queue depth / buffer size
      - auto: uses dynamic buffer write with built-in adaptive callback
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_write_tuning(mode, qd, block_size)

    if mode == "auto":
        return write_newfile_dynamic(
            dst_path,
            total_mb=total_mb,
            qd=tuned_qd,
            block_size=tuned_block,
            fsync=fsync,
            dsync=dsync,
            buffer_size_cb=buffer_size_cb or _adaptive_buffer_size,
        )

    return write_newfile(
        dst_path,
        total_mb=total_mb,
        qd=tuned_qd,
        block_size=tuned_block,
        fsync=fsync,
        dsync=dsync,
    )


def write_many(
    dir_path: str,
    *,
    nfiles: int,
    mb_per_file: int,
    mode: str = "auto",
    qd: int = 256,
    block_size: int = 4096,
    fsync_end: bool = False,
) -> int:
    """
    Write many files with a simple mode-based API.

    Note: maps to write_manyfiles(). mode only adjusts qd/block_size presets.
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_write_tuning(mode, qd, block_size)
    return write_manyfiles(
        dir_path,
        nfiles=nfiles,
        mb_per_file=mb_per_file,
        qd=tuned_qd,
        block_size=tuned_block,
        fsync_end=fsync_end,
    )
