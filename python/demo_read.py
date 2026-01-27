import os
import sys

try:
    # When executed as a module: `python3 -m python.demo_read ...`
    from .uringwrap import UringCtx  # type: ignore
except ImportError:
    # When executed as a script: `python3 python/demo_read.py ...`
    from uringwrap import UringCtx


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <path> [nbytes]")
        return 2

    path = sys.argv[1]
    nbytes = int(sys.argv[2]) if len(sys.argv) >= 3 else 4096

    fd = os.open(path, os.O_RDONLY)
    try:
        with UringCtx(entries=64) as u:
            data = u.read(fd, nbytes, offset=0)
            print(f"read {len(data)} bytes via io_uring from {path!r}")
            print(data[: min(len(data), 128)])
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


