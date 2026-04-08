"""ctypes structures and small constants used with liburingwrap."""
from __future__ import annotations

import ctypes
from ctypes import c_void_p, c_size_t

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


class _IOVec(ctypes.Structure):
    _fields_ = [("iov_base", c_void_p), ("iov_len", c_size_t)]

