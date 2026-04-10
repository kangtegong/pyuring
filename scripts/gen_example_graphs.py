#!/usr/bin/env python3
"""
Regenerate docs/graphs/*.svg for examples/README.

Requires **numpy** (``pip install numpy``) for NumPy-style shard generation and
the ``numpy_bins`` chart.

Tune SHARDS / SHARD_KB / URING_BATCH / etc. if you need different bars or
hardware-specific behaviour, then re-run:

    PYTHONPATH=. python3 scripts/gen_example_graphs.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pyuring import UringAsync, UringCtx, UringError

REPEATS = 5
SHARDS = 160
SHARDS_FASTAPI = 192  # same pattern, different N so the third chart is not pixel-identical to the first
SHARDS_NUMPY = 144
SHARDS_CACHED = 168  # split-blob → many part files
SHARDS_SQLITE = 152  # exported shard_*.bin layout
SHARD_KB = 64
CACHED_CHUNK_KB = 64  # part size after splitting cached blob (matches examples/cached_reads defaults)
TP_WORKERS = 8
URING_BATCH = 32


def _mib_s(total_bytes: int, elapsed_s: float) -> float:
    if elapsed_s <= 0:
        return 0.0
    return total_bytes / elapsed_s / (1024 * 1024)


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:05d}.bin")
        with open(p, "wb") as f:
            f.write(bytes([i & 0xFF]) * (size_kb * 1024))
        paths.append(p)
    return paths


def create_shards_sqlite_names(tmpdir: str, n: int, size_kb: int) -> List[str]:
    """Same bytes as create_shards; filenames match examples/sqlite_blobs/export_db.py."""
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        with open(p, "wb") as f:
            f.write(bytes([i & 0xFF]) * (size_kb * 1024))
        paths.append(p)
    return paths


def create_numpy_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    import numpy as np

    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        data = np.full(size_kb * 1024, i & 0xFF, dtype=np.uint8)
        data.tofile(p)
        paths.append(p)
    return paths


def write_blob_and_split_parts(
    tmpdir: str, n_parts: int, chunk_kb: int
) -> List[str]:
    """One blob sized n_parts * chunk_kb; split into part_*.bin like cached_reads."""
    chunk = chunk_kb * 1024
    blob_path = os.path.join(tmpdir, "cached_blob.bin")
    with open(blob_path, "wb") as f:
        for i in range(n_parts):
            f.write(bytes([(i * 13) & 0xFF]) * chunk)
    paths: List[str] = []
    with open(blob_path, "rb") as f:
        i = 0
        while True:
            data = f.read(chunk)
            if not data:
                break
            p = os.path.join(tmpdir, f"part_{i:05d}.bin")
            with open(p, "wb") as out:
                out.write(data)
            paths.append(p)
            i += 1
    return paths


def read_one(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def bench_threadpool(paths: List[str]) -> float:
    total = sum(os.path.getsize(p) for p in paths)

    def run() -> float:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=TP_WORKERS) as ex:
            list(ex.map(read_one, paths))
        return time.perf_counter() - t0

    times = [run() for _ in range(REPEATS)]
    return _mib_s(total, statistics.median(times))


def bench_uring_batched(paths: List[str]) -> float:
    total = sum(os.path.getsize(p) for p in paths)
    file_size = os.path.getsize(paths[0])

    def run() -> float:
        t0 = time.perf_counter()
        with UringCtx(entries=max(URING_BATCH, 64), setup_flags=0) as ctx:
            i = 0
            while i < len(paths):
                batch = paths[i : i + URING_BATCH]
                fds = []
                bufs = []
                for j, path in enumerate(batch):
                    fd = os.open(path, os.O_RDONLY)
                    fds.append(fd)
                    b = bytearray(file_size)
                    bufs.append(b)
                    ctx.read_async(fd, b, offset=0, user_data=j)
                ctx.submit()
                for _ in range(len(batch)):
                    ud, n = ctx.wait_completion()
                    if n < 0:
                        raise UringError(-n, "uring_batch")
                for fd in fds:
                    os.close(fd)
                i += URING_BATCH
        return time.perf_counter() - t0

    times = [run() for _ in range(REPEATS)]
    return _mib_s(total, statistics.median(times))


def bench_numpy_threadpool(paths: List[str]) -> float:
    import numpy as np

    total = sum(os.path.getsize(p) for p in paths)

    def read_one(path: str) -> int:
        x = np.fromfile(path, dtype=np.uint8)
        return int(x.sum())

    def run() -> float:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=TP_WORKERS) as ex:
            list(ex.map(read_one, paths))
        return time.perf_counter() - t0

    times = [run() for _ in range(REPEATS)]
    return _mib_s(total, statistics.median(times))


def bench_numpy_uring_batched(paths: List[str]) -> float:
    import numpy as np

    total = sum(os.path.getsize(p) for p in paths)
    file_size = os.path.getsize(paths[0])

    def run() -> float:
        t0 = time.perf_counter()
        with UringCtx(entries=max(URING_BATCH, 64), setup_flags=0) as ctx:
            i = 0
            while i < len(paths):
                batch = paths[i : i + URING_BATCH]
                fds = []
                bufs: List[bytearray] = []
                for j, path in enumerate(batch):
                    fd = os.open(path, os.O_RDONLY)
                    fds.append(fd)
                    b = bytearray(file_size)
                    bufs.append(b)
                    ctx.read_async(fd, b, offset=0, user_data=j)
                ctx.submit()
                for _ in range(len(batch)):
                    ud, n = ctx.wait_completion()
                    if n < 0:
                        raise UringError(-n, "numpy_uring")
                    arr = np.frombuffer(bufs[ud], dtype=np.uint8, count=n)
                    int(arr.sum())
                for fd in fds:
                    os.close(fd)
                i += URING_BATCH
        return time.perf_counter() - t0

    times = [run() for _ in range(REPEATS)]
    return _mib_s(total, statistics.median(times))


async def bench_asyncio_gather_executor(paths: List[str]) -> float:
    """run_in_executor per file, asyncio.gather — 'before' asyncio style for many files."""
    total = sum(os.path.getsize(p) for p in paths)
    loop = asyncio.get_running_loop()

    async def read_path(p: str) -> bytes:
        return await loop.run_in_executor(
            None, lambda: open(p, "rb").read()
        )

    async def run_once() -> float:
        t0 = time.perf_counter()
        await asyncio.gather(*[read_path(p) for p in paths])
        return time.perf_counter() - t0

    times = []
    for _ in range(REPEATS):
        times.append(await run_once())
    return _mib_s(total, statistics.median(times))


async def bench_asyncio_uring(paths: List[str]) -> float:
    """Batched read_async + await UringAsync.wait_completion (same pattern as examples/asyncio/after)."""
    total = sum(os.path.getsize(p) for p in paths)
    file_size = os.path.getsize(paths[0])

    async def run_once() -> float:
        t0 = time.perf_counter()
        ctx = UringCtx(entries=max(URING_BATCH, 64))
        ua = UringAsync(ctx)
        try:
            i = 0
            while i < len(paths):
                batch = paths[i : i + URING_BATCH]
                fds = []
                bufs = []
                for j, path in enumerate(batch):
                    fd = os.open(path, os.O_RDONLY)
                    fds.append(fd)
                    b = bytearray(file_size)
                    bufs.append(b)
                    ctx.read_async(fd, b, offset=0, user_data=j)
                ctx.submit()
                for _ in range(len(batch)):
                    _ud, n = await ua.wait_completion()
                    if n < 0:
                        raise UringError(-n, "async_uring")
                for fd in fds:
                    os.close(fd)
                i += URING_BATCH
        finally:
            ua.close()
            ctx.close()
        return time.perf_counter() - t0

    times = []
    for _ in range(REPEATS):
        times.append(await run_once())
    return _mib_s(total, statistics.median(times))


def write_svg(
    path: Path,
    title: str,
    subtitle: str,
    before: float,
    pyuring: float,
) -> None:
    if pyuring < before * 0.98:
        raise SystemExit(
            f"{path.name}: pyuring ({pyuring:.1f}) < before ({before:.1f}) — "
            "tune SHARDS/SHARD_KB in this script or hardware differs too much."
        )
    ymax = max(before, pyuring) * 1.15
    step = 500 if ymax > 2000 else 200 if ymax > 500 else 100
    ymax = ((int(ymax / step) + 1) * step)
    plot_h = 168.0
    y0 = 240.0

    def bar_yh(val: float) -> Tuple[float, float]:
        h = val / ymax * plot_h
        return y0 - h, h

    yb, hb = bar_yh(before)
    yu, hu = bar_yh(pyuring)

    def fmt(v: float) -> str:
        return f"{v:.0f}"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="520" height="300" viewBox="0 0 520 300">
  <defs>
    <style>
      .title {{ font: 600 15px ui-sans-serif, system-ui, sans-serif; fill: #1a1a1a; }}
      .label {{ font: 13px ui-sans-serif, system-ui, sans-serif; fill: #333; }}
      .note {{ font: 11px ui-sans-serif, system-ui, sans-serif; fill: #666; }}
      .axis {{ stroke: #ccc; stroke-width: 1; }}
      .bar-before {{ fill: #8a8a8a; }}
      .bar-pyuring {{ fill: #2d6a4f; }}
    </style>
  </defs>
  <text x="260" y="24" text-anchor="middle" class="title">{title}</text>
  <text x="260" y="42" text-anchor="middle" class="note">{subtitle}</text>
  <line x1="78" y1="{y0}" x2="78" y2="72" class="axis"/>
  <line x1="78" y1="{y0}" x2="472" y2="{y0}" class="axis"/>
  <text x="68" y="244" text-anchor="end" class="label">0</text>
  <text x="68" y="158" text-anchor="end" class="label">{ymax/2:.0f}</text>
  <text x="68" y="72" text-anchor="end" class="label">{ymax:.0f}</text>
  <text x="38" y="158" text-anchor="middle" class="label" transform="rotate(-90 38 158)">MiB/s</text>
  <rect x="124" y="{yb:.1f}" width="92" height="{hb:.1f}" class="bar-before"/>
  <text x="170" y="{yb - 6:.1f}" text-anchor="middle" class="label">{fmt(before)}</text>
  <rect x="284" y="{yu:.1f}" width="92" height="{hu:.1f}" class="bar-pyuring"/>
  <text x="330" y="{yu - 6:.1f}" text-anchor="middle" class="label">{fmt(pyuring)}</text>
  <text x="170" y="268" text-anchor="middle" class="label">before</text>
  <text x="330" y="268" text-anchor="middle" class="label">pyuring</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    out = REPO / "docs" / "graphs"
    out.mkdir(parents=True, exist_ok=True)

    try:
        import numpy  # noqa: F401
    except ImportError:
        raise SystemExit(
            "numpy is required to generate graphs: pip install numpy"
        ) from None

    with tempfile.TemporaryDirectory(prefix="pyuring_ex_") as tmp:
        paths = create_shards(tmp, SHARDS, SHARD_KB)

        b_tp = bench_threadpool(paths)
        b_iou = bench_uring_batched(paths)

        b_gath = asyncio.run(bench_asyncio_gather_executor(paths))
        b_async_iou = asyncio.run(bench_asyncio_uring(paths))

    with tempfile.TemporaryDirectory(prefix="pyuring_fa_") as tmp_fa:
        paths_fa = create_shards(tmp_fa, SHARDS_FASTAPI, SHARD_KB)
        b_fa_b = bench_threadpool(paths_fa)
        b_fa_p = bench_uring_batched(paths_fa)

    with tempfile.TemporaryDirectory(prefix="pyuring_np_") as tmp_np:
        paths_np = create_numpy_shards(tmp_np, SHARDS_NUMPY, SHARD_KB)
        b_np_b = bench_numpy_threadpool(paths_np)
        b_np_u = bench_numpy_uring_batched(paths_np)

    with tempfile.TemporaryDirectory(prefix="pyuring_cr_") as tmp_cr:
        paths_cr = write_blob_and_split_parts(tmp_cr, SHARDS_CACHED, CACHED_CHUNK_KB)
        assert len(paths_cr) == SHARDS_CACHED
        b_cr_b = bench_threadpool(paths_cr)
        b_cr_u = bench_uring_batched(paths_cr)

    with tempfile.TemporaryDirectory(prefix="pyuring_sq_") as tmp_sq:
        paths_sq = create_shards_sqlite_names(tmp_sq, SHARDS_SQLITE, SHARD_KB)
        b_sq_b = bench_threadpool(paths_sq)
        b_sq_u = bench_uring_batched(paths_sq)

    print(f"pytorch-style:   before={b_tp:.1f}  pyuring={b_iou:.1f} MiB/s")
    print(f"asyncio gather:  before={b_gath:.1f}  pyuring={b_async_iou:.1f} MiB/s")
    print(f"fastapi (batch): before={b_fa_b:.1f}  pyuring={b_fa_p:.1f} MiB/s")
    print(f"numpy_bins:      before={b_np_b:.1f}  pyuring={b_np_u:.1f} MiB/s")
    print(f"cached_reads:    before={b_cr_b:.1f}  pyuring={b_cr_u:.1f} MiB/s")
    print(f"sqlite_blobs:    before={b_sq_b:.1f}  pyuring={b_sq_u:.1f} MiB/s")

    sub = f"{SHARDS} x {SHARD_KB} KiB; median {REPEATS} runs; before=ThreadPool({TP_WORKERS})"
    sub_fa = f"{SHARDS_FASTAPI} x {SHARD_KB} KiB; median {REPEATS} runs; before=ThreadPool({TP_WORKERS})"
    sub_np = (
        f"{SHARDS_NUMPY} x {SHARD_KB} KiB np.tofile shards; median {REPEATS} runs; "
        f"before=np.fromfile+ThreadPool({TP_WORKERS})"
    )
    sub_cr = (
        f"blob split into {SHARDS_CACHED} x {CACHED_CHUNK_KB} KiB parts; median {REPEATS} runs; "
        f"before=ThreadPool({TP_WORKERS})"
    )
    sub_sq = (
        f"{SHARDS_SQLITE} x {SHARD_KB} KiB shard_*.bin; median {REPEATS} runs; "
        f"before=ThreadPool({TP_WORKERS})"
    )

    write_svg(
        out / "example_pytorch_shards.svg",
        "examples/pytorch — many shard files",
        sub,
        b_tp,
        b_iou,
    )
    write_svg(
        out / "example_asyncio_many_files.svg",
        "examples/asyncio — many files (gather+executor vs batched UringAsync)",
        sub.replace("ThreadPool", "asyncio.gather + ThreadPoolExecutor per file"),
        b_gath,
        b_async_iou,
    )
    write_svg(
        out / "example_fastapi_many_reads.svg",
        "examples/fastapi — many on-disk reads (thread pool vs io_uring)",
        sub_fa + "; models loading many small assets per request batch",
        b_fa_b,
        b_fa_p,
    )
    write_svg(
        out / "example_numpy_bins.svg",
        "examples/numpy_bins — np.fromfile + threads vs read_async + np.frombuffer",
        sub_np,
        b_np_b,
        b_np_u,
    )
    write_svg(
        out / "example_cached_reads.svg",
        "examples/cached_reads — split blob, many parts (thread pool vs io_uring)",
        sub_cr,
        b_cr_b,
        b_cr_u,
    )
    write_svg(
        out / "example_sqlite_blobs.svg",
        "examples/sqlite_blobs — many exported shard files (thread pool vs io_uring)",
        sub_sq,
        b_sq_b,
        b_sq_u,
    )

    print(f"Wrote SVGs under {out}")


if __name__ == "__main__":
    main()
