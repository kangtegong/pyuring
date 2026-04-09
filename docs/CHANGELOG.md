# Changelog

## [0.3.0] - 2026-04-09

### Added

- **`UringAsync`**: asyncio integration via `ring_fd` + `loop.add_reader()`. File completions arrive as event-loop callbacks with no thread pool. `wait_completion()` and `wait_completion_in_executor()` APIs; `UringAsync.close()` deregisters the reader.
- **`UringError`** is now a subclass of `OSError` (`errno`, `strerror`, `filename` fields populated). **PEP 561** typing markers (`py.typed`, `__init__.pyi`) published in the wheel.
- **`UringCtx` lifecycle safety**: `single_thread_check` (default `True`) records the creating thread and raises `UringError` on cross-thread access. All entry points go through `_ring()` so use-after-`close()` raises a clear error.
- **`BufferPool`** use-after-`close()` raises `UringError`.
- **High-level helpers** (`copy`, `write`, `write_many`, `copy_path`, `copy_path_dynamic`, `write_newfile`, `write_newfile_dynamic`): `sync_policy` parameter (`"none"` / `"data"` / `"end"`), `progress_cb(done_bytes, total_bytes) -> bool` for cooperative cancel and throttling.
- **Probe cache**: `get_probe_info()`, `opcode_supported()`, `require_opcode_supported()` in `pyuring.capabilities`; result cached per-process.
- **Examples** (`examples/`): `asyncio/`, `fastapi/`, and `pytorch/` each with `before/` and `after/` showing the usual pattern vs pyuring; `README.md` documents how to run them.
- **Documentation** fully rewritten in English under `docs/`: `USAGE.md` (full API reference), `INSTALLATION.md`, `BENCHMARKS.md`, `TESTING.md`.

### Changed

- `pyproject.toml`: skip `*_i686` and `*-musllinux*` wheel builds; use `manylinux_2_28` images.
- `setup.py`: remove Python 3.6/3.7 classifiers (incompatible with `python_requires=">=3.8"`); add 3.12, `Operating System :: POSIX :: Linux`.

## [0.2.0] - 2026-04-08

PyPI release **0.2.0** (semver minor). Functionality and documentation are as summarized under **[0.1.3]** below; this tag is the recommended install target for **`pip install pyuring`**.

## [0.1.3] - 2026-04-08

### Added

- Documentation: **`docs/SUPPORT.md`** (kernel/liburing matrix), **`docs/TESTING.md`** (CI policy, coverage goals, mandatory test list). Linked from README; **`MANIFEST.in`** includes **`docs/`** for sdist.
- Regression tests: **`tests/test_regression_cancel_timeout_peek.py`** (asyncio cancel on `UringAsync.wait_completion`, short `timeout`, empty `peek_completion`, `async_cancel` errno). Removed redundant **`test_async_cancel`** in favor of the stricter case.
- `io_uring` queue setup flags, fixed file/buffer registration, and opcode probe helpers on `UringCtx`, with tests.
- Broader io_uring surface in the native wrapper; tests reorganized.
- `scripts/docker-test-matrix.sh` for running the unittest suite across several Linux base images (Docker; requires relaxed seccomp for io_uring).
- High-level `copy` / `write` / `write_many`: optional **`sync_policy`** (fsync / `RWF_DSYNC` presets) and **`progress_cb(done, total) -> bool`** for cooperative cancel (`ECANCELED`) and throttling; C pipelines invoke progress after each completed write.
- **`copy_path_dynamic`** / **`write_newfile_dynamic`**: optional **`progress_cb`** (same semantics).
- **`pyuring.capabilities`**: process-cached **`get_probe_info`**, **`opcode_supported`**, **`require_opcode_supported`**, plus doc URL constants; richer **`UringCtx`** constructor error detail when queue init fails.

### Changed

- **Documentation layout:** **`USAGE.md`**, **`INSTALLATION.md`**, **`CHANGELOG.md`**, and **`examples/BENCHMARKS.md`** (as **`docs/BENCHMARKS.md`**) now live under **`docs/`**; **`README.md`** stays at the repository root. Update bookmarks and PyPI **`project_urls`** accordingly.

- Refactored bindings: implementation lives under `pyuring.native`; `pyuring._native` remains a compatibility shim.
- **`UringCtx`**: optional **`single_thread_check`** (default **`True`**) records the creating thread and rejects cross-thread calls with **`UringError`**; all native entry points go through **`_ring()`** so use after **`close()`** raises a clear error. **`BufferPool`**: use-after-**`close()`** raises **`UringError`**. Documentation in **`USAGE.md`**; **`wait_completion_in_executor`** / tests use **`single_thread_check=False`** where the worker thread runs **`wait_completion`**.

### Fixed

- Release tooling: `publish-pypi.sh` documents `TWINE_USERNAME` / `TWINE_PASSWORD` for non-interactive PyPI uploads.

## [0.1.2] - 2026-04-08

### Changed

- README: formal API overview, tighter wording, trimmed extra Docker/benchmark tooling from the tree.
- README: Docker-based PyPI install verification and benchmark speedup chart.

### Fixed

- `publish-pypi.sh`: upload **sdist only**; PyPI rejects bare `linux_x86_64` wheels (see script header).

## [0.1.1] - 2026-04-08

### Added

- `scripts/publish-pypi.sh` for building and uploading releases.
- PyPI-oriented packaging metadata, `LICENSE`, and the `pyuring.direct` / `pyuring.raw` grouped namespace.

### Fixed

- PyPI upload docs: avoid `twine upload dist/*` when stray directories under `dist/` break Twine.

### Changed

- Package rename to **pyuring** (from **pyiouring**); vendored liburing build path adjusted.

### Notes

- First PyPI release under the **pyuring** name: ctypes bindings to `liburingwrap.so`, high-level `copy` / `write` / `write_many` helpers, and `UringCtx` for io_uring operations (Linux-only).
