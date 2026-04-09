#!/usr/bin/env python3
"""
Benchmark the three examples (asyncio, fastapi, pytorch) and write one SVG each.

    PYTHONPATH=. python3 examples/graphs/bench_charts.py

Needs: fastapi + starlette (TestClient) for the FastAPI chart.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple

from pyuring import UringAsync, UringCtx, UringError

REPO = Path(__file__).resolve().parents[2]
GRAPHS = Path(__file__).resolve().parent

# --- asyncio (examples/asyncio/before vs after) ---
ASYNCIO_MIB = 32
# --- fastapi: TestClient GET /payload (examples/fastapi/*) ---
# --- pytorch-style shards ---
SHARD_COUNT = 128
SHARD_KB = 64
THREAD_WORKERS = 8
URING_BATCH = 32

REPEATS = 7


def _mib_s(total_bytes: int, elapsed_s: float) -> float:
    if elapsed_s <= 0:
        return 0.0
    return total_bytes / elapsed_s / (1024 * 1024)


def _nice_ymax(a: float, b: float) -> float:
    m = max(a, b) * 1.12
    if m <= 0:
        return 1.0
    step = 200.0 if m > 2000 else 100.0 if m > 500 else 50.0 if m > 100 else 20.0
    return ((int(m / step) + 1) * step)


async def _read_executor(path: str) -> None:
    loop = asyncio.get_running_loop()

    def _r() -> None:
        with open(path, "rb") as f:
            f.read()

    await loop.run_in_executor(None, _r)


async def _read_uring(path: str, ctx: UringCtx, ua: UringAsync) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        if size == 0:
            return
        block = min(size, 64 * 1024)
        nblocks = (size + block - 1) // block
        bufs: list[bytearray] = []
        for i in range(nblocks):
            off = i * block
            ln = min(block, size - off)
            b = bytearray(ln)
            bufs.append(b)
            ctx.read_async(fd, b, offset=off, user_data=i)
        ctx.submit()
        got: dict[int, int] = {}
        for _ in range(nblocks):
            ud, n = await ua.wait_completion()
            if n < 0:
                raise UringError(-n, "bench_asyncio_uring")
            got[ud] = n
    finally:
        os.close(fd)


def bench_asyncio() -> Tuple[float, float, int]:
    nbytes = ASYNCIO_MIB * 1024 * 1024

    async def _measure() -> Tuple[List[float], List[float]]:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(bytes(i % 256 for i in range(nbytes)))
            path = f.name
        try:
            ex_t: List[float] = []
            ur_t: List[float] = []
            for _ in range(REPEATS):
                t0 = time.perf_counter()
                await _read_executor(path)
                ex_t.append(time.perf_counter() - t0)
            for _ in range(REPEATS):
                ctx = UringCtx(entries=64)
                ua = UringAsync(ctx)
                try:
                    t0 = time.perf_counter()
                    await _read_uring(path, ctx, ua)
                    ur_t.append(time.perf_counter() - t0)
                finally:
                    ua.close()
                    ctx.close()
            return ex_t, ur_t
        finally:
            os.unlink(path)

    ex_t, ur_t = asyncio.run(_measure())
    return (
        _mib_s(nbytes, statistics.median(ex_t)),
        _mib_s(nbytes, statistics.median(ur_t)),
        nbytes,
    )


def _load_fastapi_app(which: str):
    sys.path.insert(0, str(REPO))
    path = REPO / "examples" / "fastapi" / which / "main.py"
    name = f"fastapi_{which}_main"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def bench_fastapi() -> Tuple[float, float, int]:
    from starlette.testclient import TestClient

    before_app = _load_fastapi_app("before")
    after_app = _load_fastapi_app("after")
    with TestClient(before_app) as cb, TestClient(after_app) as ca:
        for _ in range(3):
            cb.get("/payload")
            ca.get("/payload")
        n = cb.get("/payload").json()["bytes"]
        assert ca.get("/payload").json()["bytes"] == n

        tb: List[float] = []
        ta: List[float] = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            cb.get("/payload")
            tb.append(time.perf_counter() - t0)
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            ca.get("/payload")
            ta.append(time.perf_counter() - t0)

    mb = statistics.median(tb)
    ma = statistics.median(ta)
    return _mib_s(n, mb), _mib_s(n, ma), n


def create_shards(tmpdir: str, n: int, size_kb: int) -> List[str]:
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"shard_{i:04d}.bin")
        with open(p, "wb") as f:
            f.write(bytes([i & 0xFF]) * (size_kb * 1024))
        paths.append(p)
    return paths


def read_one(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def bench_pytorch_shards(paths: List[str]) -> Tuple[float, float]:
    total = sum(os.path.getsize(p) for p in paths)

    def run_tp() -> float:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=THREAD_WORKERS) as ex:
            list(ex.map(read_one, paths))
        return time.perf_counter() - t0

    def run_uring() -> float:
        file_size = os.path.getsize(paths[0])
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
                        raise UringError(-n, "bench_shards")
                for fd in fds:
                    os.close(fd)
                i += URING_BATCH
        return time.perf_counter() - t0

    tp_times = [run_tp() for _ in range(REPEATS)]
    ur_times = [run_uring() for _ in range(REPEATS)]
    return _mib_s(total, statistics.median(tp_times)), _mib_s(total, statistics.median(ur_times))


def write_svg_mib(
    path: Path,
    title: str,
    subtitle: str,
    before: float,
    pyuring: float,
) -> None:
    ymax = _nice_ymax(before, pyuring)
    plot_h = 168.0
    y0 = 240.0
    x_axis = 78.0

    def bar_yh(val: float) -> Tuple[float, float]:
        h = val / ymax * plot_h
        return y0 - h, h

    yb, hb = bar_yh(before)
    yu, hu = bar_yh(pyuring)

    def fmt(v: float) -> str:
        return f"{v:.0f}" if v >= 100 else f"{v:.1f}"

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
  <line x1="{x_axis}" y1="{y0}" x2="{x_axis}" y2="72" class="axis"/>
  <line x1="{x_axis}" y1="{y0}" x2="472" y2="{y0}" class="axis"/>
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
    a_b, a_p, _ = bench_asyncio()
    print(f"asyncio/   (single file {ASYNCIO_MIB} MiB read):  before={a_b:.1f}  pyuring={a_p:.1f} MiB/s")

    f_b, f_p, fn = bench_fastapi()
    print(f"fastapi/   (GET /payload, {fn // (1024*1024)} MiB body read): before={f_b:.1f}  pyuring={f_p:.1f} MiB/s")

    with tempfile.TemporaryDirectory(prefix="pyuring_bench_") as d:
        paths = create_shards(d, SHARD_COUNT, SHARD_KB)
        p_b, p_p = bench_pytorch_shards(paths)
    print(f"pytorch/   ({SHARD_COUNT} x {SHARD_KB} KiB shards): before={p_b:.1f}  pyuring={p_p:.1f} MiB/s")

    write_svg_mib(
        GRAPHS / "asyncio_read_mib_s.svg",
        "examples/asyncio — one async file read",
        f"run_in_executor vs UringAsync; file {ASYNCIO_MIB} MiB; median of {REPEATS} reads",
        a_b,
        a_p,
    )
    write_svg_mib(
        GRAPHS / "fastapi_payload_mib_s.svg",
        "examples/fastapi — GET /payload reads disk",
        f"Starlette TestClient median latency; payload {fn // (1024*1024)} MiB; {REPEATS} requests",
        f_b,
        f_p,
    )
    write_svg_mib(
        GRAPHS / "pytorch_shards_mib_s.svg",
        "examples/pytorch — many shard files",
        f"ThreadPoolExecutor ({THREAD_WORKERS} workers) vs io_uring batch {URING_BATCH}; {SHARD_COUNT} x {SHARD_KB} KiB",
        p_b,
        p_p,
    )
    print(f"Wrote SVGs under {GRAPHS}")


if __name__ == "__main__":
    main()
