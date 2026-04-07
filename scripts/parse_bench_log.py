#!/usr/bin/env python3
"""Parse bench_async_vs_sync.py stdout; emit JSON for plotting."""
from __future__ import annotations

import json
import re
import sys


def main() -> None:
    text = sys.stdin.read()
    out: dict = {"raw": text, "rows": []}

    # Matches both single-run and "Avg" tables, e.g.:
    # Sync Write           0.1720             581.51               1.00x
    # Async Write          0.1260             793.71               1.36           x
    pat = re.compile(
        r"^(Sync Write|Async Write|Sync Read|Async Read)\s+"
        r"([\d.]+)\s+"
        r"([\d.]+)\s+"
        r"([\d.]+)\s*x\s*$",
        re.MULTILINE,
    )
    for m in pat.finditer(text):
        name, tsec, mbs, speedup = m.groups()
        out["rows"].append(
            {
                "operation": name.strip(),
                "time_s": float(tsec),
                "throughput_mbps": float(mbs),
                "speedup_vs_sync": float(speedup) if name.startswith("Async") else 1.0,
            }
        )

    json.dump(out, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
