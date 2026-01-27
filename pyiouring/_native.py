"""
Native library bindings for io_uring operations.
"""

import ctypes
import os
import sys
from ctypes import c_int, c_uint, c_longlong, c_void_p, c_char_p, CFUNCTYPE, c_uint64, POINTER, Structure, byref


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
    # First, try to find it in the package directory (installed package)
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Try installed location: pyiouring/lib/liburingwrap.so
    installed_path = os.path.join(package_dir, "pyiouring", "lib", "liburingwrap.so")
    if os.path.exists(installed_path):
        return installed_path
    
    # Try build directory (development mode)
    build_path = os.path.join(package_dir, "build", "liburingwrap.so")
    if os.path.exists(build_path):
        return build_path
    
    # Try system library
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
    
    def __init__(self, lib_path: str = None, entries: int = 64):
        if lib_path is None:
            lib_path = _find_library()
        lib_path = os.path.abspath(lib_path) if os.path.exists(lib_path) else lib_path

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

        ctx = self._lib.uring_create(entries)
        if not ctx:
            raise UringError(
                "uring_create failed (NULL). Is liburing installed and does the kernel support io_uring?"
            )
        self._ctx = ctx

    def close(self) -> None:
        """Close the io_uring context."""
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

    def wait_completion(self) -> tuple[int, int]:
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

    def peek_completion(self) -> tuple[int, int] | None:
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
    
    def get_ptr(self, index: int) -> tuple[ctypes.c_void_p, int]:
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

