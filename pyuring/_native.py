"""
Native library bindings for io_uring operations.
"""

from __future__ import annotations

import ctypes
import gc
import mmap
import os
from typing import Tuple, Optional, Sequence, List, Any, Union
from ctypes import c_int, c_uint, c_longlong, c_void_p, c_char_p, CFUNCTYPE, c_uint64, POINTER, byref, c_size_t


# --- io_uring_setup flags (linux/io_uring.h) ---
IORING_SETUP_IOPOLL = 1 << 0
IORING_SETUP_SQPOLL = 1 << 1
IORING_SETUP_SQ_AFF = 1 << 2
IORING_SETUP_CQSIZE = 1 << 3
IORING_SETUP_CLAMP = 1 << 4
IORING_SETUP_ATTACH_WQ = 1 << 5
IORING_SETUP_R_DISABLED = 1 << 6
IORING_SETUP_SUBMIT_ALL = 1 << 7
IORING_SETUP_COOP_TASKRUN = 1 << 8
IORING_SETUP_TASKRUN_FLAG = 1 << 9
IORING_SETUP_SQE128 = 1 << 10
IORING_SETUP_CQE32 = 1 << 11
IORING_SETUP_SINGLE_ISSUER = 1 << 12
IORING_SETUP_DEFER_TASKRUN = 1 << 13
IORING_SETUP_NO_MMAP = 1 << 14
IORING_SETUP_REGISTERED_FD_ONLY = 1 << 15
IORING_SETUP_NO_SQARRAY = 1 << 16
IORING_SETUP_HYBRID_IOPOLL = 1 << 17
IORING_SETUP_CQE_MIXED = 1 << 18
IORING_SETUP_SQE_MIXED = 1 << 19
IORING_SETUP_SQ_REWIND = 1 << 20

# --- sqe->flags (IOSQE_*) ---
IOSQE_FIXED_FILE = 1 << 0
IOSQE_IO_DRAIN = 1 << 1
IOSQE_IO_LINK = 1 << 2
IOSQE_IO_HARDLINK = 1 << 3
IOSQE_ASYNC = 1 << 4
IOSQE_BUFFER_SELECT = 1 << 5
IOSQE_CQE_SKIP_SUCCESS = 1 << 6

# --- enum io_uring_op (kernel UAPI; values must match linux/io_uring.h) ---
IORING_OP_NOP = 0
IORING_OP_READV = 1
IORING_OP_WRITEV = 2
IORING_OP_FSYNC = 3
IORING_OP_READ_FIXED = 4
IORING_OP_WRITE_FIXED = 5
IORING_OP_POLL_ADD = 6
IORING_OP_POLL_REMOVE = 7
IORING_OP_SYNC_FILE_RANGE = 8
IORING_OP_SENDMSG = 9
IORING_OP_RECVMSG = 10
IORING_OP_TIMEOUT = 11
IORING_OP_TIMEOUT_REMOVE = 12
IORING_OP_ACCEPT = 13
IORING_OP_ASYNC_CANCEL = 14
IORING_OP_LINK_TIMEOUT = 15
IORING_OP_CONNECT = 16
IORING_OP_FALLOCATE = 17
IORING_OP_OPENAT = 18
IORING_OP_CLOSE = 19
IORING_OP_FILES_UPDATE = 20
IORING_OP_STATX = 21
IORING_OP_READ = 22
IORING_OP_WRITE = 23
IORING_OP_FADVISE = 24
IORING_OP_MADVISE = 25
IORING_OP_SEND = 26
IORING_OP_RECV = 27
IORING_OP_OPENAT2 = 28
IORING_OP_EPOLL_CTL = 29
IORING_OP_SPLICE = 30
IORING_OP_PROVIDE_BUFFERS = 31
IORING_OP_REMOVE_BUFFERS = 32
IORING_OP_TEE = 33
IORING_OP_SHUTDOWN = 34
IORING_OP_RENAMEAT = 35
IORING_OP_UNLINKAT = 36
IORING_OP_MKDIRAT = 37
IORING_OP_SYMLINKAT = 38
IORING_OP_LINKAT = 39
IORING_OP_MSG_RING = 40
IORING_OP_FSETXATTR = 41
IORING_OP_SETXATTR = 42
IORING_OP_FGETXATTR = 43
IORING_OP_GETXATTR = 44
IORING_OP_SOCKET = 45
IORING_OP_URING_CMD = 46
IORING_OP_SEND_ZC = 47
IORING_OP_SENDMSG_ZC = 48
IORING_OP_READ_MULTISHOT = 49
IORING_OP_WAITID = 50
IORING_OP_FUTEX_WAIT = 51
IORING_OP_FUTEX_WAKE = 52
IORING_OP_FUTEX_WAITV = 53
IORING_OP_FIXED_FD_INSTALL = 54
IORING_OP_FTRUNCATE = 55
IORING_OP_BIND = 56
IORING_OP_LISTEN = 57
IORING_OP_RECV_ZC = 58
IORING_OP_EPOLL_WAIT = 59
IORING_OP_READV_FIXED = 60
IORING_OP_WRITEV_FIXED = 61
IORING_OP_PIPE = 62
IORING_OP_NOP128 = 63
IORING_OP_URING_CMD128 = 64
IORING_OP_LAST = 65

# IORING_MSG_RING command types (enum io_uring_msg_ring_flags)
IORING_MSG_DATA = 0
IORING_MSG_SEND_FD = 1

# openat / statx / fallocate (Linux UAPI)
AT_FDCWD = -100
AT_REMOVEDIR = 0x200
AT_SYMLINK_NOFOLLOW = 0x100
IORING_FSYNC_DATASYNC = 1 << 0
STATX_BASIC_STATS = 0x000007FF
FALLOC_FL_KEEP_SIZE = 0x01
FALLOC_FL_ZERO_RANGE = 0x10
SPLICE_F_MOVE = 0x01
SPLICE_F_FD_IN_FIXED = 1 << 31

IORING_FILE_INDEX_ALLOC = 0xFFFFFFFF

IORING_TIMEOUT_ABS = 1 << 0
IORING_TIMEOUT_UPDATE = 1 << 1
IORING_TIMEOUT_BOOTTIME = 1 << 2
IORING_TIMEOUT_REALTIME = 1 << 3
IORING_LINK_TIMEOUT_UPDATE = 1 << 4
IORING_TIMEOUT_ETIME_SUCCESS = 1 << 5
IORING_TIMEOUT_MULTISHOT = 1 << 6
IORING_TIMEOUT_CLOCK_MASK = IORING_TIMEOUT_BOOTTIME | IORING_TIMEOUT_REALTIME
IORING_TIMEOUT_UPDATE_MASK = IORING_TIMEOUT_UPDATE | IORING_LINK_TIMEOUT_UPDATE

IORING_POLL_ADD_MULTI = 1 << 0
IORING_POLL_UPDATE_EVENTS = 1 << 1
IORING_POLL_UPDATE_USER_DATA = 1 << 2
IORING_POLL_ADD_LEVEL = 1 << 3

IORING_ASYNC_CANCEL_ALL = 1 << 0
IORING_ASYNC_CANCEL_FD = 1 << 1
IORING_ASYNC_CANCEL_ANY = 1 << 2
IORING_ASYNC_CANCEL_FD_FIXED = 1 << 3
IORING_ASYNC_CANCEL_USERDATA = 1 << 4
IORING_ASYNC_CANCEL_OP = 1 << 5

IORING_RECVSEND_POLL_FIRST = 1 << 0
IORING_RECV_MULTISHOT = 1 << 1
IORING_RECVSEND_FIXED_BUF = 1 << 2
IORING_SEND_ZC_REPORT_USAGE = 1 << 3
IORING_RECVSEND_BUNDLE = 1 << 4
IORING_SEND_VECTORIZED = 1 << 5

IORING_NOTIF_USAGE_ZC_COPIED = 1 << 31

IORING_ACCEPT_MULTISHOT = 1 << 0
IORING_ACCEPT_DONTWAIT = 1 << 1
IORING_ACCEPT_POLL_FIRST = 1 << 2

IORING_MSG_RING_CQE_SKIP = 1 << 0
IORING_MSG_RING_FLAGS_PASS = 1 << 1

IORING_FIXED_FD_NO_CLOEXEC = 1 << 0

IORING_NOP_INJECT_RESULT = 1 << 0
IORING_NOP_CQE32 = 1 << 5

IORING_CQE_F_BUFFER = 1 << 0
IORING_CQE_F_MORE = 1 << 1
IORING_CQE_F_SOCK_NONEMPTY = 1 << 2
IORING_CQE_F_NOTIF = 1 << 3
IORING_CQE_F_BUF_MORE = 1 << 4
IORING_CQE_F_SKIP = 1 << 5
IORING_CQE_F_32 = 1 << 15
IORING_CQE_BUFFER_SHIFT = 16

IORING_SQ_NEED_WAKEUP = 1 << 0
IORING_SQ_CQ_OVERFLOW = 1 << 1
IORING_SQ_TASKRUN = 1 << 2

IORING_CQ_EVENTFD_DISABLED = 1 << 0

IORING_ENTER_GETEVENTS = 1 << 0
IORING_ENTER_SQ_WAKEUP = 1 << 1
IORING_ENTER_SQ_WAIT = 1 << 2
IORING_ENTER_EXT_ARG = 1 << 3
IORING_ENTER_REGISTERED_RING = 1 << 4
IORING_ENTER_ABS_TIMER = 1 << 5
IORING_ENTER_EXT_ARG_REG = 1 << 6
IORING_ENTER_NO_IOWAIT = 1 << 7

IORING_URING_CMD_FIXED = 1 << 0

IORING_OFF_SQ_RING = 0
IORING_OFF_CQ_RING = 0x8000000
IORING_OFF_SQES = 0x10000000
IORING_OFF_PBUF_RING = 0x80000000
IORING_OFF_PBUF_SHIFT = 16
IORING_OFF_MMAP_MASK = 0xF8000000

IORING_RW_ATTR_FLAG_PI = 1 << 0

# sync_file_range(2) flags (Linux)
SYNC_FILE_RANGE_WAIT_BEFORE = 1
SYNC_FILE_RANGE_WRITE = 2
SYNC_FILE_RANGE_WAIT_AFTER = 4

# posix_fadvise(2) advice (POSIX / Linux)
POSIX_FADV_NORMAL = 0
POSIX_FADV_RANDOM = 1
POSIX_FADV_SEQUENTIAL = 2
POSIX_FADV_WILLNEED = 3
POSIX_FADV_DONTNEED = 4
POSIX_FADV_NOREUSE = 5

# madvise(2) — common Linux values
MADV_NORMAL = 0
MADV_RANDOM = 1
MADV_SEQUENTIAL = 2
MADV_WILLNEED = 3
MADV_DONTNEED = 4


class KernelTimespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_int64), ("tv_nsec", ctypes.c_int64)]


class OpenHow(ctypes.Structure):
    """openat2(2) parameters (see liburing compat / linux open_how)."""

    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]


class EpollEvent(ctypes.Structure):
    """struct epoll_event (layout for epoll_ctl add/mod)."""

    _fields_ = [
        ("events", ctypes.c_uint32),
        ("_pad", ctypes.c_uint32),
        ("data", ctypes.c_uint64),
    ]


class FutexWaitv(ctypes.Structure):
    """struct futex_waitv (liburing compat / linux)."""

    _fields_ = [
        ("val", ctypes.c_uint64),
        ("uaddr", ctypes.c_uint64),
        ("flags", ctypes.c_uint32),
        ("_reserved", ctypes.c_uint32),
    ]


# enum io_uring_socket_op (liburing/io_uring.h)
SOCKET_URING_OP_SIOCINQ = 0
SOCKET_URING_OP_SIOCOUTQ = 1
SOCKET_URING_OP_GETSOCKOPT = 2
SOCKET_URING_OP_SETSOCKOPT = 3
SOCKET_URING_OP_TX_TIMESTAMP = 4
SOCKET_URING_OP_GETSOCKNAME = 5

# Typical size for siginfo_t buffer passed to waitid(2) via io_uring
SIGINFO_T_SIZE = 128


class _IOVec(ctypes.Structure):
    _fields_ = [("iov_base", c_void_p), ("iov_len", c_size_t)]


class UringError(RuntimeError):
    """Exception raised for io_uring related errors."""
    pass


def _raise_for_neg_errno(ret: int, what: str) -> None:
    if ret >= 0:
        return
    err = -ret
    raise UringError(f"{what} failed: {-ret} ({os.strerror(err)})")


def _find_library():
    """Find the native library path."""
    pkg_root = os.path.dirname(os.path.abspath(__file__))
    installed_path = os.path.join(pkg_root, "lib", "liburingwrap.so")
    if os.path.exists(installed_path):
        return installed_path

    project_root = os.path.dirname(pkg_root)
    build_path = os.path.join(project_root, "build", "liburingwrap.so")
    if os.path.exists(build_path):
        return build_path

    try:
        lib = ctypes.CDLL("liburingwrap.so")
        return "liburingwrap.so"
    except OSError:
        pass

    raise UringError(
        f"liburingwrap.so not found. Tried:\n"
        f"  - {installed_path}\n"
        f"  - {build_path}\n"
        f"  - system library\n"
        f"Please ensure the package is properly installed."
    )


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
            raise UringError(
                "uring_create_ex failed (NULL). Is liburing installed and does the kernel support io_uring?"
            )
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


class BufferPool:
    """Buffer pool for dynamic buffer size management."""

    def __init__(self, lib, pool_ptr: c_void_p):
        self._lib = lib
        self._pool = pool_ptr

    @classmethod
    def create(cls, initial_count: int = 8, initial_size: int = 4096):
        """Create a new buffer pool."""
        lib = _get_lib()
        lib.uring_buffer_pool_create.argtypes = [c_uint, c_uint]
        lib.uring_buffer_pool_create.restype = c_void_p

        lib.uring_buffer_pool_destroy.argtypes = [c_void_p]
        lib.uring_buffer_pool_destroy.restype = None

        lib.uring_buffer_pool_resize.argtypes = [c_void_p, c_uint, c_uint]
        lib.uring_buffer_pool_resize.restype = c_int

        lib.uring_buffer_pool_get.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        lib.uring_buffer_pool_get.restype = c_void_p

        lib.uring_buffer_pool_set_size.argtypes = [c_void_p, c_uint, c_uint]
        lib.uring_buffer_pool_set_size.restype = c_int

        pool_ptr = lib.uring_buffer_pool_create(initial_count, initial_size)
        if not pool_ptr:
            raise UringError("Failed to create buffer pool")
        return cls(lib, pool_ptr)

    def resize(self, index: int, new_size: int) -> None:
        """Resize a buffer in the pool."""
        ret = self._lib.uring_buffer_pool_resize(self._pool, index, new_size)
        _raise_for_neg_errno(ret, "uring_buffer_pool_resize")

    def get(self, index: int) -> bytes:
        """Get buffer data as bytes."""
        size = c_uint()
        buf_ptr = self._lib.uring_buffer_pool_get(self._pool, index, byref(size))
        if not buf_ptr:
            raise UringError(f"Invalid buffer index: {index}")
        return ctypes.string_at(buf_ptr, size.value)

    def get_ptr(self, index: int) -> Tuple[ctypes.c_void_p, int]:
        """Get buffer pointer and size (for use with async operations)."""
        size = c_uint()
        buf_ptr = self._lib.uring_buffer_pool_get(self._pool, index, byref(size))
        if not buf_ptr:
            raise UringError(f"Invalid buffer index: {index}")
        return (buf_ptr, int(size.value))

    def set_size(self, index: int, size: int) -> None:
        """Set buffer size without reallocation (must be <= capacity)."""
        ret = self._lib.uring_buffer_pool_set_size(self._pool, index, size)
        _raise_for_neg_errno(ret, "uring_buffer_pool_set_size")

    def close(self) -> None:
        """Destroy the buffer pool."""
        if self._pool:
            self._lib.uring_buffer_pool_destroy(self._pool)
            self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _get_lib():
    """Get the native library instance."""
    lib_path = _find_library()
    if os.path.exists(lib_path):
        return ctypes.CDLL(os.path.abspath(lib_path))
    return ctypes.CDLL(lib_path)


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


def copy_path_dynamic(
    src_path: str,
    dst_path: str,
    *,
    qd: int = 32,
    block_size: int = 1 << 20,
    buffer_size_cb: callable = None,
    fsync: bool = False,
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

    lib.uring_copy_path_dynamic.argtypes = [
        c_char_p, c_char_p, c_uint, c_uint,
        BufferSizeCallback, c_void_p, c_int
    ]
    lib.uring_copy_path_dynamic.restype = c_longlong

    ret = lib.uring_copy_path_dynamic(
        src_path.encode(),
        dst_path.encode(),
        int(qd),
        int(block_size),
        callback_func,
        None,  # user_data
        int(bool(fsync)),
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

    lib.uring_write_newfile_dynamic.argtypes = [
        c_char_p, c_uint, c_uint, c_uint, c_int, c_int,
        BufferSizeCallback, c_void_p
    ]
    lib.uring_write_newfile_dynamic.restype = c_longlong

    ret = lib.uring_write_newfile_dynamic(
        dst_path.encode(),
        int(total_mb),
        int(block_size),
        int(qd),
        int(bool(fsync)),
        int(bool(dsync)),
        callback_func,
        None,  # user_data
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


# Kernel/io_uring UAPI integer symbols defined in this module (for pyuring package re-export).
_UAPI_PREFIXES = (
    "IORING_",
    "IOSQE_",
    "AT_",
    "SPLICE_F_",
    "FALLOC_FL_",
    "STATX_",
    "SYNC_FILE_RANGE_",
    "POSIX_FADV_",
    "MADV_",
    "SOCKET_URING_",
)
UAPI_CONSTANT_NAMES = tuple(
    sorted(
        name
        for name, val in list(globals().items())
        if isinstance(val, int) and not isinstance(val, bool) and any(name.startswith(p) for p in _UAPI_PREFIXES)
    )
)
del _UAPI_PREFIXES
