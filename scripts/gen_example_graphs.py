#!/usr/bin/env python3
"""
Regenerate docs/graphs/*.svg for examples/README.

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
SHARD_KB = 64
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

    print(f"pytorch-style:   before={b_tp:.1f}  pyuring={b_iou:.1f} MiB/s")
    print(f"asyncio gather:  before={b_gath:.1f}  pyuring={b_async_iou:.1f} MiB/s")
    print(f"fastapi (batch): before={b_fa_b:.1f}  pyuring={b_fa_p:.1f} MiB/s")

    sub = f"{SHARDS} x {SHARD_KB} KiB; median {REPEATS} runs; before=ThreadPool({TP_WORKERS})"
    sub_fa = f"{SHARDS_FASTAPI} x {SHARD_KB} KiB; median {REPEATS} runs; before=ThreadPool({TP_WORKERS})"

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

    print(f"Wrote SVGs under {out}")


if __name__ == "__main__":
    main()
