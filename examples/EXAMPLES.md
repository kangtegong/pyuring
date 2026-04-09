# Examples

Three examples covering the patterns where pyuring provides the clearest benefit.
Each example is self-contained and runnable with no extra dependencies beyond pyuring.

---

## When pyuring helps

pyuring is most effective in three situations:

1. **High fsync frequency.** Any application that calls `fsync` (or `fdatasync`) per committed record — databases, event logs, message queues — pays ~0.5–10 ms per call. Batching writes and reducing fsync frequency is the single largest lever for throughput improvement. pyuring makes the group-commit pattern straightforward to implement.

2. **Reading many files concurrently.** The standard Python approach is `ThreadPoolExecutor`. Threads work, but each thread wakeup has a fixed cost, and the thread pool becomes a bottleneck under heavy load. pyuring submits N read SQEs in a single syscall and collects all completions in another, achieving the same concurrency without extra threads.

3. **File I/O inside an asyncio event loop.** asyncio has no native support for non-blocking file reads. The usual solution is `loop.run_in_executor`, which delegates to a thread pool. `UringAsync` registers the ring's completion queue fd with the event loop directly, so file I/O completions are delivered as regular asyncio events — no thread pool involved.

---

## `db_wal.py` — Sequential append with per-record durability

**The problem this solves:** Any application that appends records sequentially and calls `fsync` per committed record.

This includes databases (WAL in PostgreSQL, SQLite, RocksDB), message queues (Kafka log segments), event sourcing systems, audit trails, and any service that needs to guarantee a record is on disk before confirming it to the caller.

The bottleneck is always the same: `write() + fsync()` is two syscalls, and `fsync()` is expensive. At 1,000 records/second, that is 1,000 fsync calls per second — one every millisecond.

**What pyuring enables:** The group-commit pattern. Submit all pending writes as a batch of SQEs, then call `fsync` once for the entire batch. This reduces fsync calls from N to 1 per batch, which is where the speedup comes from.

**Result** (2,000 transactions, 512-byte payload, page cache):

| Method | Throughput | Time (2,000 txns) |
|--------|:----------:|:-----------------:|
| `write() + fsync()` per transaction | ~1,000 txns/s | ~2,000 ms (extrapolated) |
| pyuring group commit | ~136,000 txns/s | ~15 ms |

**Speedup: ~132×**

The difference is not from io_uring's write speed — it is from calling `fsync` 2,000 times vs 1 time. On real storage (NVMe, spinning disk), each `fsync` typically costs more than on a page-cached tmpfs, so the gap only widens.

```bash
python3 examples/db_wal.py
python3 examples/db_wal.py --transactions 5000 --record-size 512
```

**Durability note:** Group commit trades per-record durability for throughput. If the process crashes after writing 500 records but before the final fsync, all 500 are lost. For strict per-record durability with lower overhead than separate `fsync` calls, use `sync_policy="data"` (passes `RWF_DSYNC` per write) or chain write+fsync SQEs with `IOSQE_IO_LINK`.

---

## `dataset_loader.py` — Reading many files concurrently

**The problem this solves:** Any application that reads a large number of files and currently uses `ThreadPoolExecutor` to avoid blocking.

This includes ML training pipelines (images, audio, tokenized shards per batch), media processing (frames, thumbnails), search indexing (documents, log files), batch jobs that process a directory of input files, and startup routines that load many configuration or asset files.

`ThreadPoolExecutor` is the standard Python answer to concurrent file reads. It works, but every file read involves a thread wakeup, and thread pool throughput is bounded by the number of workers and scheduling overhead. pyuring submits all reads in one `io_uring_enter` syscall and waits for their completions in another — no threads.

**Result** (200 files × 64 KiB = 12.5 MiB total, page cache):

| Method | Throughput | Notes |
|--------|:----------:|-------|
| Sequential `os.read` | ~1,630 MiB/s | One syscall per file |
| ThreadPoolExecutor (4 workers) | ~775 MiB/s | Thread wakeup cost dominates for small cache-hot files |
| pyuring batched (batch=32) | ~1,070 MiB/s | **+38% vs threadpool** — no thread overhead |
| pyuring fixed-buffer | ~62 MiB/s | Not competitive here; beneficial only when FDs are reused across many batches |

Sequential wins on page-cached files because there is no latency to hide. On **cold cache** (real NVMe, after dropping the page cache), batched submission allows the storage controller to service multiple reads in parallel, and the gap relative to sequential grows further.

```bash
python3 examples/dataset_loader.py
python3 examples/dataset_loader.py --num-files 200 --file-size-kb 64 --workers 4 --batch-size 32
```

---

## `async_file_server.py` — File I/O inside an asyncio event loop

**The problem this solves:** Any asyncio application that needs to read or write files without blocking the event loop and without a thread pool.

asyncio's `loop.run_in_executor` (and `aiofiles` which wraps it) delegates file reads to a thread pool. This works but adds thread wakeup latency and a bounded pool. `UringAsync` eliminates the thread pool entirely: it registers the io_uring completion queue file descriptor (`ring_fd`) with `asyncio.loop.add_reader()`, so file I/O completions arrive as regular event loop callbacks.

This applies to: web frameworks serving static files, API servers reading config or templates per request, data pipelines mixing network and file I/O in one loop, or any asyncio service where thread pool overhead is visible.

**What the example does:** A minimal asyncio TCP server where each client sends a file path and receives the file contents. File reads are submitted as io_uring SQEs and awaited via `UringAsync.wait_completion()` — no background threads.

**Result** (50 files × 256 KiB served sequentially):

| Metric | Value |
|--------|:-----:|
| Total data | 12.5 MiB |
| Elapsed | ~50 ms |
| Throughput | ~250 MiB/s |
| Errors | 0 |

The throughput figure here reflects end-to-end TCP round-trips for 50 sequential requests, not raw file read speed. The key point is correctness and the absence of any thread pool in the implementation.

```bash
# Self-test: creates files, starts server, sends requests, verifies all responses
python3 examples/async_file_server.py
python3 examples/async_file_server.py --files 50 --size-kb 256

# Run as a persistent server
python3 examples/async_file_server.py --serve
echo "/etc/hostname" | nc 127.0.0.1 9999
```

---

## Summary

| Example | Core pattern | Speedup vs standard |
|---------|-------------|:-------------------:|
| `db_wal.py` | Reduce fsync frequency via group commit | **~132×** (2,000 txns/s → 136,000 txns/s) |
| `dataset_loader.py` | Replace ThreadPoolExecutor with batched SQEs | **+38%** vs threadpool on warm cache |
| `async_file_server.py` | Replace `run_in_executor` with `UringAsync` | No thread pool required |

**Test environment:** Linux kernel 5.15, x86\_64. Files in `/tmp` (page cache). Results reflect syscall and scheduling overhead, not raw storage throughput. On real NVMe or spinning disk, cold-cache results will differ — the group-commit gain in `db_wal.py` grows larger, and the batched-read gain in `dataset_loader.py` also grows as storage latency becomes the bottleneck.
