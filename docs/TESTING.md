# Testing policy

## Runner

- **Default / CI:** Python’s **`unittest`** (`python3 -m unittest discover -s tests -v`).
- **pytest:** Optional. The tree does not require pytest; contributors may run `pytest tests/` if they install pytest, but **CI and release checks use unittest** unless explicitly changed.

## Coverage (goals)

- **Line coverage** is a **soft target**, not a merge gate: aim to **not decrease** coverage on substantive changes; incremental improvement is welcome.
- Suggested command (optional):  
  `coverage run -m unittest discover -s tests && coverage report`  
  There is **no fixed percentage** enforced in this repository yet; treat **~60%+ on `pyuring/native`** as a reasonable long-term aspiration when touching that code.

## Mandatory test areas (must stay green)

The following areas must have automated coverage via `tests/` (file names may evolve; keep equivalents when refactoring):

| Area | Role |
|------|------|
| **Lifecycle / thread** | `test_lifecycle_contracts` — closed `UringCtx` / `BufferPool`, thread check. |
| **Errors** | `test_uring_error` — `UringError` shape and errno. |
| **Ring / probe** | `test_ring_probe_setup` — nop, probe, setup flags (skip if kernel lacks feature). |
| **Aio** | `test_aio` — `UringAsync`, executor path, closed context. |
| **High-level API** | `test_easy_and_c_api`, `test_capabilities_and_easy` — copy/write/probe/progress. |
| **Regression (async / io)** | `test_regression_cancel_timeout_peek` — cancel, timeout, empty peek (see file docstring). |

## Docker matrix

- **`scripts/docker-test-matrix.sh`** runs the same unittest suite in multiple Linux images (requires relaxed seccomp for io_uring). Use before releases when possible.

## Release linkage

- **[CHANGELOG.md](CHANGELOG.md)** summarizes user-visible changes; keep it in sync with notable test additions.
- Project **TODO** / roadmap items: trim or check off when done; point here for testing expectations.
