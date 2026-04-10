#!/usr/bin/env python3
"""
One-time download or synthetic cache file for the cached_reads before/after demos.

  pip install requests tqdm urllib3

- Default: writes a local random file (no network) so examples work offline.
- Optional: ``--url`` uses ``requests`` with ``tqdm``; or ``--urllib3`` for the same URL via urllib3.
"""

from __future__ import annotations

import argparse
import os
import sys


def write_synthetic(path: str, mib: int) -> None:
    with open(path, "wb") as f:
        for _ in range(mib):
            f.write(os.urandom(1024 * 1024))


def download_requests(url: str, path: str) -> None:
    import requests
    from tqdm import tqdm

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        with open(path, "wb") as f, tqdm(
            total=total if total else None, unit="B", unit_scale=True, desc="requests"
        ) as bar:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))


def download_urllib3(url: str, path: str) -> None:
    import urllib3
    from tqdm import tqdm

    http = urllib3.PoolManager()
    r = http.request("GET", url, preload_content=False, timeout=60.0)
    if r.status >= 400:
        raise RuntimeError(f"HTTP {r.status}")
    try:
        cl = int(r.headers.get("content-length") or 0)
        with open(path, "wb") as f, tqdm(total=cl or None, unit="B", unit_scale=True, desc="urllib3") as bar:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                bar.update(len(chunk))
    finally:
        r.release_conn()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(__file__), "cached_blob.bin"),
        help="output path for the single large file to split in read demos",
    )
    ap.add_argument("--mib", type=int, default=8, help="synthetic file size when not using --url")
    ap.add_argument(
        "--url",
        help="if set, download this URL (e.g. a large static asset); else write random data",
    )
    ap.add_argument("--urllib3", action="store_true", help="use urllib3 instead of requests for --url")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    if args.url:
        if args.urllib3:
            download_urllib3(args.url, args.out)
        else:
            download_requests(args.url, args.out)
    else:
        write_synthetic(args.out, args.mib)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
