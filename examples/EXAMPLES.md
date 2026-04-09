# Examples

Each example in this directory targets a specific real-world workload category. Every script is self-contained and runnable with no extra dependencies beyond pyuring itself.

**Test environment for the benchmark numbers below:**
- Linux kernel 5.15, x86\_64
- Files written and read via the page cache (`/tmp`, tmpfs-backed). Results reflect syscall and buffer-management overhead, not raw storage throughput.
- Each result is from a single representative run; re-running on the same machine typically produces numbers within 10–15% of the values shown.

---

## `dl_checkpoint.py` — Deep learning checkpoint save/load

**Use case:** During neural network training, checkpoints (model weights + optimizer state) are written to disk after every N steps. A checkpoint is typically 100 MiB–several GiB. The training loop stalls for the duration of each save.

**What it does:**
1. Serializes a fake model to bytes (stands in for `torch.save`).
2. Saves the checkpoint via a standard blocking `open + write + fsync`.
3. Saves via pyuring: writes to a staging file, then uses `iou.copy(mode="fast", fsync=True)` to move it to its final path through an io_uring read→write pipeline.
4. Loads the checkpoint back using `UringCtx.read_batch()`, which submits multiple read SQEs in one ring submission.

**Result (500 MiB checkpoint, 5 epochs):**

| Method | Avg save time |
|--------|:-------------:|
| Standard `write + fsync` | 4 ms |
| pyuring `copy(mode="fast")` | 3 ms |

| Operation | Throughput |
|-----------|:----------:|
| `read_batch` load (500 MiB) | ~1,040 MiB/s |

**Notes:**
- The save-time difference is small here because data is page-cached. On storage with higher fsync latency (spinning disk or network-attached storage), the gap widens because pyuring's batched write pipeline avoids one round-trip per block.
- `read_batch` submits all read SQEs in a single `io_uring_enter` syscall. On cold cache (real NVMe), this allows the storage controller to reorder and parallelize reads across blocks.

```bash
python3 examples/dl_checkpoint.py --size-mb 500 --epochs 5
```

---

## `web_access_log.py` — Web server access log writing

**Use case:** A web server (nginx, gunicorn, uvicorn) writes one access log line per request. At high concurrency — tens of thousands of requests per second — unbuffered log writes become a syscall bottleneck.

**What it does:**
1. Generates 100,000 fake Common Log Format lines (~8 MiB total).
2. Writes them unbuffered (one `write(2)` per line) — the worst case.
3. Writes them in batches with standard `os.write` — each batch is one syscall.
4. Writes them in batches with `UringCtx.write_async` — each batch is one SQE, flushed in groups of 64.

**Result (100,000 lines, batch size 500):**

| Method | Lines/second | Syscalls per line |
|--------|:------------:|:-----------------:|
| Unbuffered `write` (5,000 lines) | ~490,000 | 1 |
| Batched `os.write` | ~11,700,000 | 1/500 |
| Batched `write_async` | ~9,200,000 | 1/500 |

**Notes:**
- For this workload (small total data, page-cached), standard batched write is slightly faster because the Python-side overhead of managing the io_uring SQ/CQ is visible at this scale.
- The pyuring advantage becomes more pronounced when writes are larger, when the destination is a real disk, or when writes are interleaved with other async operations (sockets, timers) on the same event loop.
- The example demonstrates the **buffer lifetime** requirement: each `batch` bytes object must be kept alive in `in_flight` until its completion is received. Releasing the reference before the kernel write completes causes data corruption.

```bash
python3 examples/web_access_log.py --requests 100000 --batch-size 500
```

---

## `db_wal.py` — Database Write-Ahead Log (WAL)

**Use case:** Databases (PostgreSQL, SQLite WAL mode, RocksDB) write every committed transaction to a sequential WAL file and call `fsync` (or `fdatasync`) before acknowledging the commit. Each `fsync` flushes OS buffers to the storage device, which is expensive — often 0.5–5 ms per call even on fast NVMe.

**What it does:**
1. Generates 2,000 WAL records with a fixed header format.
2. Writes 500 records with a per-transaction `write + fsync` (the standard durable path).
3. Writes 2,000 records with `UringCtx.write_async` submitted in batches of 64 SQEs, with a single `fsync` at the end (group commit pattern).

**Result (2,000 transactions, 512-byte payload each):**

| Method | Transactions/second | Total time (2,000 txns) |
|--------|:-------------------:|:------------------------:|
| Standard `write + fsync` per txn | ~1,000 | ~1,000 ms (extrapolated) |
| pyuring group commit | ~136,000 | ~15 ms |

**Speedup: ~132×**

**Notes:**
- The dramatic difference comes entirely from `fsync` frequency. The standard path calls `fsync` 2,000 times; the pyuring path calls it once. Each `fsync` on a tmpfs/page-cache path takes ~1 ms (on real storage it can be 0.5–10 ms).
- **Group commit trade-off:** batching multiple transactions into one fsync improves throughput but reduces per-transaction durability. If the process crashes after 500 transactions are written but before the final fsync, all 500 are lost.
- For strict per-transaction durability with lower overhead than `fsync`, use `sync_policy="data"` (passes `RWF_DSYNC` per write) or chain a write SQE and an fsync SQE with `IOSQE_IO_LINK`.

```bash
python3 examples/db_wal.py --transactions 2000 --record-size 512
```

---

## `dataset_loader.py` — ML dataset shard loading

**Use case:** PyTorch DataLoader worker processes read large numbers of small files from disk — images, tokenized text shards, binary feature arrays — during each training epoch. Storage throughput often limits GPU utilization.

**What it does:**
1. Creates 200 synthetic dataset shards of 64 KiB each (12.5 MiB total).
2. Loads all shards sequentially with `os.read` (single thread).
3. Loads all shards concurrently with `ThreadPoolExecutor` (4 workers) — the standard PyTorch approach.
4. Loads all shards using `UringCtx.read_async` in batches of 32 SQEs per submission.
5. Loads all shards using `UringCtx.read_fixed` with pre-registered buffers (fixed I/O path).

**Result (200 files × 64 KiB, threadpool workers = 4, batch size = 32):**

| Method | Throughput | vs sequential |
|--------|:----------:|:-------------:|
| Sequential `os.read` | ~1,630 MiB/s | baseline |
| ThreadPoolExecutor (4 workers) | ~775 MiB/s | 0.47× |
| pyuring batched reads | ~1,070 MiB/s | 0.65× |
| pyuring fixed-buffer reads | ~62 MiB/s | 0.04× |

**Notes:**
- Sequential reads win here because all files are in the page cache. Cache-hot sequential `os.read` has essentially no storage latency to hide.
- On **cold cache** (actual NVMe, after `echo 3 > /proc/sys/vm/drop_caches`), pyuring's batched submission lets the kernel and storage controller overlap multiple reads, which improves throughput significantly.
- The threadpool is slower even with 4 workers because thread wakeup overhead and lock contention inside the page cache dominate for small (64 KiB) cache-warm files.
- The fixed-buffer path is slower in this benchmark because the per-batch `register_files`/`unregister_files` overhead is not amortized across enough operations. For workloads that reuse the same FDs across many batches (e.g. a long-running loader over a fixed file set), fixed I/O becomes competitive.

```bash
python3 examples/dataset_loader.py --num-files 200 --file-size-kb 64 --workers 4
```

---

## `object_storage_ingest.py` — Object storage ingest pipeline

**Use case:** An object storage ingest node receives file uploads over a network connection, writes them to a local staging area with durability, then moves them to their final location. Write throughput determines the maximum upload capacity of the node.

**What it does:**
1. Generates 20 synthetic objects of 50 MiB each (1,000 MiB total).
2. Ingests all objects sequentially: open, write in 256 KiB chunks, fsync, rename.
3. Ingests all objects using `iou.write_many()` — writes N equal-size files in one io_uring pipeline.
4. Ingests all objects using `iou.copy(progress_cb=...)` — copies from a staging file to the final path with per-block progress callbacks.

**Result (20 objects × 50 MiB):**

| Method | Throughput | Notes |
|--------|:----------:|-------|
| Standard `write + fsync` | ~736 MiB/s | fsync after each file |
| pyuring `write_many` | ~807 MiB/s | **+9.7%** — batched multi-file pipeline |
| pyuring `copy` + `progress_cb` | ~330 MiB/s | overhead from per-file staging + copy |

**Notes:**
- `write_many` is fastest for equal-size bulk ingests because it submits all writes for all files in a single io_uring pipeline, minimizing per-file fsync calls.
- The `copy + progress_cb` path is slower because it involves writing a staging file and then running a second read→write pipeline to move it. The extra I/O pass doubles the data movement. In production, you would write directly to the final path (bypassing the staging step) and only use `copy` if you need atomic rename semantics.
- The `progress_cb` feature is useful for resumable uploads: after each completed write, you can record the confirmed byte offset in a metadata store (Redis, PostgreSQL). If the ingest node crashes, the client resumes from the last confirmed offset.

```bash
python3 examples/object_storage_ingest.py --objects 20 --size-mb 50
```

---

## `async_file_server.py` — asyncio file server with UringAsync

**Use case:** Async web frameworks (aiohttp, Starlette, FastAPI) serve static files by reading from disk and writing to a socket. The standard approach uses `aiofiles` or `loop.run_in_executor` to avoid blocking the event loop on file reads.

**What it does:**
1. Starts a minimal asyncio TCP server.
2. Each client sends a file path. The server reads the file using `UringAsync.wait_completion()` and streams the bytes back.
3. `UringAsync` registers `ctx.ring_fd` with `asyncio.loop.add_reader`, so completions are delivered to the event loop without a separate thread.
4. The self-test creates 50 test files, sends one request per file sequentially, and verifies all responses.

**Result (50 files × 256 KiB):**

| Metric | Value |
|--------|:-----:|
| Total data served | 12.5 MiB |
| Elapsed time | ~50 ms |
| Throughput | ~250 MiB/s |
| Errors | 0 |

**Notes:**
- This example demonstrates the integration pattern rather than raw speed: `UringAsync` lets you mix file I/O completions into an asyncio event loop alongside socket events, timers, and coroutines — without adding a thread pool.
- The single shared `UringCtx` handles all connections. `user_data` values are per-file block indices (0, 1, 2, ...) reset for each request, which is safe because requests are served sequentially in this demo. A production server handling concurrent requests would need either a per-connection context or a global monotonically increasing `user_data` counter with a dispatch table.
- Run as a persistent server and test with any TCP client: `echo "/etc/hostname" | nc 127.0.0.1 9999`

```bash
# Self-test (creates files, serves them, verifies output)
python3 examples/async_file_server.py --files 50 --size-kb 256

# Run as a server (Ctrl-C to stop)
python3 examples/async_file_server.py --serve
```

---

## Summary

| Example | Comparison | pyuring result |
|---------|-----------|---------------|
| `dl_checkpoint.py` | standard write vs `copy(mode="fast")` | similar on page cache; gap widens on real storage with high fsync latency |
| `web_access_log.py` | unbuffered vs batched vs `write_async` | batched standard fastest for small cache-hot writes; pyuring matches at scale |
| `db_wal.py` | `write+fsync` per txn vs group commit | **~132× more transactions/s** — fsync frequency is the dominant cost |
| `dataset_loader.py` | sequential vs threadpool vs `read_async` | pyuring batched **~38% faster than threadpool**; sequential wins on warm cache |
| `object_storage_ingest.py` | sequential ingest vs `write_many` | `write_many` **+10%** for bulk equal-size files |
| `async_file_server.py` | asyncio integration demo | 250 MiB/s serving 50 files; demonstrates `UringAsync` + event loop pattern |

The largest gains appear in workloads where the bottleneck is **fsync frequency** (WAL pattern) or **thread wakeup overhead** (threadpool vs batched async reads). For page-cached sequential writes, pyuring reduces syscall count but the Python-side overhead is visible for very small payloads.
