import argparse
import os
import time

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import UringCtx


def human_mb_per_s(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return (nbytes / (1024 * 1024)) / seconds


def ensure_file(path: str, size: int) -> None:
    # Create a file of 'size' bytes (prefer preallocation to avoid sparse holes).
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            os.posix_fallocate(fd, 0, size)
        except (AttributeError, OSError):
            os.ftruncate(fd, size)
    finally:
        os.close(fd)


def bench_pread_loop(path: str, block_size: int, blocks: int, iters: int) -> float:
    fd = os.open(path, os.O_RDONLY)
    try:
        buf = bytearray(block_size * blocks)
        start = time.perf_counter()
        for _ in range(iters):
            off = 0
            for i in range(blocks):
                chunk = os.pread(fd, block_size, off)
                if not chunk:
                    break
                buf[i * block_size : i * block_size + len(chunk)] = chunk
                off += block_size
        end = time.perf_counter()
        return end - start
    finally:
        os.close(fd)


def bench_iouring_batch(path: str, block_size: int, blocks: int, iters: int) -> float:
    fd = os.open(path, os.O_RDONLY)
    try:
        with UringCtx(entries=blocks) as u:
            start = time.perf_counter()
            for _ in range(iters):
                _ = u.read_batch(fd, block_size=block_size, blocks=blocks, offset=0)
            end = time.perf_counter()
            return end - start
    finally:
        os.close(fd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="/tmp/iouring_bench.dat")
    ap.add_argument("--size-mb", type=int, default=256, help="file size used for read benchmark")
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--blocks", type=int, default=4096, help="number of blocks per iteration")
    ap.add_argument("--iters", type=int, default=20)
    args = ap.parse_args()

    size = int(args.size_mb) * 1024 * 1024
    ensure_file(args.path, size)

    total_bytes = args.block_size * args.blocks * args.iters

    # Warmup (touch the file, reduce first-run effects)
    _ = bench_pread_loop(args.path, args.block_size, min(args.blocks, 128), 1)
    _ = bench_iouring_batch(args.path, args.block_size, min(args.blocks, 128), 1)

    t_pread = bench_pread_loop(args.path, args.block_size, args.blocks, args.iters)
    t_uring = bench_iouring_batch(args.path, args.block_size, args.blocks, args.iters)

    pread_mb_s = human_mb_per_s(total_bytes, t_pread)
    uring_mb_s = human_mb_per_s(total_bytes, t_uring)
    speedup = (uring_mb_s / pread_mb_s) if pread_mb_s > 0 else 0.0

    print("### read benchmark (cached IO; measures userspace/syscall overhead heavily)")
    print(f"path={args.path} size={args.size_mb}MB block_size={args.block_size} blocks={args.blocks} iters={args.iters}")
    print(f"python os.pread loop : {t_pread:.4f}s  {pread_mb_s:.2f} MiB/s")
    print(f"io_uring batch (C)  : {t_uring:.4f}s  {uring_mb_s:.2f} MiB/s")
    print(f"speedup             : {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


