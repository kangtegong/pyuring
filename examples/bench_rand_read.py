import argparse
import os
import random
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
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            os.posix_fallocate(fd, 0, size)
        except (AttributeError, OSError):
            os.ftruncate(fd, size)
    finally:
        os.close(fd)


def maybe_drop_cache_for_file(fd: int, size: int) -> None:
    # Advisory; doesn't require sudo. Helps reduce page cache hits.
    try:
        os.posix_fadvise(fd, 0, size, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError):
        pass


def gen_offsets(file_size: int, block_size: int, reads: int, seed: int) -> list:
    rng = random.Random(seed)
    max_off = file_size - block_size
    return [rng.randrange(0, max_off + 1, block_size) for _ in range(reads)]


def bench_pread_random(path: str, file_size: int, block_size: int, reads: int, iters: int, seed: int) -> float:
    fd = os.open(path, os.O_RDONLY)
    try:
        offsets = gen_offsets(file_size, block_size, reads, seed)
        buf = bytearray(block_size)
        start = time.perf_counter()
        for i in range(iters):
            maybe_drop_cache_for_file(fd, file_size)
            for off in offsets:
                chunk = os.pread(fd, block_size, off)
                if not chunk:
                    break
                buf[: len(chunk)] = chunk
            # perturb seed slightly per-iter so readahead patterns don't dominate
            if i % 3 == 0:
                offsets = gen_offsets(file_size, block_size, reads, seed + i + 1)
        end = time.perf_counter()
        return end - start
    finally:
        os.close(fd)


def bench_iouring_random(path: str, file_size: int, block_size: int, reads: int, iters: int, seed: int) -> float:
    fd = os.open(path, os.O_RDONLY)
    try:
        offsets = gen_offsets(file_size, block_size, reads, seed)
        with UringCtx(entries=reads) as u:
            start = time.perf_counter()
            for i in range(iters):
                maybe_drop_cache_for_file(fd, file_size)
                _ = u.read_offsets(fd, block_size, offsets, offset_bytes=True)
                if i % 3 == 0:
                    offsets = gen_offsets(file_size, block_size, reads, seed + i + 1)
            end = time.perf_counter()
            return end - start
    finally:
        os.close(fd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="/tmp/iouring_rand_bench.dat")
    ap.add_argument("--size-mb", type=int, default=2048, help="file size used for random read benchmark")
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--reads", type=int, default=256, help="queue depth / random reads per iteration")
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    file_size = int(args.size_mb) * 1024 * 1024
    ensure_file(args.path, file_size)

    total_bytes = args.block_size * args.reads * args.iters

    # Warmup
    _ = bench_pread_random(args.path, file_size, args.block_size, min(args.reads, 32), 1, args.seed)
    _ = bench_iouring_random(args.path, file_size, args.block_size, min(args.reads, 32), 1, args.seed)

    t_pread = bench_pread_random(args.path, file_size, args.block_size, args.reads, args.iters, args.seed)
    t_uring = bench_iouring_random(args.path, file_size, args.block_size, args.reads, args.iters, args.seed)

    pread_mb_s = human_mb_per_s(total_bytes, t_pread)
    uring_mb_s = human_mb_per_s(total_bytes, t_uring)
    speedup = (uring_mb_s / pread_mb_s) if pread_mb_s > 0 else 0.0

    print("### random 4k read benchmark (tries to reduce page cache hits with POSIX_FADV_DONTNEED)")
    print(
        f"path={args.path} size={args.size_mb}MB block_size={args.block_size} reads={args.reads} iters={args.iters}"
    )
    print(f"python os.pread loop : {t_pread:.4f}s  {pread_mb_s:.2f} MiB/s")
    print(f"io_uring QD={args.reads}   : {t_uring:.4f}s  {uring_mb_s:.2f} MiB/s")
    print(f"speedup             : {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


