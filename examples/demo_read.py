import os
import sys

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import UringCtx


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


