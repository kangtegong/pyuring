"""Locate and load ``liburingwrap.so``."""
from __future__ import annotations

import ctypes
import errno
import os

from .errors import UringError


def _find_library():
    """Find the native library path."""
    # This file lives in ``pyuring/native/``; shared library is under ``pyuring/lib/``.
    _here = os.path.dirname(os.path.abspath(__file__))
    pkg_root = os.path.dirname(_here)
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

    detail = (
        f"Tried:\n"
        f"  - {installed_path}\n"
        f"  - {build_path}\n"
        f"  - system library (ctypes CDLL)\n"
        f"Ensure the package is built/installed so liburingwrap.so is available."
    )
    raise UringError(errno.ENOENT, "_find_library", detail=detail)


def _get_lib():
    """Get the native library instance."""
    lib_path = _find_library()
    if os.path.exists(lib_path):
        return ctypes.CDLL(os.path.abspath(lib_path))
    return ctypes.CDLL(lib_path)

