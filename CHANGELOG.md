# Changelog

## [0.1.3] - 2026-04-08

### Added

- `io_uring` queue setup flags, fixed file/buffer registration, and opcode probe helpers on `UringCtx`, with tests.
- Broader io_uring surface in the native wrapper; tests reorganized.
- `scripts/docker-test-matrix.sh` for running the unittest suite across several Linux base images (Docker; requires relaxed seccomp for io_uring).

### Changed

- Refactored bindings: implementation lives under `pyuring.native`; `pyuring._native` remains a compatibility shim.

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
