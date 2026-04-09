# Testing

## Running the tests

The default test runner is Python's built-in `unittest`. pytest works too, but CI and release checks use `unittest`.

```bash
# Build the native library first, then run all tests
make
PYTHONPATH=. python3 -m unittest discover -s tests -v

# Using pytest (optional)
pytest tests/
```

If you installed pyuring with `pip install -e .`, you can omit `PYTHONPATH=.`.

Do not run the tests from a directory where `import pyuring` would resolve to an unbuilt source tree (i.e. a tree without a built `liburingwrap.so`). If that happens, `import pyuring` will fail at the `.so` load step.

## Test coverage

The `tests/` directory contains 23 test files. Each one covers a specific area of the library.

| Test file | What it covers |
|-----------|----------------|
| `test_lifecycle_contracts` | `UringCtx` and `BufferPool` behavior after `close()`, thread check (using from a non-creator thread). |
| `test_uring_error` | `UringError` fields (`errno`, `operation`, `detail`), subclass of `OSError`. |
| `test_ring_probe_setup` | Ring creation with various `IORING_SETUP_*` flags; opcode probe (`probe_opcode_supported`, `probe_last_op`, `probe_supported_mask`); nop submission. |
| `test_aio` | `UringAsync.wait_completion`, `wait_completion_in_executor`, behavior when `UringCtx` is closed before awaiting. |
| `test_easy_and_c_api` | `copy`, `write`, `write_many` helpers; `copy_path`, `write_newfile`, `write_manyfiles` direct functions; `progress_cb` cancel. |
| `test_capabilities_and_easy` | Module-level `opcode_supported`, `require_opcode_supported`, `get_probe_info`; probe cache refresh. |
| `test_regression_cancel_timeout_peek` | asyncio task cancellation during `wait_completion`; `peek_completion` when queue is empty; timeout SQE submission. |
| `test_buffer_pool` | `BufferPool.create`, `get`, `get_ptr`, `resize`, `set_size`, `close`, use-after-close. |
| `test_read_write_helpers` | `UringCtx.read`, `write`, `read_batch`, `read_offsets`. |
| `test_vectors_io` | `readv` / `writev` (scatter-gather). |
| `test_vectors_fixed_io` | `read_fixed` / `write_fixed` with registered buffers. |
| `test_register_fixed_io` | `register_files`, `unregister_files`, `register_buffers`, `unregister_buffers`. |
| `test_vfs_ops` | `openat`, `close`, `fsync`, `fallocate`, `statx`, `renameat`, `unlinkat`, `mkdirat`. |
| `test_socket_pipe_openat2` | `socket`, `pipe`, `bind`, `listen`, `accept`, `connect`, `openat2`. |
| `test_sockets_stream` | `send` / `recv` over a connected socket pair. |
| `test_splice_timeouts_links` | `splice`, `tee`; timeout SQEs; SQE link chains (`IOSQE_IO_LINK`). |
| `test_poll_tee_symlink` | `poll_add`, `poll_remove`; `tee`; `symlinkat`, `linkat`. |
| `test_sync_advice_cancel_fd` | `sync_file_range`, `fadvise`, `madvise`, `async_cancel` by fd. |
| `test_epoll_buffers_xattr` | `epoll_ctl`, `provide_buffers`, `remove_buffers`, `getxattr`, `setxattr`. |
| `test_prep_smoke_extended` | Smoke tests for less common ops: `msg_ring`, `ftruncate`, `waitid`, `futex_*`, zero-copy send. |
| `test_easy_and_c_api` | (see above) |
| `test_package_exports` | `__all__` completeness, `pyuring.direct` and `pyuring.raw` namespace contents. |

Tests that require kernel features not available on the current kernel (e.g. certain `IORING_SETUP_*` flags or opcodes) are skipped automatically using `unittest.skip`.

## Coverage

Coverage is a soft target, not a merge gate. The goal is to not decrease coverage on the `pyuring/native` package when making substantial changes. A long-term aspiration is 60%+ line coverage on that package.

```bash
pip install coverage
coverage run -m unittest discover -s tests
coverage report -m
```

## Docker test matrix

`scripts/docker-test-matrix.sh` runs the full unittest suite inside several Linux container images to catch distribution-specific issues.

```bash
./scripts/docker-test-matrix.sh
```

io_uring requires a relaxed seccomp profile in Docker. The script passes the necessary flags. If you are running in a restricted environment (e.g. some CI providers), you may need to enable `--privileged` or a custom seccomp policy.
