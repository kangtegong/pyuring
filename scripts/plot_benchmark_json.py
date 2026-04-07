#!/usr/bin/env python3
"""Plot benchmark JSON (time bars + speedup) to PNG."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if len(rows) < 4:
        print("need 4 rows in JSON", file=sys.stderr)
        sys.exit(1)

    labels = ["Write", "Read"]
    sync_t = [
        next(r["time_s"] for r in rows if r["operation"] == "Sync Write"),
        next(r["time_s"] for r in rows if r["operation"] == "Sync Read"),
    ]
    async_t = [
        next(r["time_s"] for r in rows if r["operation"] == "Async Write"),
        next(r["time_s"] for r in rows if r["operation"] == "Async Read"),
    ]
    speedups = [s / a for s, a in zip(sync_t, async_t)]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    x = range(len(labels))
    w = 0.35
    axes[0].bar([i - w / 2 for i in x], sync_t, width=w, label="Blocking I/O (os.read/os.write)", color="#334155")
    axes[0].bar([i + w / 2 for i in x], async_t, width=w, label="pyuring (io_uring)", color="#0ea5e9")
    axes[0].set_xticks(list(x))
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("Time (seconds)")
    axes[0].set_title("Lower is better")
    axes[0].legend(fontsize=8)

    axes[1].bar(labels, speedups, color="#22c55e")
    axes[1].axhline(1.0, color="#94a3b8", linestyle="--")
    axes[1].set_ylabel("Speedup (×)")
    axes[1].set_title("pyuring / blocking")

    fig.suptitle("pyuring vs blocking Python file I/O (same workload in bench_async_vs_sync.py)")
    fig.tight_layout()
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
