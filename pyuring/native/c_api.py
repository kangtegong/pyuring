"""High-level C pipeline helpers (copy/write paths) using liburingwrap."""
from __future__ import annotations

import ctypes
from ctypes import CFUNCTYPE, c_char_p, c_int, c_longlong, c_uint, c_void_p, cast

from .errors import _raise_for_neg_errno
from .library import _get_lib


def copy_path(src_path: str, dst_path: str, *, qd: int = 32, block_size: int = 1 << 20) -> int:
    """
    Copy file using io_uring pipeline in C (read->write), minimizing Python overhead.
    Returns bytes copied.
    """
    lib = _get_lib()
    lib.uring_copy_path.argtypes = [c_char_p, c_char_p, c_uint, c_uint]
    lib.uring_copy_path.restype = c_longlong

    ret = lib.uring_copy_path(src_path.encode(), dst_path.encode(), int(qd), int(block_size))
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_copy_path")
    return int(ret)


# Callback type for dynamic buffer size adjustment
BufferSizeCallback = CFUNCTYPE(c_uint, ctypes.c_uint64, ctypes.c_uint64, c_uint, c_void_p)

# Return 0 to continue, non-zero to abort with -ECANCELED from the C pipeline.
ProgressCallback = CFUNCTYPE(c_int, ctypes.c_uint64, ctypes.c_uint64, c_void_p)


def copy_path_dynamic(
    src_path: str,
    dst_path: str,
    *,
    qd: int = 32,
    block_size: int = 1 << 20,
    buffer_size_cb: callable = None,
    fsync: bool = False,
    progress_cb: callable = None,
) -> int:
    """
    Copy file using io_uring pipeline with dynamically adjustable buffer sizes.

    Args:
        src_path: Source file path
        dst_path: Destination file path
        qd: Queue depth
        block_size: Default block size (used if buffer_size_cb is None)
        buffer_size_cb: Optional callback function(current_offset, total_bytes, default_block_size) -> buffer_size
                       This function is called before each read/write to determine the buffer size.
                       Must return a positive integer <= max_buffer_size (will be clamped).
        fsync: Whether to fsync destination file at the end
        progress_cb: Optional ``(done_bytes: int, total_bytes: int) -> bool``.
            Called from the worker thread after each completed destination write;
            return True to stop early (raises ``UringError`` with ``errno.ECANCELED``).
            May be used for progress reporting or throttling (e.g. ``time.sleep``).

    Returns:
        Bytes copied.

    Example:
        def adaptive_size(offset, total, default):
            # Start with small buffers, increase as we progress
            if offset < total // 4:
                return default
            elif offset < total // 2:
                return default * 2
            else:
                return default * 4

        copy_path_dynamic("/tmp/src.dat", "/tmp/dst.dat", block_size=4096,
                         buffer_size_cb=adaptive_size, fsync=True)
    """
    lib = _get_lib()

    # Define callback wrapper
    callback_func = None

    if buffer_size_cb is not None:
        def _callback_wrapper(current_offset, total_bytes, default_block_size, user_data):
            try:
                return int(buffer_size_cb(int(current_offset), int(total_bytes), int(default_block_size)))
            except Exception:
                # On error, return default block size
                return int(default_block_size)

        callback_func = BufferSizeCallback(_callback_wrapper)

    progress_func = None
    if progress_cb is not None:
        def _progress_wrapper(done_bytes, total_bytes, user_data):
            try:
                return 1 if progress_cb(int(done_bytes), int(total_bytes)) else 0
            except Exception:
                return 1

        progress_func = ProgressCallback(_progress_wrapper)

    lib.uring_copy_path_dynamic.argtypes = [
        c_char_p, c_char_p, c_uint, c_uint,
        BufferSizeCallback, c_void_p, c_int,
        ProgressCallback, c_void_p,
    ]
    lib.uring_copy_path_dynamic.restype = c_longlong

    ret = lib.uring_copy_path_dynamic(
        src_path.encode(),
        dst_path.encode(),
        int(qd),
        int(block_size),
        callback_func if callback_func is not None else cast(0, BufferSizeCallback),
        None,  # user_data
        int(bool(fsync)),
        progress_func if progress_func is not None else cast(0, ProgressCallback),
        None,
    )
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_copy_path_dynamic")
    return int(ret)


def write_newfile(
    dst_path: str,
    *,
    total_mb: int,
    block_size: int = 4096,
    qd: int = 256,
    fsync: bool = False,
    dsync: bool = False,
) -> int:
    """
    Write a brand-new file with many small sequential writes using io_uring in C.
    Returns bytes written.
    """
    lib = _get_lib()
    lib.uring_write_newfile.argtypes = [c_char_p, c_uint, c_uint, c_uint, c_int, c_int]
    lib.uring_write_newfile.restype = c_longlong

    ret = lib.uring_write_newfile(
        dst_path.encode(), int(total_mb), int(block_size), int(qd), int(bool(fsync)), int(bool(dsync))
    )
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_write_newfile")
    return int(ret)


def write_newfile_dynamic(
    dst_path: str,
    *,
    total_mb: int,
    block_size: int = 4096,
    qd: int = 256,
    fsync: bool = False,
    dsync: bool = False,
    buffer_size_cb: callable = None,
    progress_cb: callable = None,
) -> int:
    """
    Write a brand-new file with dynamically adjustable buffer sizes using io_uring in C.

    Args:
        dst_path: Destination file path
        total_mb: Total size to write in MB
        block_size: Default block size (used if buffer_size_cb is None)
        qd: Queue depth
        fsync: Whether to fsync at the end
        dsync: Whether to sync each write
        buffer_size_cb: Optional callback function(current_offset, total_bytes, default_block_size) -> buffer_size
                       This function is called before each write to determine the buffer size.
                       Must return a positive integer <= max_buffer_size (will be clamped).
        progress_cb: Optional ``(done_bytes: int, total_bytes: int) -> bool``; same semantics as for
            :func:`copy_path_dynamic`.

    Returns:
        Bytes written.

    Example:
        def adaptive_size(offset, total, default):
            # Start with small buffers, increase as we progress
            if offset < total // 4:
                return default
            elif offset < total // 2:
                return default * 2
            else:
                return default * 4

        write_newfile_dynamic("/tmp/test.dat", total_mb=100, block_size=4096,
                             buffer_size_cb=adaptive_size)
    """
    lib = _get_lib()

    # Define callback wrapper
    callback_func = None

    if buffer_size_cb is not None:
        def _callback_wrapper(current_offset, total_bytes, default_block_size, user_data):
            try:
                return int(buffer_size_cb(int(current_offset), int(total_bytes), int(default_block_size)))
            except Exception:
                # On error, return default block size
                return int(default_block_size)

        callback_func = BufferSizeCallback(_callback_wrapper)

    progress_func = None
    if progress_cb is not None:
        def _progress_wrapper(done_bytes, total_bytes, user_data):
            try:
                return 1 if progress_cb(int(done_bytes), int(total_bytes)) else 0
            except Exception:
                return 1

        progress_func = ProgressCallback(_progress_wrapper)

    lib.uring_write_newfile_dynamic.argtypes = [
        c_char_p, c_uint, c_uint, c_uint, c_int, c_int,
        BufferSizeCallback, c_void_p,
        ProgressCallback, c_void_p,
    ]
    lib.uring_write_newfile_dynamic.restype = c_longlong

    ret = lib.uring_write_newfile_dynamic(
        dst_path.encode(),
        int(total_mb),
        int(block_size),
        int(qd),
        int(bool(fsync)),
        int(bool(dsync)),
        callback_func if callback_func is not None else cast(0, BufferSizeCallback),
        None,  # user_data
        progress_func if progress_func is not None else cast(0, ProgressCallback),
        None,
    )
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_write_newfile_dynamic")
    return int(ret)


def write_manyfiles(
    dir_path: str,
    *,
    nfiles: int,
    mb_per_file: int,
    block_size: int = 4096,
    qd: int = 256,
    fsync_end: bool = False,
) -> int:
    """
    Write many brand-new files using io_uring in C.
    Returns total bytes written across all files.
    """
    lib = _get_lib()
    lib.uring_write_manyfiles.argtypes = [c_char_p, c_uint, c_uint, c_uint, c_uint, c_int]
    lib.uring_write_manyfiles.restype = c_longlong

    ret = lib.uring_write_manyfiles(
        dir_path.encode(),
        int(nfiles),
        int(mb_per_file),
        int(block_size),
        int(qd),
        int(bool(fsync_end)),
    )
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_write_manyfiles")
    return int(ret)

