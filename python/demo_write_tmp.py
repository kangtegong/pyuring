import os
import tempfile

try:
    # When executed as a module: `python3 -m python.demo_write_tmp`
    from .uringwrap import UringCtx  # type: ignore
except ImportError:
    # When executed as a script: `python3 python/demo_write_tmp.py`
    from uringwrap import UringCtx


def main() -> int:
    payload = b"hello from io_uring via python ctypes\n"
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.txt")
        fd = os.open(out_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
        try:
            with UringCtx(entries=64) as u:
                n = u.write(fd, payload, offset=0)
            print(f"wrote {n} bytes via io_uring to {out_path}")
        finally:
            os.close(fd)

        with open(out_path, "rb") as f:
            got = f.read()
        print("file contents:", got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


