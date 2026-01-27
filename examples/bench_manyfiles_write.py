import argparse
import os
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import write_manyfiles


def mb_s(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return (nbytes / (1024 * 1024)) / seconds


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    ret = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return ret, (t1 - t0)


def prep_dir(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def python_threadpool_write(dir_path: str, nfiles: int, mb_per_file: int, block_size: int, workers: int) -> int:
    total_bytes = nfiles * mb_per_file * 1024 * 1024

    def write_one(i: int) -> int:
        p = os.path.join(dir_path, f"file_{i:06d}.dat")
        fd = os.open(p, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
        try:
            target = mb_per_file * 1024 * 1024
            block = (bytes([65 + (i % 26)]) * block_size)
            left = target
            while left > 0:
                n = block_size if left >= block_size else left
                os.write(fd, block[:n])
                left -= n
            return target
        finally:
            os.close(fd)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        s = sum(ex.map(write_one, range(nfiles)))
    if s != total_bytes:
        raise RuntimeError(f"size mismatch: {s} != {total_bytes}")
    return s


def python_writev_write(dir_path: str, nfiles: int, mb_per_file: int, block_size: int, vec: int) -> int:
    total_bytes = nfiles * mb_per_file * 1024 * 1024
    iov = [b"A" * block_size] * vec

    total = 0
    for i in range(nfiles):
        p = os.path.join(dir_path, f"file_{i:06d}.dat")
        fd = os.open(p, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
        try:
            target = mb_per_file * 1024 * 1024
            full_batches = target // (block_size * vec)
            leftover = target - (full_batches * block_size * vec)

            for _ in range(full_batches):
                os.writev(fd, iov)

            while leftover > 0:
                nblocks = min(vec, leftover // block_size)
                if nblocks:
                    os.writev(fd, iov[:nblocks])
                    leftover -= nblocks * block_size
                else:
                    os.write(fd, b"A" * leftover)
                    leftover = 0

            total += target
        finally:
            os.close(fd)

    if total != total_bytes:
        raise RuntimeError(f"size mismatch: {total} != {total_bytes}")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/iouring_manyfiles")
    ap.add_argument("--nfiles", type=int, default=64)
    ap.add_argument("--mb-per-file", type=int, default=16)
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--qd", type=int, default=256)
    ap.add_argument("--vec", type=int, default=64)
    ap.add_argument("--workers", type=int, default=16, help="threadpool workers for 'aio' baseline")
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    repeats = max(1, int(args.repeats))
    total_bytes = args.nfiles * args.mb_per_file * 1024 * 1024

    aio_secs = []
    writev_secs = []
    uring_secs = []

    # Warmup
    prep_dir(args.dir)
    _ = python_threadpool_write(args.dir, min(args.nfiles, 8), min(args.mb_per_file, 4), args.block_size, args.workers)
    prep_dir(args.dir)
    _ = python_writev_write(args.dir, min(args.nfiles, 8), min(args.mb_per_file, 4), args.block_size, args.vec)
    prep_dir(args.dir)
    _ = write_manyfiles(args.dir, nfiles=min(args.nfiles, 8), mb_per_file=min(args.mb_per_file, 4), block_size=args.block_size, qd=args.qd)

    for _ in range(repeats):
        prep_dir(args.dir)
        _, s0 = timed(python_threadpool_write, args.dir, args.nfiles, args.mb_per_file, args.block_size, args.workers)
        prep_dir(args.dir)
        _, s1 = timed(python_writev_write, args.dir, args.nfiles, args.mb_per_file, args.block_size, args.vec)
        prep_dir(args.dir)
        _, s2 = timed(write_manyfiles, args.dir, nfiles=args.nfiles, mb_per_file=args.mb_per_file, block_size=args.block_size, qd=args.qd)

        aio_secs.append(s0)
        writev_secs.append(s1)
        uring_secs.append(s2)

    def summarize(label: str, secs):
        med = statistics.median(secs)
        avg = sum(secs) / len(secs)
        print(
            f"{label:22s}: median {med:.4f}s  {mb_s(total_bytes, med):.2f} MiB/s | avg {avg:.4f}s  {mb_s(total_bytes, avg):.2f} MiB/s"
        )

    print("### many-files write benchmark (new files, many small writes)")
    print(
        f"dir={args.dir} nfiles={args.nfiles} mb_per_file={args.mb_per_file} total={total_bytes/(1024*1024):.0f}MB "
        f"block_size={args.block_size} qd={args.qd} vec={args.vec} workers={args.workers} repeats={repeats}"
    )
    summarize("aio (threadpool)", aio_secs)
    summarize("os.writev", writev_secs)
    summarize("io_uring (C)", uring_secs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


