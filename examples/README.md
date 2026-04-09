# Examples

`before/` = idiomatic Python, `after/` = pyuring. Linux only.

## What each does

Each folder is the same scenario twice: **`before/`** uses a common Python pattern, **`after/`** uses pyuring.

### `asyncio/`

**Code sample:** read **one file** from a coroutine — `run_in_executor` vs `UringAsync` (good for learning the API).

**Throughput:** pyuring shines when you **batch many reads** through one ring (see chart below). The tiny one-file demos are for clarity, not peak MiB/s.

### `fastapi/`

**Code sample:** `GET /payload` reads **one** payload file — executor vs ring in **`lifespan`**. Ports **8765** / **8766**.

**Throughput:** serving or aggregating **many** file reads per burst (static assets, shards) is where io_uring batching pays off; the chart uses a **multi-file** read pattern to show that.

### `pytorch/`

**Workload:** **many** equal-sized shard files — `ThreadPoolExecutor` vs batched `read_async`. No `torch` import; it is the same I/O shape as DataLoader-style prefetch.

---

## Charts (multi-file workloads — pyuring ahead here)

Charts are **not** the one-file demos above: they measure **many files per run** (thread pool / `asyncio.gather` vs batched io_uring). That is where syscall batching and the ring usually beat lots of thread wakeups.

Regenerate SVGs on your machine after changing hardware:

```bash
PYTHONPATH=. python3 scripts/gen_example_graphs.py
```

| File | Meaning |
|------|---------|
| [`docs/graphs/example_pytorch_shards.svg`](../docs/graphs/example_pytorch_shards.svg) | `examples/pytorch/` pattern: ThreadPoolExecutor vs batched `read_async`. |
| [`docs/graphs/example_asyncio_many_files.svg`](../docs/graphs/example_asyncio_many_files.svg) | Many files: `asyncio.gather` + `run_in_executor` per file vs batched `UringAsync`. |
| [`docs/graphs/example_fastapi_many_reads.svg`](../docs/graphs/example_fastapi_many_reads.svg) | Same class of **multi-file** read; models many small on-disk reads behind a handler. |

![pytorch](../docs/graphs/example_pytorch_shards.svg)
![asyncio](../docs/graphs/example_asyncio_many_files.svg)
![fastapi](../docs/graphs/example_fastapi_many_reads.svg)

**Why we don’t chart the one-file demos:** with a **warm page cache**, a single blocking `read()` in a thread can look faster in MiB/s than multi-completion io_uring — that does **not** mean pyuring is worse in general; it means that micro-benchmark is a poor fit. The charts above use workloads where **batching wins**.

## Run examples

```bash
export PYTHONPATH=.   # or: pip install -e .
python3 examples/asyncio/before/read_file.py
python3 examples/asyncio/after/read_file.py

pip install fastapi uvicorn
cd examples/fastapi/before && uvicorn main:app --host 127.0.0.1 --port 8765
cd examples/fastapi/after  && uvicorn main:app --host 127.0.0.1 --port 8766

python3 examples/pytorch/before/load_shards.py
python3 examples/pytorch/after/load_shards.py
```

More: [`docs/graphs/`](../docs/graphs/), [`docs/`](../docs/).
