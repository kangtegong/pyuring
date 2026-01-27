import ctypes
import os
from ctypes import c_int, c_uint, c_longlong, c_void_p, c_char_p, CFUNCTYPE


class UringError(RuntimeError):
    pass


def _raise_for_neg_errno(ret: int, what: str) -> None:
    if ret >= 0:
        return
    err = -ret
    raise UringError(f"{what} failed: {-ret} ({os.strerror(err)})")


class UringCtx:
    def __init__(self, lib_path: str = None, entries: int = 64):
        if lib_path is None:
            lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
        lib_path = os.path.abspath(lib_path)

        self._lib = ctypes.CDLL(lib_path)

        self._lib.uring_create.argtypes = [c_uint]
        self._lib.uring_create.restype = c_void_p

        self._lib.uring_destroy.argtypes = [c_void_p]
        self._lib.uring_destroy.restype = None

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

        ctx = self._lib.uring_create(entries)
        if not ctx:
            # errno from CDLL isn't straightforward; just give a helpful message.
            raise UringError(
                "uring_create failed (NULL). Is liburing installed and does the kernel support io_uring?"
            )
        self._ctx = ctx

    def close(self) -> None:
        if getattr(self, "_ctx", None):
            self._lib.uring_destroy(self._ctx)
            self._ctx = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def read(self, fd: int, length: int, offset: int = 0) -> bytes:
        buf = ctypes.create_string_buffer(length)
        ret = self._lib.uring_read_sync(self._ctx, fd, ctypes.byref(buf), length, offset)
        _raise_for_neg_errno(ret, "uring_read_sync")
        return buf.raw[:ret]

    def write(self, fd: int, data: bytes, offset: int = 0) -> int:
        buf = ctypes.create_string_buffer(data, len(data))
        ret = self._lib.uring_write_sync(self._ctx, fd, ctypes.byref(buf), len(data), offset)
        _raise_for_neg_errno(ret, "uring_write_sync")
        return int(ret)

    def read_batch(self, fd: int, block_size: int, blocks: int, offset: int = 0) -> bytes:
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


def copy_path(src_path: str, dst_path: str, *, qd: int = 32, block_size: int = 1 << 20, lib_path: str = None) -> int:
    """
    Copy file using io_uring pipeline in C (read->write), minimizing Python overhead.
    Returns bytes copied.
    """
    if lib_path is None:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
    lib = ctypes.CDLL(os.path.abspath(lib_path))
    lib.uring_copy_path.argtypes = [c_char_p, c_char_p, c_uint, c_uint]
    lib.uring_copy_path.restype = c_longlong

    ret = lib.uring_copy_path(src_path.encode(), dst_path.encode(), int(qd), int(block_size))
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_copy_path")
    return int(ret)


def copy_path_dynamic(
    src_path: str,
    dst_path: str,
    *,
    qd: int = 32,
    block_size: int = 1 << 20,
    buffer_size_cb: callable = None,
    fsync: bool = False,
    lib_path: str = None,
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
        lib_path: Optional path to liburingwrap.so
    
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
    if lib_path is None:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
    lib = ctypes.CDLL(os.path.abspath(lib_path))
    
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
    lib_path: str = None,
) -> int:
    """
    Write a brand-new file with many small sequential writes using io_uring in C.
    Returns bytes written.
    """
    if lib_path is None:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
    lib = ctypes.CDLL(os.path.abspath(lib_path))
    lib.uring_write_newfile.argtypes = [c_char_p, c_uint, c_uint, c_uint, c_int, c_int]
    lib.uring_write_newfile.restype = c_longlong

    ret = lib.uring_write_newfile(
        dst_path.encode(), int(total_mb), int(block_size), int(qd), int(bool(fsync)), int(bool(dsync))
    )
    _raise_for_neg_errno(int(ret) if ret < 0 else 0, "uring_write_newfile")
    return int(ret)


# Callback type for dynamic buffer size adjustment
# Signature: (current_offset: int, total_bytes: int, default_block_size: int, user_data: void*) -> int
BufferSizeCallback = CFUNCTYPE(c_uint, ctypes.c_uint64, ctypes.c_uint64, c_uint, c_void_p)


def write_newfile_dynamic(
    dst_path: str,
    *,
    total_mb: int,
    block_size: int = 4096,
    qd: int = 256,
    fsync: bool = False,
    dsync: bool = False,
    buffer_size_cb: callable = None,
    lib_path: str = None,
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
        lib_path: Optional path to liburingwrap.so
    
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
    if lib_path is None:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
    lib = ctypes.CDLL(os.path.abspath(lib_path))
    
    # Define callback wrapper
    callback_wrapper = None
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
    lib_path: str = None,
) -> int:
    """
    Write many brand-new files using io_uring in C.
    Returns total bytes written across all files.
    """
    if lib_path is None:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "build", "liburingwrap.so")
    lib = ctypes.CDLL(os.path.abspath(lib_path))
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


