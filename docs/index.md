<div align="center">
  <img src="logo.png" alt="pyuring" width="420" />
</div>

# pyuring

Python bindings for file I/O using the Linux [**io_uring**](https://kernel.dk/io_uring.pdf) interface. Operations are submitted through a shared ring buffer, reducing per-call syscall overhead for concurrent or batched workloads.

The package ships a native wrapper (`liburingwrap.so`) built on [liburing](https://github.com/axboe/liburing) plus `ctypes` bindings. High-level helpers (`copy`, `write`, …) are available alongside direct `UringCtx` / `UringAsync` control.

**Requirements:** Linux kernel 5.15+, Python 3.8+

```bash
pip install pyuring
```

Use the **navigation** for installation, full API reference, benchmarks, and changelog. The canonical README with long-form examples also lives [on GitHub](https://github.com/kangtegong/pyuring#readme).
