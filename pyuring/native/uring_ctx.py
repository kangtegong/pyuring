"""``UringCtx``: io_uring operations via liburingwrap (ctypes)."""
from __future__ import annotations

import ctypes
import errno
import gc
import mmap
import os
from typing import Any, List, Optional, Sequence, Tuple, Union
from ctypes import (
    CFUNCTYPE,
    POINTER,
    byref,
    c_char_p,
    c_int,
    c_longlong,
    c_size_t,
    c_uint,
    c_uint64,
    c_void_p,
)

from .constants import *
from .errors import UringError, _raise_for_neg_errno
from .library import _find_library
from .structs import EpollEvent, FutexWaitv, KernelTimespec, OpenHow, _IOVec


class UringCtx:
    """Context manager for io_uring operations."""

    def __init__(
        self,
        lib_path: str = None,
        entries: int = 64,
        *,
        setup_flags: int = 0,
        sq_thread_cpu: int = -1,
        sq_thread_idle: int = 0,
    ):
        if lib_path is None:
            lib_path = _find_library()
        lib_path = os.path.abspath(lib_path) if os.path.exists(lib_path) else lib_path

        self._lib = ctypes.CDLL(lib_path)
        self._buffer_keepalive: List[Any] = []

        self._lib.uring_create.argtypes = [c_uint]
        self._lib.uring_create.restype = c_void_p

        self._lib.uring_create_ex.argtypes = [c_uint, c_uint, c_int, c_uint]
        self._lib.uring_create_ex.restype = c_void_p

        self._lib.uring_destroy.argtypes = [c_void_p]
        self._lib.uring_destroy.restype = None

        self._lib.uring_ring_fd.argtypes = [c_void_p]
        self._lib.uring_ring_fd.restype = c_int

        self._lib.uring_register_files.argtypes = [c_void_p, POINTER(c_int), c_uint]
        self._lib.uring_register_files.restype = c_int
        self._lib.uring_unregister_files.argtypes = [c_void_p]
        self._lib.uring_unregister_files.restype = c_int

        self._lib.uring_register_buffers.argtypes = [c_void_p, POINTER(_IOVec), c_uint]
        self._lib.uring_register_buffers.restype = c_int
        self._lib.uring_unregister_buffers.argtypes = [c_void_p]
        self._lib.uring_unregister_buffers.restype = c_int

        self._lib.uring_read_fixed_sync.argtypes = [c_void_p, c_uint, c_void_p, c_uint, c_longlong, c_uint]
        self._lib.uring_read_fixed_sync.restype = c_int
        self._lib.uring_write_fixed_sync.argtypes = [c_void_p, c_uint, c_void_p, c_uint, c_longlong, c_uint]
        self._lib.uring_write_fixed_sync.restype = c_int

        self._lib.uring_probe_opcode_supported.argtypes = [c_void_p, c_int]
        self._lib.uring_probe_opcode_supported.restype = c_int
        self._lib.uring_probe_supported_mask.argtypes = [c_void_p, c_void_p, c_uint]
        self._lib.uring_probe_supported_mask.restype = c_int
        self._lib.uring_probe_last_op.argtypes = [c_void_p]
        self._lib.uring_probe_last_op.restype = c_int

        self._lib.uring_nop_sync.argtypes = [c_void_p]
        self._lib.uring_nop_sync.restype = c_int

        self._lib.uring_readv_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_longlong]
        self._lib.uring_readv_sync.restype = c_int
        self._lib.uring_writev_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_longlong]
        self._lib.uring_writev_sync.restype = c_int
        self._lib.uring_openat_sync.argtypes = [c_void_p, c_int, c_char_p, c_int, c_uint]
        self._lib.uring_openat_sync.restype = c_int
        self._lib.uring_close_sync.argtypes = [c_void_p, c_int]
        self._lib.uring_close_sync.restype = c_int
        self._lib.uring_fsync_sync.argtypes = [c_void_p, c_int, c_uint]
        self._lib.uring_fsync_sync.restype = c_int
        self._lib.uring_fallocate_sync.argtypes = [c_void_p, c_int, c_int, ctypes.c_uint64, ctypes.c_uint64]
        self._lib.uring_fallocate_sync.restype = c_int
        self._lib.uring_statx_sync.argtypes = [c_void_p, c_int, c_char_p, c_int, c_uint, c_void_p]
        self._lib.uring_statx_sync.restype = c_int
        self._lib.uring_statx_stx_size.argtypes = [c_void_p]
        self._lib.uring_statx_stx_size.restype = ctypes.c_uint64
        self._lib.uring_renameat_sync.argtypes = [c_void_p, c_int, c_char_p, c_int, c_char_p, c_uint]
        self._lib.uring_renameat_sync.restype = c_int
        self._lib.uring_unlinkat_sync.argtypes = [c_void_p, c_int, c_char_p, c_int]
        self._lib.uring_unlinkat_sync.restype = c_int
        self._lib.uring_mkdirat_sync.argtypes = [c_void_p, c_int, c_char_p, c_uint]
        self._lib.uring_mkdirat_sync.restype = c_int
        self._lib.uring_send_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_uint]
        self._lib.uring_send_sync.restype = c_int
        self._lib.uring_recv_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_uint]
        self._lib.uring_recv_sync.restype = c_int
        self._lib.uring_accept_sync.argtypes = [c_void_p, c_int, c_void_p, POINTER(c_uint), c_int]
        self._lib.uring_accept_sync.restype = c_int
        self._lib.uring_connect_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint]
        self._lib.uring_connect_sync.restype = c_int
        self._lib.uring_shutdown_sync.argtypes = [c_void_p, c_int, c_int]
        self._lib.uring_shutdown_sync.restype = c_int
        self._lib.uring_splice_sync.argtypes = [c_void_p, c_int, ctypes.c_int64, c_int, ctypes.c_int64, c_uint, c_uint]
        self._lib.uring_splice_sync.restype = c_int

        self._lib.uring_tee_sync.argtypes = [c_void_p, c_int, c_int, c_uint, c_uint]
        self._lib.uring_tee_sync.restype = c_int
        self._lib.uring_poll_add_sync.argtypes = [c_void_p, c_int, c_uint, c_uint64]
        self._lib.uring_poll_add_sync.restype = c_int
        self._lib.uring_poll_remove_sync.argtypes = [c_void_p, c_uint64]
        self._lib.uring_poll_remove_sync.restype = c_int
        self._lib.uring_symlinkat_sync.argtypes = [c_void_p, c_char_p, c_int, c_char_p]
        self._lib.uring_symlinkat_sync.restype = c_int
        self._lib.uring_linkat_sync.argtypes = [c_void_p, c_int, c_char_p, c_int, c_char_p, c_int]
        self._lib.uring_linkat_sync.restype = c_int
        self._lib.uring_sync_file_range_sync.argtypes = [c_void_p, c_int, c_uint, ctypes.c_uint64, c_int]
        self._lib.uring_sync_file_range_sync.restype = c_int
        self._lib.uring_fadvise_sync.argtypes = [c_void_p, c_int, ctypes.c_uint64, c_uint, c_int]
        self._lib.uring_fadvise_sync.restype = c_int
        self._lib.uring_madvise_sync.argtypes = [c_void_p, c_void_p, c_uint, c_int]
        self._lib.uring_madvise_sync.restype = c_int
        self._lib.uring_async_cancel_fd_sync.argtypes = [c_void_p, c_int, c_uint]
        self._lib.uring_async_cancel_fd_sync.restype = c_int

        self._lib.uring_sendmsg_iov_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_uint]
        self._lib.uring_sendmsg_iov_sync.restype = c_int
        self._lib.uring_recvmsg_iov_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_uint]
        self._lib.uring_recvmsg_iov_sync.restype = c_int
        self._lib.uring_socket_sync.argtypes = [c_void_p, c_int, c_int, c_int, c_uint]
        self._lib.uring_socket_sync.restype = c_int
        self._lib.uring_pipe_sync.argtypes = [c_void_p, POINTER(c_int), c_int]
        self._lib.uring_pipe_sync.restype = c_int
        self._lib.uring_bind_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint]
        self._lib.uring_bind_sync.restype = c_int
        self._lib.uring_listen_sync.argtypes = [c_void_p, c_int, c_int]
        self._lib.uring_listen_sync.restype = c_int
        self._lib.uring_openat2_sync.argtypes = [c_void_p, c_int, c_char_p, POINTER(OpenHow)]
        self._lib.uring_openat2_sync.restype = c_int
        self._lib.uring_link_timeout_sync.argtypes = [c_void_p, POINTER(KernelTimespec), c_uint]
        self._lib.uring_link_timeout_sync.restype = c_int
        self._lib.uring_getxattr_sync.argtypes = [c_void_p, c_char_p, c_void_p, c_char_p, c_uint]
        self._lib.uring_getxattr_sync.restype = c_int
        self._lib.uring_setxattr_sync.argtypes = [c_void_p, c_char_p, c_char_p, c_char_p, c_int, c_uint]
        self._lib.uring_setxattr_sync.restype = c_int
        self._lib.uring_fgetxattr_sync.argtypes = [c_void_p, c_int, c_char_p, c_void_p, c_uint]
        self._lib.uring_fgetxattr_sync.restype = c_int
        self._lib.uring_fsetxattr_sync.argtypes = [c_void_p, c_int, c_char_p, c_char_p, c_int, c_uint]
        self._lib.uring_fsetxattr_sync.restype = c_int
        self._lib.uring_epoll_ctl_sync.argtypes = [c_void_p, c_int, c_int, c_int, POINTER(EpollEvent)]
        self._lib.uring_epoll_ctl_sync.restype = c_int
        self._lib.uring_provide_buffers_sync.argtypes = [c_void_p, c_void_p, c_int, c_int, c_int, c_int]
        self._lib.uring_provide_buffers_sync.restype = c_int
        self._lib.uring_remove_buffers_sync.argtypes = [c_void_p, c_int, c_int]
        self._lib.uring_remove_buffers_sync.restype = c_int
        self._lib.uring_msg_ring_sync.argtypes = [c_void_p, c_int, c_uint, c_uint64, c_uint]
        self._lib.uring_msg_ring_sync.restype = c_int
        self._lib.uring_ftruncate_sync.argtypes = [c_void_p, c_int, ctypes.c_int64]
        self._lib.uring_ftruncate_sync.restype = c_int

        self._lib.uring_nop128_sync.argtypes = [c_void_p]
        self._lib.uring_nop128_sync.restype = c_int
        self._lib.uring_poll_update_sync.argtypes = [c_void_p, c_uint64, c_uint64, c_uint, c_uint]
        self._lib.uring_poll_update_sync.restype = c_int
        self._lib.uring_timeout_update_sync.argtypes = [c_void_p, POINTER(KernelTimespec), c_uint64, c_uint]
        self._lib.uring_timeout_update_sync.restype = c_int
        self._lib.uring_recv_multishot_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_int]
        self._lib.uring_recv_multishot_sync.restype = c_int
        self._lib.uring_send_zc_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_int, c_uint]
        self._lib.uring_send_zc_sync.restype = c_int
        self._lib.uring_send_zc_fixed_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_int, c_uint, c_uint]
        self._lib.uring_send_zc_fixed_sync.restype = c_int
        self._lib.uring_sendmsg_zc_iov_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_uint]
        self._lib.uring_sendmsg_zc_iov_sync.restype = c_int
        self._lib.uring_sendmsg_zc_fixed_iov_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_uint, c_uint]
        self._lib.uring_sendmsg_zc_fixed_iov_sync.restype = c_int
        self._lib.uring_recv_zc_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_uint, c_uint]
        self._lib.uring_recv_zc_sync.restype = c_int
        self._lib.uring_recvmsg_multishot_iov_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, c_uint]
        self._lib.uring_recvmsg_multishot_iov_sync.restype = c_int
        self._lib.uring_epoll_wait_sync.argtypes = [c_void_p, c_int, POINTER(EpollEvent), c_int, c_uint]
        self._lib.uring_epoll_wait_sync.restype = c_int
        self._lib.uring_waitid_sync.argtypes = [c_void_p, c_int, c_int, c_void_p, c_int, c_uint]
        self._lib.uring_waitid_sync.restype = c_int
        self._lib.uring_futex_wake_sync.argtypes = [c_void_p, POINTER(ctypes.c_uint32), c_uint64, c_uint64, c_uint, c_uint]
        self._lib.uring_futex_wake_sync.restype = c_int
        self._lib.uring_futex_wait_sync.argtypes = [c_void_p, POINTER(ctypes.c_uint32), c_uint64, c_uint64, c_uint, c_uint]
        self._lib.uring_futex_wait_sync.restype = c_int
        self._lib.uring_futex_waitv_sync.argtypes = [c_void_p, POINTER(FutexWaitv), c_uint, c_uint]
        self._lib.uring_futex_waitv_sync.restype = c_int
        self._lib.uring_uring_cmd_sync.argtypes = [c_void_p, c_int, c_int]
        self._lib.uring_uring_cmd_sync.restype = c_int
        self._lib.uring_uring_cmd128_sync.argtypes = [c_void_p, c_int, c_int]
        self._lib.uring_uring_cmd128_sync.restype = c_int
        self._lib.uring_cmd_sock_sync.argtypes = [c_void_p, c_int, c_int, c_int, c_int, c_void_p, c_int]
        self._lib.uring_cmd_sock_sync.restype = c_int
        self._lib.uring_cmd_getsockname_sync.argtypes = [c_void_p, c_int, c_void_p, POINTER(c_uint), c_int]
        self._lib.uring_cmd_getsockname_sync.restype = c_int
        self._lib.uring_fixed_fd_install_sync.argtypes = [c_void_p, c_int, c_uint]
        self._lib.uring_fixed_fd_install_sync.restype = c_int
        self._lib.uring_socket_direct_sync.argtypes = [c_void_p, c_int, c_int, c_int, c_uint, c_uint]
        self._lib.uring_socket_direct_sync.restype = c_int
        self._lib.uring_socket_direct_alloc_sync.argtypes = [c_void_p, c_int, c_int, c_int, c_uint]
        self._lib.uring_socket_direct_alloc_sync.restype = c_int
        self._lib.uring_pipe_direct_sync.argtypes = [c_void_p, POINTER(c_int), c_int, c_uint]
        self._lib.uring_pipe_direct_sync.restype = c_int
        self._lib.uring_msg_ring_fd_sync.argtypes = [c_void_p, c_int, c_int, c_int, c_uint64, c_uint]
        self._lib.uring_msg_ring_fd_sync.restype = c_int
        self._lib.uring_msg_ring_fd_alloc_sync.argtypes = [c_void_p, c_int, c_int, c_uint64, c_uint]
        self._lib.uring_msg_ring_fd_alloc_sync.restype = c_int
        self._lib.uring_msg_ring_cqe_flags_sync.argtypes = [c_void_p, c_int, c_uint, c_uint64, c_uint, c_uint]
        self._lib.uring_msg_ring_cqe_flags_sync.restype = c_int
        self._lib.uring_files_update_sync.argtypes = [c_void_p, POINTER(c_int), c_uint, c_int]
        self._lib.uring_files_update_sync.restype = c_int
        self._lib.uring_send_bundle_sync.argtypes = [c_void_p, c_int, c_size_t, c_int]
        self._lib.uring_send_bundle_sync.restype = c_int
        self._lib.uring_readv_fixed_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, ctypes.c_uint64, c_int, c_int]
        self._lib.uring_readv_fixed_sync.restype = c_int
        self._lib.uring_writev_fixed_sync.argtypes = [c_void_p, c_int, POINTER(_IOVec), c_uint, ctypes.c_uint64, c_int, c_int]
        self._lib.uring_writev_fixed_sync.restype = c_int
        self._lib.uring_sendto_sync.argtypes = [c_void_p, c_int, c_void_p, c_size_t, c_int, c_void_p, c_uint]
        self._lib.uring_sendto_sync.restype = c_int

        self._lib.uring_timeout_sync.argtypes = [c_void_p, POINTER(KernelTimespec), c_uint, c_uint, c_uint64]
        self._lib.uring_timeout_sync.restype = c_int
        self._lib.uring_timeout_remove_sync.argtypes = [c_void_p, c_uint64, c_uint]
        self._lib.uring_timeout_remove_sync.restype = c_int
        self._lib.uring_async_cancel_sync.argtypes = [c_void_p, c_uint64, c_uint]
        self._lib.uring_async_cancel_sync.restype = c_int
        self._lib.uring_link_read_write_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_longlong, c_int, c_longlong]
        self._lib.uring_link_read_write_sync.restype = c_int
        self._lib.uring_timeout_arm_remove_pair_sync.argtypes = [c_void_p, ctypes.c_int64, ctypes.c_int64, c_uint64]
        self._lib.uring_timeout_arm_remove_pair_sync.restype = c_int

        self._lib.uring_read_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_longlong]
        self._lib.uring_read_sync.restype = c_int

        self._lib.uring_write_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_longlong]
        self._lib.uring_write_sync.restype = c_int

        self._lib.uring_read_batch_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_uint, c_longlong]
        self._lib.uring_read_batch_sync.restype = c_int

        self._lib.uring_read_offsets_sync.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_void_p, c_uint]
        self._lib.uring_read_offsets_sync.restype = c_int

        self._lib.uring_copy_path.argtypes = [c_char_p, c_char_p, c_uint, c_uint]
        self._lib.uring_copy_path.restype = c_longlong

        # Async API bindings
        self._lib.uring_read_async.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_longlong, c_uint64]
        self._lib.uring_read_async.restype = c_longlong

        self._lib.uring_write_async.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_longlong, c_uint64]
        self._lib.uring_write_async.restype = c_longlong

        self._lib.uring_wait_completion.argtypes = [c_void_p, POINTER(c_uint64), POINTER(c_int)]
        self._lib.uring_wait_completion.restype = c_int

        self._lib.uring_peek_completion.argtypes = [c_void_p, POINTER(c_uint64), POINTER(c_int)]
        self._lib.uring_peek_completion.restype = c_int

        self._lib.uring_submit.argtypes = [c_void_p]
        self._lib.uring_submit.restype = c_int

        self._lib.uring_submit_and_wait.argtypes = [c_void_p, c_uint]
        self._lib.uring_submit_and_wait.restype = c_int

        # Buffer pool API bindings
        self._lib.uring_buffer_pool_create.argtypes = [c_uint, c_uint]
        self._lib.uring_buffer_pool_create.restype = c_void_p

        self._lib.uring_buffer_pool_destroy.argtypes = [c_void_p]
        self._lib.uring_buffer_pool_destroy.restype = None

        self._lib.uring_buffer_pool_resize.argtypes = [c_void_p, c_uint, c_uint]
        self._lib.uring_buffer_pool_resize.restype = c_int

        self._lib.uring_buffer_pool_get.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        self._lib.uring_buffer_pool_get.restype = c_void_p

        self._lib.uring_buffer_pool_set_size.argtypes = [c_void_p, c_uint, c_uint]
        self._lib.uring_buffer_pool_set_size.restype = c_int

        ctx = self._lib.uring_create_ex(
            int(entries), int(setup_flags) & 0xFFFFFFFF, int(sq_thread_cpu), int(sq_thread_idle) & 0xFFFFFFFF
        )
        if not ctx:
            err = ctypes.get_errno()
            if err == 0:
                err = errno.EOPNOTSUPP
            detail = (
                "io_uring_queue_init_params failed (NULL return). "
                "Check that liburing is usable and the kernel supports io_uring for these flags."
            )
            raise UringError(err, "uring_create_ex", detail=detail)
        self._ctx = ctx

    def register_files(self, fds: Sequence[int]) -> None:
        """Register file descriptors for use with IOSQE_FIXED_FILE (indexed reads/writes)."""
        n = len(fds)
        if n == 0:
            raise ValueError("fds must be non-empty")
        arr = (c_int * n)(*[int(f) for f in fds])
        ret = self._lib.uring_register_files(self._ctx, arr, n)
        _raise_for_neg_errno(ret, "uring_register_files")

    def unregister_files(self) -> None:
        ret = self._lib.uring_unregister_files(self._ctx)
        _raise_for_neg_errno(ret, "uring_unregister_files")

    def register_buffers(self, buffers: Sequence[Any]) -> None:
        """
        Register memory regions for IORING_OP_READ_FIXED / WRITE_FIXED.
        Each element must be a writable bytes-like object with stable address (e.g. bytearray).
        Indices 0..len-1 are buf_index values for read_fixed/write_fixed.
        """
        n = len(buffers)
        if n == 0:
            raise ValueError("buffers must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, b in enumerate(buffers):
            if isinstance(b, bytes):
                raise TypeError("buffers must be mutable (e.g. bytearray), not bytes")
            mv = memoryview(b)
            if mv.readonly:
                raise TypeError("buffer must be writable")
            if not mv.contiguous:
                raise ValueError("buffer must be contiguous")
            arr = (ctypes.c_char * mv.nbytes).from_buffer(b)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(mv.nbytes)
        ret = self._lib.uring_register_buffers(self._ctx, iov, n)
        _raise_for_neg_errno(ret, "uring_register_buffers")
        self._buffer_keepalive = keep

    def unregister_buffers(self) -> None:
        ret = self._lib.uring_unregister_buffers(self._ctx)
        _raise_for_neg_errno(ret, "uring_unregister_buffers")
        self._buffer_keepalive.clear()

    def read_fixed(self, file_index: int, buf: bytearray, offset: int, buf_index: int) -> int:
        """Read using registered file index and registered buffer index (READ_FIXED + IOSQE_FIXED_FILE)."""
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        ret = self._lib.uring_read_fixed_sync(
            self._ctx, int(file_index), ctypes.cast(arr, c_void_p), len(buf), int(offset), int(buf_index)
        )
        _raise_for_neg_errno(ret, "uring_read_fixed_sync")
        return int(ret)

    def write_fixed(self, file_index: int, data: bytearray, offset: int, buf_index: int) -> int:
        """Write using registered file index; data must be the same memory as registered buffer buf_index."""
        arr = (ctypes.c_char * len(data)).from_buffer(data)
        ret = self._lib.uring_write_fixed_sync(
            self._ctx, int(file_index), ctypes.cast(arr, c_void_p), len(data), int(offset), int(buf_index)
        )
        _raise_for_neg_errno(ret, "uring_write_fixed_sync")
        return int(ret)

    def probe_opcode_supported(self, opcode: int) -> bool:
        """Return True if the kernel reports this opcode as supported (IORING_REGISTER_PROBE)."""
        ret = self._lib.uring_probe_opcode_supported(self._ctx, int(opcode))
        if ret < 0:
            _raise_for_neg_errno(ret, "uring_probe_opcode_supported")
        return bool(ret)

    def probe_last_op(self) -> int:
        """Highest opcode probe slot (see io_uring_probe.last_op)."""
        ret = self._lib.uring_probe_last_op(self._ctx)
        _raise_for_neg_errno(ret, "uring_probe_last_op")
        return int(ret)

    def probe_supported_mask(self) -> bytes:
        """Byte string where probe_supported_mask[i] is 1 iff opcode i is supported."""
        lo = self.probe_last_op()
        n = lo + 1
        buf = (ctypes.c_ubyte * n)()
        ret = self._lib.uring_probe_supported_mask(self._ctx, ctypes.cast(buf, c_void_p), n)
        if ret < 0:
            _raise_for_neg_errno(ret, "uring_probe_supported_mask")
        return bytes(buf)

    def nop(self) -> None:
        """IORING_OP_NOP: submit a no-op and wait for its completion."""
        ret = self._lib.uring_nop_sync(self._ctx)
        _raise_for_neg_errno(ret, "uring_nop_sync")

    # --- Extended synchronous opcodes (readv, vfs, sockets, splice, timeout, link) ---

    def readv(self, fd: int, parts: Sequence[Any], offset: int = 0) -> int:
        """IORING_OP_READV: scatter read into writable buffers (e.g. list of bytearray)."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            mv = memoryview(p)
            if mv.readonly:
                raise TypeError("each part must be writable")
            arr = (ctypes.c_char * mv.nbytes).from_buffer(p)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(mv.nbytes)
        ret = self._lib.uring_readv_sync(self._ctx, int(fd), iov, n, int(offset))
        _raise_for_neg_errno(ret, "uring_readv_sync")
        return int(ret)

    def writev(self, fd: int, parts: Sequence[Any], offset: int = 0) -> int:
        """IORING_OP_WRITEV: gather write from buffer parts."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            if isinstance(p, bytes):
                ba = p
            else:
                mv = memoryview(p)
                if not mv.contiguous:
                    raise ValueError("each part must be contiguous")
                ba = p
            arr = (ctypes.c_char * len(ba)).from_buffer_copy(ba) if isinstance(ba, bytes) else (ctypes.c_char * len(ba)).from_buffer(ba)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(len(ba))
        ret = self._lib.uring_writev_sync(self._ctx, int(fd), iov, n, int(offset))
        _raise_for_neg_errno(ret, "uring_writev_sync")
        return int(ret)

    def openat(self, path: str, flags: int, mode: int = 0o644, *, dir_fd: int = AT_FDCWD) -> int:
        """IORING_OP_OPENAT: returns new file descriptor."""
        ret = self._lib.uring_openat_sync(self._ctx, int(dir_fd), path.encode(), int(flags), int(mode) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_openat_sync")
        return int(ret)

    def close_fd(self, fd: int) -> None:
        """IORING_OP_CLOSE."""
        ret = self._lib.uring_close_sync(self._ctx, int(fd))
        _raise_for_neg_errno(ret, "uring_close_sync")

    def fsync_fd(self, fd: int, *, datasync: bool = False) -> None:
        """IORING_OP_FSYNC."""
        fl = IORING_FSYNC_DATASYNC if datasync else 0
        ret = self._lib.uring_fsync_sync(self._ctx, int(fd), fl)
        _raise_for_neg_errno(ret, "uring_fsync_sync")

    def fallocate_fd(self, fd: int, mode: int, offset: int, length: int) -> None:
        """IORING_OP_FALLOCATE."""
        ret = self._lib.uring_fallocate_sync(self._ctx, int(fd), int(mode), int(offset), int(length))
        _raise_for_neg_errno(ret, "uring_fallocate_sync")

    def statx(
        self,
        path: str,
        *,
        dir_fd: int = AT_FDCWD,
        flags: int = AT_SYMLINK_NOFOLLOW,
        mask: int = STATX_BASIC_STATS,
    ) -> int:
        """IORING_OP_STATX: returns stx_size via native helper (full struct in internal buffer)."""
        buf = (ctypes.c_byte * 512)()
        ret = self._lib.uring_statx_sync(
            self._ctx, int(dir_fd), path.encode(), int(flags), int(mask) & 0xFFFFFFFF, ctypes.cast(buf, c_void_p)
        )
        _raise_for_neg_errno(ret, "uring_statx_sync")
        return int(self._lib.uring_statx_stx_size(ctypes.cast(buf, c_void_p)))

    def renameat(self, old_path: str, new_path: str, *, old_dir_fd: int = AT_FDCWD, new_dir_fd: int = AT_FDCWD, flags: int = 0) -> None:
        ret = self._lib.uring_renameat_sync(
            self._ctx, int(old_dir_fd), old_path.encode(), int(new_dir_fd), new_path.encode(), int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_renameat_sync")

    def unlinkat(self, path: str, *, dir_fd: int = AT_FDCWD, flags: int = 0) -> None:
        ret = self._lib.uring_unlinkat_sync(self._ctx, int(dir_fd), path.encode(), int(flags))
        _raise_for_neg_errno(ret, "uring_unlinkat_sync")

    def mkdirat(self, path: str, mode: int = 0o755, *, dir_fd: int = AT_FDCWD) -> None:
        ret = self._lib.uring_mkdirat_sync(self._ctx, int(dir_fd), path.encode(), int(mode) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_mkdirat_sync")

    def send(self, fd: int, data: bytes, flags: int = 0) -> int:
        """IORING_OP_SEND."""
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        ret = self._lib.uring_send_sync(
            self._ctx, int(fd), ctypes.cast(buf, c_void_p), len(data), int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_send_sync")
        return int(ret)

    def recv(self, fd: int, buf: bytearray, flags: int = 0) -> int:
        """IORING_OP_RECV."""
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        ret = self._lib.uring_recv_sync(self._ctx, int(fd), ctypes.cast(arr, c_void_p), len(buf), int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_recv_sync")
        return int(ret)

    def accept(self, fd: int, flags: int = 0) -> Tuple[int, bytes]:
        """IORING_OP_ACCEPT: returns (new_fd, sockaddr bytes)."""
        storage = (ctypes.c_byte * 128)()
        alen = c_uint(ctypes.sizeof(storage))
        ret = self._lib.uring_accept_sync(
            self._ctx, int(fd), ctypes.cast(storage, c_void_p), ctypes.byref(alen), int(flags)
        )
        _raise_for_neg_errno(ret, "uring_accept_sync")
        return int(ret), bytes(storage)[: int(alen.value)]

    def connect(self, fd: int, addr, addr_len: int) -> None:
        """IORING_OP_CONNECT: addr is sockaddr bytes (e.g. from socket.pack)."""
        buf = (ctypes.c_char * max(len(addr), addr_len))()
        ctypes.memmove(buf, addr, len(addr))
        ret = self._lib.uring_connect_sync(self._ctx, int(fd), ctypes.cast(buf, c_void_p), int(addr_len))
        _raise_for_neg_errno(ret, "uring_connect_sync")

    def shutdown(self, fd: int, how: int) -> None:
        """IORING_OP_SHUTDOWN (how: socket.SHUT_*)."""
        ret = self._lib.uring_shutdown_sync(self._ctx, int(fd), int(how))
        _raise_for_neg_errno(ret, "uring_shutdown_sync")

    def splice(
        self,
        fd_in: int,
        off_in: int,
        fd_out: int,
        off_out: int,
        nbytes: int,
        flags: int = 0,
    ) -> int:
        """IORING_OP_SPLICE."""
        ret = self._lib.uring_splice_sync(
            self._ctx,
            int(fd_in),
            int(off_in),
            int(fd_out),
            int(off_out),
            int(nbytes) & 0xFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_splice_sync")
        return int(ret)

    def tee(self, fd_in: int, fd_out: int, nbytes: int, flags: int = 0) -> int:
        """IORING_OP_TEE: copy pipe-to-pipe (see tee(2)); returns bytes duplicated or 0."""
        ret = self._lib.uring_tee_sync(
            self._ctx, int(fd_in), int(fd_out), int(nbytes) & 0xFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_tee_sync")
        return int(ret)

    def poll_add(self, fd: int, poll_mask: int, *, user_data: int = 42_000) -> int:
        """IORING_OP_POLL_ADD: wait for readiness; returns event bitmask (e.g. POLLIN from select module)."""
        ret = self._lib.uring_poll_add_sync(
            self._ctx, int(fd), int(poll_mask) & 0xFFFFFFFF, int(user_data) & 0xFFFFFFFFFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_poll_add_sync")
        return int(ret)

    def poll_remove(self, target_user_data: int) -> None:
        """IORING_OP_POLL_REMOVE: cancel poll/multishot installed with the same user_data."""
        ret = self._lib.uring_poll_remove_sync(self._ctx, int(target_user_data) & 0xFFFFFFFFFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_poll_remove_sync")

    def symlinkat(self, target: str, link_path: str, *, new_dir_fd: int = AT_FDCWD) -> None:
        """IORING_OP_SYMLINKAT."""
        ret = self._lib.uring_symlinkat_sync(self._ctx, target.encode(), int(new_dir_fd), link_path.encode())
        _raise_for_neg_errno(ret, "uring_symlinkat_sync")

    def linkat(
        self,
        old_path: str,
        new_path: str,
        *,
        old_dir_fd: int = AT_FDCWD,
        new_dir_fd: int = AT_FDCWD,
        flags: int = 0,
    ) -> None:
        """IORING_OP_LINKAT (hard link)."""
        ret = self._lib.uring_linkat_sync(
            self._ctx,
            int(old_dir_fd),
            old_path.encode(),
            int(new_dir_fd),
            new_path.encode(),
            int(flags),
        )
        _raise_for_neg_errno(ret, "uring_linkat_sync")

    def sync_file_range(self, fd: int, length: int, offset: int, flags: int) -> None:
        """IORING_OP_SYNC_FILE_RANGE (see SYNC_FILE_RANGE_* constants)."""
        ret = self._lib.uring_sync_file_range_sync(
            self._ctx,
            int(fd),
            int(length) & 0xFFFFFFFF,
            int(offset) & 0xFFFFFFFFFFFFFFFF,
            int(flags),
        )
        _raise_for_neg_errno(ret, "uring_sync_file_range_sync")

    def fadvise(self, fd: int, offset: int, length: int, advice: int) -> None:
        """IORING_OP_FADVISE (POSIX_FADV_*)."""
        ret = self._lib.uring_fadvise_sync(
            self._ctx,
            int(fd),
            int(offset) & 0xFFFFFFFFFFFFFFFF,
            int(length) & 0xFFFFFFFF,
            int(advice),
        )
        _raise_for_neg_errno(ret, "uring_fadvise_sync")

    def madvise(self, buf, advice: int) -> None:
        """IORING_OP_MADVISE on a writable mmap-like region (see madvise(2))."""
        if not isinstance(buf, mmap.mmap):
            mv = memoryview(buf)
            if mv.readonly:
                raise TypeError("madvise buffer must be writable")
            if not mv.contiguous:
                raise ValueError("buffer must be contiguous")
        n = len(buf)
        arr = (ctypes.c_char * n).from_buffer(buf)
        try:
            ret = self._lib.uring_madvise_sync(self._ctx, ctypes.cast(arr, c_void_p), n, int(advice))
            _raise_for_neg_errno(ret, "uring_madvise_sync")
        finally:
            del arr
            if isinstance(buf, mmap.mmap):
                gc.collect()

    def async_cancel_fd(self, fd: int, flags: int = 0) -> None:
        """IORING_OP_ASYNC_CANCEL with IORING_ASYNC_CANCEL_FD (cancel by fd)."""
        ret = self._lib.uring_async_cancel_fd_sync(self._ctx, int(fd), int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_async_cancel_fd_sync")

    def sendmsg_iov(self, fd: int, parts: Sequence[Any], flags: int = 0) -> int:
        """IORING_OP_SENDMSG with a scatter/gather list (single msghdr, multiple iovec)."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            if isinstance(p, bytes):
                ba = p
            else:
                mv = memoryview(p)
                if not mv.contiguous:
                    raise ValueError("each part must be contiguous")
                ba = p
            arr = (ctypes.c_char * len(ba)).from_buffer_copy(ba) if isinstance(ba, bytes) else (ctypes.c_char * len(ba)).from_buffer(ba)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(len(ba))
        ret = self._lib.uring_sendmsg_iov_sync(self._ctx, int(fd), iov, n, int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_sendmsg_iov_sync")
        return int(ret)

    def recvmsg_iov(self, fd: int, parts: Sequence[Any], flags: int = 0) -> int:
        """IORING_OP_RECVMSG into writable iovec parts (e.g. list of bytearray)."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            mv = memoryview(p)
            if mv.readonly:
                raise TypeError("each part must be writable")
            arr = (ctypes.c_char * mv.nbytes).from_buffer(p)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(mv.nbytes)
        ret = self._lib.uring_recvmsg_iov_sync(self._ctx, int(fd), iov, n, int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_recvmsg_iov_sync")
        return int(ret)

    def socket(self, domain: int, type: int, protocol: int = 0, flags: int = 0) -> int:
        """IORING_OP_SOCKET: returns new fd from cqe.res."""
        ret = self._lib.uring_socket_sync(
            self._ctx, int(domain), int(type), int(protocol), int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_socket_sync")
        return int(ret)

    def pipe(self, pipe_flags: int = 0) -> Tuple[int, int]:
        """IORING_OP_PIPE: returns (read_fd, write_fd)."""
        fds = (c_int * 2)()
        ret = self._lib.uring_pipe_sync(self._ctx, fds, int(pipe_flags))
        _raise_for_neg_errno(ret, "uring_pipe_sync")
        return int(fds[0]), int(fds[1])

    def bind(self, fd: int, addr, addr_len: int) -> None:
        """IORING_OP_BIND: addr is sockaddr bytes."""
        buf = (ctypes.c_char * max(len(addr), addr_len))()
        ctypes.memmove(buf, addr, len(addr))
        ret = self._lib.uring_bind_sync(self._ctx, int(fd), ctypes.cast(buf, c_void_p), int(addr_len))
        _raise_for_neg_errno(ret, "uring_bind_sync")

    def listen(self, fd: int, backlog: int) -> None:
        """IORING_OP_LISTEN."""
        ret = self._lib.uring_listen_sync(self._ctx, int(fd), int(backlog))
        _raise_for_neg_errno(ret, "uring_listen_sync")

    def openat2(self, path: str, how: OpenHow, *, dir_fd: int = AT_FDCWD) -> int:
        """IORING_OP_OPENAT2: returns new fd."""
        ret = self._lib.uring_openat2_sync(self._ctx, int(dir_fd), path.encode(), ctypes.byref(how))
        _raise_for_neg_errno(ret, "uring_openat2_sync")
        return int(ret)

    def link_timeout(self, sec: int = 0, nsec: int = 0, *, flags: int = 0) -> None:
        """IORING_OP_LINK_TIMEOUT (typically chained after IOSQE_IO_LINK); may fail if misused."""
        ts = KernelTimespec()
        ts.tv_sec = int(sec)
        ts.tv_nsec = int(nsec)
        ret = self._lib.uring_link_timeout_sync(self._ctx, ctypes.byref(ts), int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_link_timeout_sync")

    def getxattr(self, path: str, name: str, value: bytearray) -> int:
        """IORING_OP_GETXATTR: returns value length or error."""
        arr = (ctypes.c_char * len(value)).from_buffer(value)
        ret = self._lib.uring_getxattr_sync(
            self._ctx, name.encode(), ctypes.cast(arr, c_void_p), path.encode(), len(value)
        )
        _raise_for_neg_errno(ret, "uring_getxattr_sync")
        return int(ret)

    def setxattr(self, path: str, name: str, value: bytes, flags: int = 0) -> None:
        """IORING_OP_SETXATTR."""
        buf = (ctypes.c_char * len(value)).from_buffer_copy(value)
        ret = self._lib.uring_setxattr_sync(
            self._ctx, name.encode(), buf, path.encode(), int(flags), len(value)
        )
        _raise_for_neg_errno(ret, "uring_setxattr_sync")

    def fgetxattr(self, fd: int, name: str, value: bytearray) -> int:
        """IORING_OP_FGETXATTR."""
        arr = (ctypes.c_char * len(value)).from_buffer(value)
        ret = self._lib.uring_fgetxattr_sync(self._ctx, int(fd), name.encode(), ctypes.cast(arr, c_void_p), len(value))
        _raise_for_neg_errno(ret, "uring_fgetxattr_sync")
        return int(ret)

    def fsetxattr(self, fd: int, name: str, value: bytes, flags: int = 0) -> None:
        """IORING_OP_FSETXATTR."""
        buf = (ctypes.c_char * len(value)).from_buffer_copy(value)
        ret = self._lib.uring_fsetxattr_sync(
            self._ctx, int(fd), name.encode(), buf, int(flags), len(value)
        )
        _raise_for_neg_errno(ret, "uring_fsetxattr_sync")

    def epoll_ctl(self, epfd: int, fd: int, op: int, event: Optional[EpollEvent] = None) -> None:
        """IORING_OP_EPOLL_CTL (event=None for EPOLL_CTL_DEL)."""
        if event is not None:
            evp = ctypes.byref(event)
        else:
            evp = None
        ret = self._lib.uring_epoll_ctl_sync(self._ctx, int(epfd), int(fd), int(op), evp)
        _raise_for_neg_errno(ret, "uring_epoll_ctl_sync")

    def provide_buffers(self, buf, buf_len_each: int, nr: int, bgid: int, bid: int = 0) -> None:
        """IORING_OP_PROVIDE_BUFFERS: contiguous memory of at least buf_len_each * nr bytes."""
        mv = memoryview(buf)
        need = int(buf_len_each) * int(nr)
        if mv.nbytes < need:
            raise ValueError("buffer too small for nr buffers of buf_len_each")
        if mv.readonly:
            raise TypeError("buffer must be writable")
        arr = (ctypes.c_char * need).from_buffer(buf)
        self._buffer_keepalive.append(arr)
        ret = self._lib.uring_provide_buffers_sync(
            self._ctx, ctypes.cast(arr, c_void_p), int(buf_len_each), int(nr), int(bgid), int(bid)
        )
        _raise_for_neg_errno(ret, "uring_provide_buffers_sync")

    def remove_buffers(self, nr: int, bgid: int) -> None:
        """IORING_OP_REMOVE_BUFFERS."""
        ret = self._lib.uring_remove_buffers_sync(self._ctx, int(nr), int(bgid))
        _raise_for_neg_errno(ret, "uring_remove_buffers_sync")

    def msg_ring(self, fd: int, len_val: int, data: int, flags: int = 0) -> None:
        """IORING_OP_MSG_RING (target ring fd)."""
        ret = self._lib.uring_msg_ring_sync(
            self._ctx, int(fd), int(len_val) & 0xFFFFFFFF, int(data) & 0xFFFFFFFFFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_msg_ring_sync")

    def ftruncate(self, fd: int, length: int) -> None:
        """IORING_OP_FTRUNCATE."""
        ret = self._lib.uring_ftruncate_sync(self._ctx, int(fd), int(length))
        _raise_for_neg_errno(ret, "uring_ftruncate_sync")

    def nop128(self) -> None:
        """IORING_OP_NOP128 (requires IORING_SETUP_SQE128 / mixed SQE mode)."""
        ret = self._lib.uring_nop128_sync(self._ctx)
        _raise_for_neg_errno(ret, "uring_nop128_sync")

    def poll_update(self, old_user_data: int, new_user_data: int, poll_mask: int, flags: int = 0) -> None:
        """IORING_OP_POLL_REMOVE variant: update poll mask / user_data."""
        ret = self._lib.uring_poll_update_sync(
            self._ctx,
            int(old_user_data) & 0xFFFFFFFFFFFFFFFF,
            int(new_user_data) & 0xFFFFFFFFFFFFFFFF,
            int(poll_mask) & 0xFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_poll_update_sync")

    def timeout_update(self, target_user_data: int, sec: int = 0, nsec: int = 0, flags: int = 0) -> None:
        """IORING_OP_TIMEOUT_REMOVE with IORING_TIMEOUT_UPDATE."""
        ts = KernelTimespec()
        ts.tv_sec = int(sec)
        ts.tv_nsec = int(nsec)
        ret = self._lib.uring_timeout_update_sync(
            self._ctx,
            ctypes.byref(ts),
            int(target_user_data) & 0xFFFFFFFFFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_timeout_update_sync")

    def recv_multishot(self, fd: int, buf: bytearray, msg_flags: int = 0) -> int:
        """IORING_OP_RECV with IORING_RECV_MULTISHOT."""
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        ret = self._lib.uring_recv_multishot_sync(
            self._ctx, int(fd), ctypes.cast(arr, c_void_p), len(buf), int(msg_flags)
        )
        _raise_for_neg_errno(ret, "uring_recv_multishot_sync")
        return int(ret)

    def send_zc(self, fd: int, data: bytes, msg_flags: int = 0, zc_flags: int = 0) -> int:
        """IORING_OP_SEND_ZC."""
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        ret = self._lib.uring_send_zc_sync(
            self._ctx, int(fd), ctypes.cast(buf, c_void_p), len(data), int(msg_flags), int(zc_flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_send_zc_sync")
        return int(ret)

    def send_zc_fixed(self, fd: int, data, msg_flags: int = 0, zc_flags: int = 0, buf_index: int = 0) -> int:
        """IORING_OP_SEND_ZC with registered buffer index."""
        mv = memoryview(data)
        arr = (ctypes.c_char * mv.nbytes).from_buffer(data)
        ret = self._lib.uring_send_zc_fixed_sync(
            self._ctx,
            int(fd),
            ctypes.cast(arr, c_void_p),
            mv.nbytes,
            int(msg_flags),
            int(zc_flags) & 0xFFFFFFFF,
            int(buf_index) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_send_zc_fixed_sync")
        return int(ret)

    def sendmsg_zc_iov(self, fd: int, parts: Sequence[Any], flags: int = 0) -> int:
        """IORING_OP_SENDMSG_ZC."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            if isinstance(p, bytes):
                ba = p
            else:
                mv = memoryview(p)
                if not mv.contiguous:
                    raise ValueError("each part must be contiguous")
                ba = p
            arr = (ctypes.c_char * len(ba)).from_buffer_copy(ba) if isinstance(ba, bytes) else (ctypes.c_char * len(ba)).from_buffer(ba)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(len(ba))
        ret = self._lib.uring_sendmsg_zc_iov_sync(self._ctx, int(fd), iov, n, int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_sendmsg_zc_iov_sync")
        return int(ret)

    def sendmsg_zc_fixed_iov(self, fd: int, parts: Sequence[Any], flags: int = 0, buf_index: int = 0) -> int:
        """IORING_OP_SENDMSG_ZC with fixed buffer."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            if isinstance(p, bytes):
                ba = p
            else:
                mv = memoryview(p)
                if not mv.contiguous:
                    raise ValueError("each part must be contiguous")
                ba = p
            arr = (ctypes.c_char * len(ba)).from_buffer_copy(ba) if isinstance(ba, bytes) else (ctypes.c_char * len(ba)).from_buffer(ba)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(len(ba))
        ret = self._lib.uring_sendmsg_zc_fixed_iov_sync(
            self._ctx, int(fd), iov, n, int(flags) & 0xFFFFFFFF, int(buf_index) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_sendmsg_zc_fixed_iov_sync")
        return int(ret)

    def recv_zc(self, fd: int, buf: bytearray, msg_flags: int = 0, ioprio_zc: int = 0) -> int:
        """IORING_OP_RECV_ZC (raw layout; often used with buffer groups / zcrx)."""
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        ret = self._lib.uring_recv_zc_sync(
            self._ctx,
            int(fd),
            ctypes.cast(arr, c_void_p),
            len(buf),
            int(msg_flags) & 0xFFFFFFFF,
            int(ioprio_zc) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_recv_zc_sync")
        return int(ret)

    def recvmsg_multishot_iov(self, fd: int, parts: Sequence[Any], flags: int = 0) -> int:
        """IORING_OP_RECVMSG with IORING_RECV_MULTISHOT."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            mv = memoryview(p)
            if mv.readonly:
                raise TypeError("each part must be writable")
            arr = (ctypes.c_char * mv.nbytes).from_buffer(p)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(mv.nbytes)
        ret = self._lib.uring_recvmsg_multishot_iov_sync(self._ctx, int(fd), iov, n, int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_recvmsg_multishot_iov_sync")
        return int(ret)

    def epoll_wait(self, epfd: int, maxevents: int, flags: int = 0) -> Tuple[int, List[EpollEvent]]:
        """IORING_OP_EPOLL_WAIT: returns (result, list of EpollEvent up to maxevents)."""
        n = int(maxevents)
        if n <= 0:
            raise ValueError("maxevents must be positive")
        arr = (EpollEvent * n)()
        ret = self._lib.uring_epoll_wait_sync(self._ctx, int(epfd), arr, n, int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_epoll_wait_sync")
        k = min(int(ret), n) if ret >= 0 else 0
        return int(ret), [arr[i] for i in range(k)]

    def waitid(self, idtype: int, pid: int, options: int, flags: int, info: Optional[bytearray] = None) -> int:
        """IORING_OP_WAITID (info: optional writable buffer >= SIGINFO_T_SIZE)."""
        inf: Any = None
        if info is not None:
            if len(info) < SIGINFO_T_SIZE:
                raise ValueError(f"info must be at least {SIGINFO_T_SIZE} bytes")
            inf = ctypes.cast((ctypes.c_char * len(info)).from_buffer(info), c_void_p)
        ret = self._lib.uring_waitid_sync(
            self._ctx, int(idtype), int(pid), inf, int(options), int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_waitid_sync")
        return int(ret)

    def futex_wake(self, uaddr: Union[bytearray, memoryview], val: int, mask: int, futex_flags: int, flags: int = 0) -> int:
        """IORING_OP_FUTEX_WAKE; uaddr must hold at least 4 writable bytes (aligned u32)."""
        w = (ctypes.c_uint32 * 1).from_buffer(uaddr)
        ret = self._lib.uring_futex_wake_sync(
            self._ctx,
            ctypes.byref(w[0]),
            int(val) & 0xFFFFFFFFFFFFFFFF,
            int(mask) & 0xFFFFFFFFFFFFFFFF,
            int(futex_flags) & 0xFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_futex_wake_sync")
        return int(ret)

    def futex_wait(self, uaddr: Union[bytearray, memoryview], val: int, mask: int, futex_flags: int, flags: int = 0) -> int:
        """IORING_OP_FUTEX_WAIT."""
        w = (ctypes.c_uint32 * 1).from_buffer(uaddr)
        ret = self._lib.uring_futex_wait_sync(
            self._ctx,
            ctypes.byref(w[0]),
            int(val) & 0xFFFFFFFFFFFFFFFF,
            int(mask) & 0xFFFFFFFFFFFFFFFF,
            int(futex_flags) & 0xFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_futex_wait_sync")
        return int(ret)

    def futex_waitv(self, entries: Sequence[FutexWaitv], flags: int = 0) -> int:
        """IORING_OP_FUTEX_WAITV."""
        n = len(entries)
        if n == 0:
            raise ValueError("entries must be non-empty")
        arr = (FutexWaitv * n)()
        for i, e in enumerate(entries):
            arr[i] = e
        ret = self._lib.uring_futex_waitv_sync(self._ctx, arr, int(n), int(flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_futex_waitv_sync")
        return int(ret)

    def uring_cmd(self, cmd_op: int, fd: int) -> int:
        """IORING_OP_URING_CMD."""
        ret = self._lib.uring_uring_cmd_sync(self._ctx, int(cmd_op), int(fd))
        _raise_for_neg_errno(ret, "uring_uring_cmd_sync")
        return int(ret)

    def uring_cmd128(self, cmd_op: int, fd: int) -> int:
        """IORING_OP_URING_CMD128."""
        ret = self._lib.uring_uring_cmd128_sync(self._ctx, int(cmd_op), int(fd))
        _raise_for_neg_errno(ret, "uring_uring_cmd128_sync")
        return int(ret)

    def cmd_sock(self, cmd_op: int, fd: int, level: int, optname: int, optval: Optional[bytes], optlen: int) -> int:
        """Socket uring_cmd (SOCKET_URING_OP_*)."""
        if optval is None or optlen <= 0:
            ov: Any = None
            ol = 0
        else:
            ov = (ctypes.c_char * len(optval)).from_buffer_copy(optval)
            ol = int(optlen)
        ret = self._lib.uring_cmd_sock_sync(
            self._ctx, int(cmd_op), int(fd), int(level), int(optname), ov, ol
        )
        _raise_for_neg_errno(ret, "uring_cmd_sock_sync")
        return int(ret)

    def cmd_getsockname(self, fd: int, addr: bytearray, peer: int = 0) -> int:
        """SOCKET_URING_OP_GETSOCKNAME via uring_cmd."""
        alen = c_uint(len(addr))
        arr = (ctypes.c_char * len(addr)).from_buffer(addr)
        ret = self._lib.uring_cmd_getsockname_sync(
            self._ctx, int(fd), ctypes.cast(arr, c_void_p), ctypes.byref(alen), int(peer)
        )
        _raise_for_neg_errno(ret, "uring_cmd_getsockname_sync")
        return int(ret)

    def fixed_fd_install(self, fd: int, install_flags: int = 0) -> int:
        """IORING_OP_FIXED_FD_INSTALL."""
        ret = self._lib.uring_fixed_fd_install_sync(self._ctx, int(fd), int(install_flags) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_fixed_fd_install_sync")
        return int(ret)

    def socket_direct(self, domain: int, type: int, protocol: int, file_index: int, flags: int = 0) -> int:
        """IORING_OP_SOCKET into fixed file table."""
        ret = self._lib.uring_socket_direct_sync(
            self._ctx, int(domain), int(type), int(protocol), int(file_index) & 0xFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_socket_direct_sync")
        return int(ret)

    def socket_direct_alloc(self, domain: int, type: int, protocol: int, flags: int = 0) -> int:
        """IORING_OP_SOCKET with IORING_FILE_INDEX_ALLOC."""
        ret = self._lib.uring_socket_direct_alloc_sync(
            self._ctx, int(domain), int(type), int(protocol), int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_socket_direct_alloc_sync")
        return int(ret)

    def pipe_direct(self, pipe_flags: int = 0, file_index: int = IORING_FILE_INDEX_ALLOC) -> Tuple[int, int]:
        """IORING_OP_PIPE into fixed file table."""
        fds = (c_int * 2)()
        ret = self._lib.uring_pipe_direct_sync(self._ctx, fds, int(pipe_flags), int(file_index) & 0xFFFFFFFF)
        _raise_for_neg_errno(ret, "uring_pipe_direct_sync")
        return int(fds[0]), int(fds[1])

    def msg_ring_fd(self, fd: int, source_fd: int, target_fd: int, data: int, flags: int = 0) -> None:
        """IORING_OP_MSG_RING: send fd to another ring."""
        ret = self._lib.uring_msg_ring_fd_sync(
            self._ctx,
            int(fd),
            int(source_fd),
            int(target_fd),
            int(data) & 0xFFFFFFFFFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_msg_ring_fd_sync")

    def msg_ring_fd_alloc(self, fd: int, source_fd: int, data: int, flags: int = 0) -> None:
        """IORING_MSG_SEND_FD with target index allocation."""
        ret = self._lib.uring_msg_ring_fd_alloc_sync(
            self._ctx, int(fd), int(source_fd), int(data) & 0xFFFFFFFFFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_msg_ring_fd_alloc_sync")

    def msg_ring_cqe_flags(self, fd: int, len_val: int, data: int, flags: int, cqe_flags: int) -> None:
        """IORING_OP_MSG_RING with IORING_MSG_RING_FLAGS_PASS."""
        ret = self._lib.uring_msg_ring_cqe_flags_sync(
            self._ctx,
            int(fd),
            int(len_val) & 0xFFFFFFFF,
            int(data) & 0xFFFFFFFFFFFFFFFF,
            int(flags) & 0xFFFFFFFF,
            int(cqe_flags) & 0xFFFFFFFF,
        )
        _raise_for_neg_errno(ret, "uring_msg_ring_cqe_flags_sync")

    def files_update(self, fds: Sequence[int], offset: int = 0) -> None:
        """IORING_OP_FILES_UPDATE (registered files table)."""
        n = len(fds)
        if n == 0:
            raise ValueError("fds must be non-empty")
        arr = (c_int * n)(*[int(f) for f in fds])
        ret = self._lib.uring_files_update_sync(self._ctx, arr, n, int(offset))
        _raise_for_neg_errno(ret, "uring_files_update_sync")

    def send_bundle(self, fd: int, length: int, msg_flags: int = 0) -> int:
        """IORING_OP_SEND with bundle (IOSQE_BUFFER_SELECT)."""
        ret = self._lib.uring_send_bundle_sync(self._ctx, int(fd), int(length), int(msg_flags))
        _raise_for_neg_errno(ret, "uring_send_bundle_sync")
        return int(ret)

    def readv_fixed(
        self,
        fd: int,
        parts: Sequence[Any],
        offset: int,
        rw_flags: int,
        buf_index: int,
    ) -> int:
        """IORING_OP_READV_FIXED."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            mv = memoryview(p)
            if mv.readonly:
                raise TypeError("each part must be writable")
            arr = (ctypes.c_char * mv.nbytes).from_buffer(p)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(mv.nbytes)
        ret = self._lib.uring_readv_fixed_sync(
            self._ctx,
            int(fd),
            iov,
            n,
            int(offset) & 0xFFFFFFFFFFFFFFFF,
            int(rw_flags),
            int(buf_index),
        )
        _raise_for_neg_errno(ret, "uring_readv_fixed_sync")
        return int(ret)

    def writev_fixed(
        self,
        fd: int,
        parts: Sequence[Any],
        offset: int,
        rw_flags: int,
        buf_index: int,
    ) -> int:
        """IORING_OP_WRITEV_FIXED."""
        n = len(parts)
        if n == 0:
            raise ValueError("parts must be non-empty")
        iov = (_IOVec * n)()
        keep: List[Any] = []
        for i, p in enumerate(parts):
            if isinstance(p, bytes):
                ba = p
            else:
                mv = memoryview(p)
                if not mv.contiguous:
                    raise ValueError("each part must be contiguous")
                ba = p
            arr = (ctypes.c_char * len(ba)).from_buffer_copy(ba) if isinstance(ba, bytes) else (ctypes.c_char * len(ba)).from_buffer(ba)
            keep.append(arr)
            iov[i].iov_base = ctypes.cast(arr, c_void_p)
            iov[i].iov_len = c_size_t(len(ba))
        ret = self._lib.uring_writev_fixed_sync(
            self._ctx,
            int(fd),
            iov,
            n,
            int(offset) & 0xFFFFFFFFFFFFFFFF,
            int(rw_flags),
            int(buf_index),
        )
        _raise_for_neg_errno(ret, "uring_writev_fixed_sync")
        return int(ret)

    def sendto(self, fd: int, data: bytes, msg_flags: int, addr: bytes, addr_len: int) -> int:
        """sendto(2)-style IORING_OP_SEND with destination address."""
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        abuf = (ctypes.c_char * max(len(addr), addr_len))()
        ctypes.memmove(abuf, addr, len(addr))
        ret = self._lib.uring_sendto_sync(
            self._ctx,
            int(fd),
            ctypes.cast(buf, c_void_p),
            len(data),
            int(msg_flags),
            ctypes.cast(abuf, c_void_p),
            int(addr_len),
        )
        _raise_for_neg_errno(ret, "uring_sendto_sync")
        return int(ret)

    def timeout(self, sec: int = 0, nsec: int = 0, *, count: int = 0, timeout_flags: int = 0, user_data: int = 500) -> None:
        """IORING_OP_TIMEOUT (relative if ABS flag not set)."""
        ts = KernelTimespec()
        ts.tv_sec = int(sec)
        ts.tv_nsec = int(nsec)
        ret = self._lib.uring_timeout_sync(
            self._ctx,
            ctypes.byref(ts),
            int(count) & 0xFFFFFFFF,
            int(timeout_flags) & 0xFFFFFFFF,
            int(user_data) & 0xFFFFFFFFFFFFFFFF,
        )
        # Kernel often reports fired relative timeouts as -ETIME (Timer expired).
        if ret < 0 and ret != -62:
            _raise_for_neg_errno(ret, "uring_timeout_sync")

    def timeout_remove(self, target_user_data: int, flags: int = 0) -> None:
        """IORING_OP_TIMEOUT_REMOVE."""
        ret = self._lib.uring_timeout_remove_sync(
            self._ctx, int(target_user_data) & 0xFFFFFFFFFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_timeout_remove_sync")

    def async_cancel(self, user_data: int, flags: int = 0) -> None:
        """IORING_OP_ASYNC_CANCEL (target user_data of pending op)."""
        ret = self._lib.uring_async_cancel_sync(
            self._ctx, int(user_data) & 0xFFFFFFFFFFFFFFFF, int(flags) & 0xFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_async_cancel_sync")

    def link_read_write(self, fd_in: int, buf: bytearray, offset_in: int, fd_out: int, offset_out: int) -> int:
        """IOSQE_IO_LINK: read then write sharing the same buffer."""
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        ret = self._lib.uring_link_read_write_sync(
            self._ctx, int(fd_in), ctypes.cast(arr, c_void_p), len(buf), int(offset_in), int(fd_out), int(offset_out)
        )
        _raise_for_neg_errno(ret, "uring_link_read_write_sync")
        return int(ret)

    def timeout_arm_remove_pair(self, sec: int = 60, nsec: int = 0, *, user_data: int = 9000) -> None:
        """Submit long timeout then remove it (two SQEs, one submit)."""
        ret = self._lib.uring_timeout_arm_remove_pair_sync(
            self._ctx, int(sec), int(nsec), int(user_data) & 0xFFFFFFFFFFFFFFFF
        )
        _raise_for_neg_errno(ret, "uring_timeout_arm_remove_pair_sync")

    def close(self) -> None:
        """Close the io_uring context."""
        self._buffer_keepalive.clear()
        if getattr(self, "_ctx", None):
            self._lib.uring_destroy(self._ctx)
            self._ctx = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def ring_fd(self) -> int:
        """Kernel fd for this ring's completion side (poll/epoll, :mod:`asyncio` ``add_reader``)."""
        if not getattr(self, "_ctx", None):
            raise UringError(errno.EINVAL, "uring_ring_fd", detail="UringCtx is closed")
        ret = self._lib.uring_ring_fd(self._ctx)
        _raise_for_neg_errno(ret, "uring_ring_fd")
        return int(ret)

    def read(self, fd: int, length: int, offset: int = 0) -> bytes:
        """Read data from a file descriptor using io_uring."""
        buf = ctypes.create_string_buffer(length)
        ret = self._lib.uring_read_sync(self._ctx, fd, ctypes.byref(buf), length, offset)
        _raise_for_neg_errno(ret, "uring_read_sync")
        return buf.raw[:ret]

    def write(self, fd: int, data: bytes, offset: int = 0) -> int:
        """Write data to a file descriptor using io_uring."""
        buf = ctypes.create_string_buffer(data, len(data))
        ret = self._lib.uring_write_sync(self._ctx, fd, ctypes.byref(buf), len(data), offset)
        _raise_for_neg_errno(ret, "uring_write_sync")
        return int(ret)

    def read_batch(self, fd: int, block_size: int, blocks: int, offset: int = 0) -> bytes:
        """Read multiple blocks in a batch."""
        total_len = int(block_size) * int(blocks)
        buf = ctypes.create_string_buffer(total_len)
        ret = self._lib.uring_read_batch_sync(self._ctx, fd, ctypes.byref(buf), block_size, blocks, offset)
        _raise_for_neg_errno(ret, "uring_read_batch_sync")
        return buf.raw[:ret]

    def read_offsets(self, fd: int, block_size: int, offsets: list, *, offset_bytes: bool = True) -> bytes:
        """
        Read len(offsets) blocks of size block_size into a single bytes object.
        offsets: list of byte offsets (default) or block indices (set offset_bytes=False).
        """
        blocks = len(offsets)
        total_len = int(block_size) * int(blocks)
        buf = ctypes.create_string_buffer(total_len)

        arr_type = c_longlong * blocks
        if offset_bytes:
            off_arr = arr_type(*[int(o) for o in offsets])
        else:
            off_arr = arr_type(*[int(o) * int(block_size) for o in offsets])

        ret = self._lib.uring_read_offsets_sync(
            self._ctx, fd, ctypes.byref(buf), block_size, ctypes.cast(off_arr, c_void_p), blocks
        )
        _raise_for_neg_errno(ret, "uring_read_offsets_sync")
        return buf.raw[:ret]

    # ========================================================================
    # Asynchronous API
    # ========================================================================

    def read_async(self, fd: int, buf, offset: int = 0, user_data: int = 0) -> int:
        """
        Submit an asynchronous read operation.

        Args:
            fd: File descriptor
            buf: Buffer to read into. Can be:
                - bytes/bytearray: will be used directly
                - tuple (ptr, size): from BufferPool.get_ptr()
            offset: File offset
            user_data: User data tag to identify this operation (default: 0)

        Returns:
            user_data tag on success, raises UringError on error
        """
        if isinstance(buf, tuple) and len(buf) == 2:
            # Tuple from BufferPool.get_ptr() - use read_async_ptr instead
            return self.read_async_ptr(fd, buf[0], buf[1], offset, user_data)
        elif isinstance(buf, (bytes, bytearray)):
            # Create a mutable buffer
            if isinstance(buf, bytes):
                buf = bytearray(buf)
            buf_ptr = (ctypes.c_char * len(buf)).from_buffer(buf)
            buf_len = len(buf)
        else:
            raise TypeError(f"buf must be bytes, bytearray, or tuple (ptr, size), got {type(buf)}")

        ret = self._lib.uring_read_async(self._ctx, fd, buf_ptr, buf_len, offset, user_data)
        _raise_for_neg_errno(ret, "uring_read_async")
        return int(ret)

    def read_async_ptr(self, fd: int, buf_ptr: ctypes.c_void_p, buf_len: int, offset: int = 0, user_data: int = 0) -> int:
        """
        Submit an asynchronous read operation using a raw pointer.

        Args:
            fd: File descriptor
            buf_ptr: Raw buffer pointer (c_void_p or from BufferPool.get_ptr())
            buf_len: Buffer length
            offset: File offset
            user_data: User data tag to identify this operation (default: 0)

        Returns:
            user_data tag on success, raises UringError on error
        """
        if isinstance(buf_ptr, tuple):
            buf_ptr, buf_len = buf_ptr
        elif not isinstance(buf_ptr, ctypes.c_void_p):
            buf_ptr = ctypes.c_void_p(buf_ptr)

        ret = self._lib.uring_read_async(self._ctx, fd, buf_ptr, buf_len, offset, user_data)
        _raise_for_neg_errno(ret, "uring_read_async")
        return int(ret)

    def write_async(self, fd: int, data: bytes, offset: int = 0, user_data: int = 0) -> int:
        """
        Submit an asynchronous write operation.

        Args:
            fd: File descriptor
            data: Data to write (bytes or bytearray)
            offset: File offset
            user_data: User data tag to identify this operation (default: 0)

        Returns:
            user_data tag on success, raises UringError on error
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes or bytearray")

        # For write, we can use c_char_p since we're not modifying the data
        buf_ptr = ctypes.c_char_p(data) if isinstance(data, bytes) else (ctypes.c_char * len(data)).from_buffer(data)
        ret = self._lib.uring_write_async(self._ctx, fd, buf_ptr, len(data), offset, user_data)
        _raise_for_neg_errno(ret, "uring_write_async")
        return int(ret)

    def write_async_ptr(self, fd: int, buf_ptr: ctypes.c_void_p, buf_len: int, offset: int = 0, user_data: int = 0) -> int:
        """
        Submit an asynchronous write operation using a raw pointer.

        Args:
            fd: File descriptor
            buf_ptr: Raw buffer pointer (c_void_p or from BufferPool.get_ptr())
            buf_len: Buffer length
            offset: File offset
            user_data: User data tag to identify this operation (default: 0)

        Returns:
            user_data tag on success, raises UringError on error
        """
        if isinstance(buf_ptr, tuple):
            buf_ptr, buf_len = buf_ptr
        elif not isinstance(buf_ptr, ctypes.c_void_p):
            buf_ptr = ctypes.c_void_p(buf_ptr)

        ret = self._lib.uring_write_async(self._ctx, fd, buf_ptr, buf_len, offset, user_data)
        _raise_for_neg_errno(ret, "uring_write_async")
        return int(ret)

    def wait_completion(self) -> Tuple[int, int]:
        """
        Wait for a completion (blocking).

        Returns:
            Tuple of (user_data, result) where:
            - user_data: The user_data tag passed to read_async/write_async
            - result: Bytes read/written (>=0) or negative errno on error

        Raises:
            UringError on error
        """
        user_data = c_uint64()
        result = c_int()
        ret = self._lib.uring_wait_completion(self._ctx, byref(user_data), byref(result))
        _raise_for_neg_errno(ret, "uring_wait_completion")
        return (int(user_data.value), int(result.value))

    def peek_completion(self) -> Optional[Tuple[int, int]]:
        """
        Peek at a completion without waiting (non-blocking).

        Returns:
            Tuple of (user_data, result) if completion available, None otherwise
            - user_data: The user_data tag passed to read_async/write_async
            - result: Bytes read/written (>=0) or negative errno on error

        Raises:
            UringError on error
        """
        user_data = c_uint64()
        result = c_int()
        ret = self._lib.uring_peek_completion(self._ctx, byref(user_data), byref(result))
        if ret == 0:
            return None  # No completion available
        _raise_for_neg_errno(ret, "uring_peek_completion")
        return (int(user_data.value), int(result.value))

    def submit(self) -> int:
        """
        Submit all queued operations.

        Returns:
            Number of operations submitted

        Raises:
            UringError on error
        """
        ret = self._lib.uring_submit(self._ctx)
        _raise_for_neg_errno(ret, "uring_submit")
        return int(ret)

    def submit_and_wait(self, wait_nr: int = 1) -> int:
        """
        Wait for at least 'wait_nr' completions, then submit any queued operations.

        Args:
            wait_nr: Number of completions to wait for

        Returns:
            Number of operations submitted

        Raises:
            UringError on error
        """
        ret = self._lib.uring_submit_and_wait(self._ctx, wait_nr)
        _raise_for_neg_errno(ret, "uring_submit_and_wait")
        return int(ret)

