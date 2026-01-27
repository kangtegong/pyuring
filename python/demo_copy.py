import argparse
import os
import time

from python.uringwrap import copy_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--qd", type=int, default=32)
    ap.add_argument("--block-size", type=int, default=1 << 20)
    args = ap.parse_args()

    t0 = time.perf_counter()
    n = copy_path(args.src, args.dst, qd=args.qd, block_size=args.block_size)
    t1 = time.perf_counter()
    mb_s = (n / (1024 * 1024)) / (t1 - t0) if (t1 - t0) > 0 else 0.0

    print(f"copied {n} bytes in {t1 - t0:.4f}s ({mb_s:.2f} MiB/s)")
    print("dst size:", os.stat(args.dst).st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


