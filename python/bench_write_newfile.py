import argparse
import os
import statistics
import time

from python.uringwrap import write_newfile


def mb_s(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return (nbytes / (1024 * 1024)) / seconds


def python_naive_write(path: str, total_mb: int, block_size: int, fsync: bool) -> int:
    total = total_mb * 1024 * 1024
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    try:
        block = b"A" * block_size
        left = total
        while left > 0:
            n = block_size if left >= block_size else left
            os.write(fd, block[:n])
            left -= n
        if fsync:
            os.fsync(fd)
        return total
    finally:
        os.close(fd)


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    n = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return n, (t1 - t0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp")
    ap.add_argument("--total-mb", type=int, default=512)
    ap.add_argument("--block-size", type=int, default=4096, help="small write size for both tests")
    ap.add_argument("--qd", type=int, default=256)
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--fsync", action="store_true", help="include fsync in timing (slower, but real durability)")
    ap.add_argument("--dsync", action="store_true", help="sync each small write to disk (very slow for Python loop; shows QD benefit)")
    args = ap.parse_args()

    repeats = max(1, int(args.repeats))
    total_bytes = args.total_mb * 1024 * 1024

    p_py = os.path.join(args.dir, "newfile_python_naive.dat")
    p_uring = os.path.join(args.dir, "newfile_iouring.dat")

    def python_writer():
        flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY
        if args.dsync:
            flags |= os.O_DSYNC
        total = args.total_mb * 1024 * 1024
        fd = os.open(p_py, flags, 0o644)
        try:
            block = b"A" * args.block_size
            left = total
            while left > 0:
                n = args.block_size if left >= args.block_size else left
                os.write(fd, block[:n])
                left -= n
            if args.fsync:
                os.fsync(fd)
            return total
        finally:
            os.close(fd)

    # Warmup
    _ = python_writer()
    write_newfile(
        p_uring,
        total_mb=min(args.total_mb, 64),
        block_size=args.block_size,
        qd=args.qd,
        fsync=args.fsync,
        dsync=args.dsync,
    )

    py_secs = []
    uring_secs = []

    for _ in range(repeats):
        n0, s0 = timed(python_writer)
        n1, s1 = timed(
            write_newfile,
            p_uring,
            total_mb=args.total_mb,
            block_size=args.block_size,
            qd=args.qd,
            fsync=args.fsync,
            dsync=args.dsync,
        )
        if n0 != total_bytes or n1 != total_bytes:
            raise SystemExit(f"size mismatch: n0={n0} n1={n1} total={total_bytes}")
        py_secs.append(s0)
        uring_secs.append(s1)

    def summarize(label: str, secs):
        med = statistics.median(secs)
        avg = sum(secs) / len(secs)
        print(
            f"{label:26s}: median {med:.4f}s  {mb_s(total_bytes, med):.2f} MiB/s | avg {avg:.4f}s  {mb_s(total_bytes, avg):.2f} MiB/s"
        )

    print("### new-file write benchmark (many small writes)")
    print(
        f"dir={args.dir} total={args.total_mb}MB block_size={args.block_size} qd={args.qd} repeats={repeats} fsync={args.fsync}"
    )
    summarize("python naive os.write loop", py_secs)
    summarize("io_uring C pipeline", uring_secs)
    speedup = (statistics.median(py_secs) / statistics.median(uring_secs)) if statistics.median(uring_secs) > 0 else 0.0
    print(f"speedup (median)           : {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


