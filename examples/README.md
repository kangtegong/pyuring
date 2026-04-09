# Examples

`before/` = idiomatic Python, `after/` = pyuring. Linux only.

## What each does

Each folder is the same scenario twice: **`before/`** uses a common Python pattern, **`after/`** uses pyuring. The performance being compared is **how fast that scenario completes** (throughput in the charts is bytes read per second for the read-heavy paths).

### `asyncio/`

**Workload:** Read **one file** from an async entrypoint (`asyncio.run` / coroutine) without blocking the event loop.

- **`before/`** — `run_in_executor(None, …)` runs a normal blocking `open().read()` on a worker thread so the loop stays free, but file I/O still goes through the thread pool.
- **`after/`** — `UringCtx` + `UringAsync`: `read_async` submits io_uring reads and `await wait_completion()` ties completions to the loop (no thread pool on the read path).

**Compared:** End-to-end time to get the full file into memory using these two “async file read” styles.

### `fastapi/`

**Workload:** An HTTP handler returns JSON after **reading a payload file from disk** (same idea as serving a static blob or config per request).

- **`before/`** — Route uses `run_in_executor` + `Path.read_bytes()` so the ASGI stack stays async while the blocking read runs in a thread.
- **`after/`** — One `UringCtx` / `UringAsync` pair is created in **`lifespan`** and reused; the route calls the same multi-block `read_async` pattern as `asyncio/after`.

**Compared:** Full **`GET /payload`** request cost (in the charts: `TestClient` median latency turned into effective MiB/s for the bytes returned). **Before** app: port **8765**. **After** app: port **8766**.

### `pytorch/`

**Workload:** Load **many small files** (shards) in one batch — the same shape as a DataLoader prefetch step (this repo does **not** import `torch`; it only models the I/O).

- **`before/`** — `ThreadPoolExecutor` + one `open().read()` per file so many files are read concurrently via threads.
- **`after/`** — One `UringCtx`: `read_async` for a batch of files, `submit`, then `wait_completion` until the batch is done; repeats until every shard is read.

**Compared:** Total time to read the whole shard set (throughput = sum of file sizes ÷ time). Batching many reads through one ring is the usual win here versus per-file threads.

## Results

Regenerate after changing code or hardware:

```bash
PYTHONPATH=. python3 examples/graphs/bench_charts.py
```

Y-axis is always **MiB/s** (effective: bytes read ÷ wall time). **before** / **pyuring** on the x-axis.

| File | Matches |
|------|---------|
| [`graphs/asyncio_read_mib_s.svg`](graphs/asyncio_read_mib_s.svg) | `examples/asyncio/` — one **32 MiB** file, same pattern as `before/read_file.py` vs `after/read_file.py`. |
| [`graphs/fastapi_payload_mib_s.svg`](graphs/fastapi_payload_mib_s.svg) | `examples/fastapi/` — **Starlette `TestClient`** `GET /payload` (full request), **32 MiB** file on disk. |
| [`graphs/pytorch_shards_mib_s.svg`](graphs/pytorch_shards_mib_s.svg) | `examples/pytorch/` — **128 × 64 KiB** shards, thread pool vs batched `read_async`. |

![asyncio](graphs/asyncio_read_mib_s.svg)
![fastapi](graphs/fastapi_payload_mib_s.svg)
![pytorch](graphs/pytorch_shards_mib_s.svg)

On a warm page cache, **asyncio** / **fastapi** “before” paths can look faster in MiB/s than a multi-completion **pyuring** read on a single request; **pytorch**-style many-file reads are where batching usually wins. Treat the numbers as this machine, this run.

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

More: [`graphs/`](graphs/), [`docs/`](../docs/).
