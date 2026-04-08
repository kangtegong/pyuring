"""
Easy entrypoints for pyuring.

These helpers provide tuned file I/O entry points; the same operations are
available without preset tuning via `pyuring.direct` (or top-level exports).
"""

from __future__ import annotations

from typing import Callable, Literal, Optional, Tuple

from pyuring.native import (
    copy_path,
    copy_path_dynamic,
    write_newfile,
    write_newfile_dynamic,
    write_manyfiles,
)

CopySyncPolicy = Literal["default", "none", "end"]
WriteSyncPolicy = Literal["default", "none", "end", "data", "end_and_data"]
ProgressFn = Callable[[int, int], bool]
"""``(done_bytes, total_bytes) -> cancel`` — return True to stop (``errno.ECANCELED``)."""


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


def _copy_fsync(sync_policy: CopySyncPolicy, fsync: bool) -> bool:
    if sync_policy == "default":
        return fsync
    if sync_policy == "none":
        return False
    if sync_policy == "end":
        return True
    raise ValueError("sync_policy must be 'default', 'none', or 'end'")


def _write_fsync_dsync(sync_policy: WriteSyncPolicy, fsync: bool, dsync: bool) -> Tuple[bool, bool]:
    if sync_policy == "default":
        return fsync, dsync
    if sync_policy == "none":
        return False, False
    if sync_policy == "end":
        return True, False
    if sync_policy == "data":
        return False, True
    if sync_policy == "end_and_data":
        return True, True
    raise ValueError(
        "sync_policy must be 'default', 'none', 'end', 'data', or 'end_and_data'"
    )


def _fixed_block_cb(block: int):
    def _cb(_o: int, _t: int, _d: int) -> int:
        return block

    return _cb


def copy(
    src_path: str,
    dst_path: str,
    *,
    mode: str = "auto",
    qd: int = 32,
    block_size: int = 1 << 20,
    fsync: bool = False,
    sync_policy: CopySyncPolicy = "default",
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = None,
    progress_cb: Optional[ProgressFn] = None,
) -> int:
    """
    Copy a file with a simple mode-based API.

    mode:
      - safe: conservative queue depth / buffer size
      - fast: aggressive queue depth / buffer size
      - auto: uses dynamic buffer copy with built-in adaptive callback

    sync_policy (overrides ``fsync`` when not ``\"default\"``):
      - default: use ``fsync`` boolean
      - none: do not fsync the destination at the end
      - end: fsync after the copy (local disk style)

    progress_cb:
      Optional ``(done_bytes, total_bytes) -> bool``. Invoked after each completed
      destination write; return True to cancel cooperatively (``UringError`` with
      ``errno.ECANCELED``). May ``sleep`` for throttling.
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_copy_tuning(mode, qd, block_size)
    fsync_eff = _copy_fsync(sync_policy, fsync)

    if mode == "auto":
        return copy_path_dynamic(
            src_path,
            dst_path,
            qd=tuned_qd,
            block_size=tuned_block,
            buffer_size_cb=buffer_size_cb or _adaptive_buffer_size,
            fsync=fsync_eff,
            progress_cb=progress_cb,
        )

    if progress_cb is not None or sync_policy != "default" or buffer_size_cb is not None:
        return copy_path_dynamic(
            src_path,
            dst_path,
            qd=tuned_qd,
            block_size=tuned_block,
            buffer_size_cb=buffer_size_cb or _fixed_block_cb(tuned_block),
            fsync=fsync_eff,
            progress_cb=progress_cb,
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
    sync_policy: WriteSyncPolicy = "default",
    buffer_size_cb: Optional[Callable[[int, int, int], int]] = None,
    progress_cb: Optional[ProgressFn] = None,
) -> int:
    """
    Write a new file with a simple mode-based API.

    sync_policy (overrides ``fsync`` / ``dsync`` when not ``\"default\"``):
      - default: use ``fsync`` and ``dsync`` booleans
      - none: no end fsync and no per-write ``RWF_DSYNC``
      - end: fsync at end only
      - data: ``RWF_DSYNC`` on each write (data integrity before return)
      - end_and_data: fsync at end and dsync each write

    progress_cb: same contract as :func:`copy`.
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_write_tuning(mode, qd, block_size)
    fsync_eff, dsync_eff = _write_fsync_dsync(sync_policy, fsync, dsync)

    if mode == "auto":
        return write_newfile_dynamic(
            dst_path,
            total_mb=total_mb,
            qd=tuned_qd,
            block_size=tuned_block,
            fsync=fsync_eff,
            dsync=dsync_eff,
            buffer_size_cb=buffer_size_cb or _adaptive_buffer_size,
            progress_cb=progress_cb,
        )

    if progress_cb is not None or sync_policy != "default" or buffer_size_cb is not None:
        return write_newfile_dynamic(
            dst_path,
            total_mb=total_mb,
            qd=tuned_qd,
            block_size=tuned_block,
            fsync=fsync_eff,
            dsync=dsync_eff,
            buffer_size_cb=buffer_size_cb or _fixed_block_cb(tuned_block),
            progress_cb=progress_cb,
        )

    return write_newfile(
        dst_path,
        total_mb=total_mb,
        qd=tuned_qd,
        block_size=tuned_block,
        fsync=fsync_eff,
        dsync=dsync_eff,
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
    sync_policy: CopySyncPolicy = "default",
) -> int:
    """
    Write many files with a simple mode-based API.

    Note: maps to write_manyfiles(). mode only adjusts qd/block_size presets.
    sync_policy: same as :func:`copy` (fsync after each file batch is controlled
    by ``fsync_end`` when ``sync_policy`` is ``default``; ``none`` / ``end`` override).
    """
    _validate_mode(mode)
    tuned_qd, tuned_block = _resolve_write_tuning(mode, qd, block_size)
    fsync_eff = _copy_fsync(sync_policy, fsync_end)
    return write_manyfiles(
        dir_path,
        nfiles=nfiles,
        mb_per_file=mb_per_file,
        qd=tuned_qd,
        block_size=tuned_block,
        fsync_end=fsync_eff,
    )
