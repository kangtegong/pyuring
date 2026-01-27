import argparse
import os
import statistics
import shutil
import time

from python.uringwrap import copy_path


def ensure_file(path: str, size_mb: int) -> None:
    size = size_mb * 1024 * 1024
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            os.posix_fallocate(fd, 0, size)
        except (AttributeError, OSError):
            os.ftruncate(fd, size)
    finally:
        os.close(fd)


def mb_s(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return (nbytes / (1024 * 1024)) / seconds


def python_naive_copy(src: str, dst: str, block_size: int) -> int:
    sfd = os.open(src, os.O_RDONLY)
    dfd = os.open(dst, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    try:
        total = 0
        while True:
            b = os.read(sfd, block_size)
            if not b:
                break
            os.write(dfd, b)
            total += len(b)
        return total
    finally:
        os.close(dfd)
        os.close(sfd)


def run_timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    ret = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return ret, (t1 - t0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/iouring_copy_src.dat")
    ap.add_argument("--dst-dir", default="/tmp")
    ap.add_argument("--size-mb", type=int, default=1024)
    ap.add_argument("--block-size", type=int, default=64 * 1024, help="block size for naive python copy")
    ap.add_argument("--qd", type=int, default=32)
    ap.add_argument("--uring-block-size", type=int, default=1 << 20)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    ensure_file(args.src, args.size_mb)
    total = os.stat(args.src).st_size

    dst_py = os.path.join(args.dst_dir, "dst_python_naive.dat")
    dst_shutil = os.path.join(args.dst_dir, "dst_shutil_copyfile.dat")
    dst_uring = os.path.join(args.dst_dir, "dst_iouring_copy.dat")

    repeats = max(1, int(args.repeats))

    py_secs = []
    shutil_secs = []
    uring_secs = []

    # Warmup
    _ = python_naive_copy(args.src, dst_py, args.block_size)
    shutil.copyfile(args.src, dst_shutil)
    _ = copy_path(args.src, dst_uring, qd=args.qd, block_size=args.uring_block_size)

    for _ in range(repeats):
        n0, s0 = run_timed(python_naive_copy, args.src, dst_py, args.block_size)
        _, s1 = run_timed(shutil.copyfile, args.src, dst_shutil)
        n2, s2 = run_timed(copy_path, args.src, dst_uring, qd=args.qd, block_size=args.uring_block_size)

        if n0 != total or n2 != total:
            raise SystemExit(f"copy size mismatch: total={total} n0={n0} n2={n2}")

        py_secs.append(s0)
        shutil_secs.append(s1)
        uring_secs.append(s2)

    def summarize(label: str, secs_list, nbytes: int):
        med = statistics.median(secs_list)
        avg = sum(secs_list) / len(secs_list)
        print(f"{label:24s}: median {med:.4f}s  {mb_s(nbytes, med):.2f} MiB/s | avg {avg:.4f}s  {mb_s(nbytes, avg):.2f} MiB/s")

    print("### copy benchmark")
    print(f"size={args.size_mb}MB src={args.src} repeats={repeats}")
    summarize("python naive (read/write)", py_secs, total)
    summarize("shutil.copyfile", shutil_secs, total)
    summarize(f"io_uring pipeline (C) qd={args.qd} bs={args.uring_block_size}", uring_secs, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


