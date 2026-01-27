import argparse
import os
import statistics
import time


def mb_s(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return (nbytes / (1024 * 1024)) / seconds


def python_write_loop(path: str, total_mb: int, block_size: int, *, fdatasync: bool) -> int:
    total = total_mb * 1024 * 1024
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    try:
        block = b"A" * block_size
        left = total
        while left > 0:
            n = block_size if left >= block_size else left
            os.write(fd, block[:n])
            left -= n
        if fdatasync:
            os.fdatasync(fd)
        return total
    finally:
        os.close(fd)


def python_writev(path: str, total_mb: int, block_size: int, *, vec: int, fdatasync: bool) -> int:
    total = total_mb * 1024 * 1024
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    try:
        block = b"A" * block_size
        full_batches = total // (block_size * vec)
        leftover = total - (full_batches * block_size * vec)

        iov = [block] * vec
        for _ in range(full_batches):
            os.writev(fd, iov)

        # leftover blocks
        while leftover > 0:
            nblocks = min(vec, leftover // block_size)
            if nblocks:
                os.writev(fd, iov[:nblocks])
                leftover -= nblocks * block_size
            else:
                os.write(fd, block[:leftover])
                leftover = 0

        if fdatasync:
            os.fdatasync(fd)
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
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--vec", type=int, default=64, help="iovecs per writev() call")
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--fdatasync", action="store_true", help="include fdatasync() at end (durability)")
    args = ap.parse_args()

    total_bytes = args.total_mb * 1024 * 1024
    repeats = max(1, int(args.repeats))

    p_loop = os.path.join(args.dir, "newfile_write_loop.dat")
    p_writev = os.path.join(args.dir, "newfile_writev.dat")

    # Warmup
    python_write_loop(p_loop, total_mb=min(args.total_mb, 64), block_size=args.block_size, fdatasync=args.fdatasync)
    python_writev(
        p_writev,
        total_mb=min(args.total_mb, 64),
        block_size=args.block_size,
        vec=args.vec,
        fdatasync=args.fdatasync,
    )

    loop_secs = []
    writev_secs = []

    for _ in range(repeats):
        n0, s0 = timed(
            python_write_loop, p_loop, args.total_mb, args.block_size, fdatasync=args.fdatasync
        )
        n1, s1 = timed(
            python_writev, p_writev, args.total_mb, args.block_size, vec=args.vec, fdatasync=args.fdatasync
        )
        if n0 != total_bytes or n1 != total_bytes:
            raise SystemExit(f"size mismatch: n0={n0} n1={n1} total={total_bytes}")
        loop_secs.append(s0)
        writev_secs.append(s1)

    def summarize(label: str, secs):
        med = statistics.median(secs)
        avg = sum(secs) / len(secs)
        print(
            f"{label:24s}: median {med:.4f}s  {mb_s(total_bytes, med):.2f} MiB/s | avg {avg:.4f}s  {mb_s(total_bytes, avg):.2f} MiB/s"
        )

    print("### new-file write benchmark (many small writes) - syscall batching with writev")
    print(
        f"dir={args.dir} total={args.total_mb}MB block_size={args.block_size} vec={args.vec} repeats={repeats} fdatasync={args.fdatasync}"
    )
    summarize("python os.write loop", loop_secs)
    summarize("python os.writev", writev_secs)
    speedup = (statistics.median(loop_secs) / statistics.median(writev_secs)) if statistics.median(writev_secs) > 0 else 0.0
    print(f"speedup writev vs loop     : {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


