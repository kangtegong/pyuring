# Benchmarks

## What is being measured

`examples/bench_async_vs_sync.py` runs the same workload (write N files, then read them back) using two implementations:

- **sync**: `os.open` + `os.write` + `os.read` in a sequential loop — one syscall per operation
- **pyuring**: `UringCtx` + `BufferPool` with io_uring submission batching — multiple operations queued before entering the kernel

Both implementations operate on the same files and the same total data size. The benchmark measures wall-clock time for the write phase plus the read phase combined.

## Results

The table below shows how much faster the pyuring implementation is compared to the sync implementation. Numbers are the mean of 3 runs, 8 files × 2 MiB each, with `--no-odirect` (page cache enabled), in Docker on the listed base images.

| Environment | pyuring vs sync os read/write |
|-------------|-------------------------------|
| Ubuntu 22.04 | 1.25× faster |
| Debian 12 | 1.29× faster |
| Fedora 40 | 1.24× faster |

The exact speedup depends on CPU, storage device, kernel version, and queue depth. To get numbers for your own hardware, run the benchmark yourself (see below). Using `--no-odirect` removes storage latency from the picture and isolates the syscall and buffer management overhead difference between the two implementations.

## Running the benchmark

```bash
# Reproduce the numbers from the table above
python3 examples/bench_async_vs_sync.py --num-files 8 --file-size-mb 2 --no-odirect --repeats 3

# Larger workload with O_DIRECT (bypasses page cache, hits storage)
python3 examples/bench_async_vs_sync.py --num-files 50 --file-size-mb 20 --qd 64

# Adjust queue depth
python3 examples/bench_async_vs_sync.py --num-files 100 --file-size-mb 10 --qd 32 --repeats 3
```

### All options

| Option | Default | Description |
|--------|---------|-------------|
| `--num-files N` | 100 | Number of files to write and read back. |
| `--file-size-mb N` | 10 | Size of each file in MiB. |
| `--qd N` | 32 | io_uring queue depth for the pyuring path. |
| `--repeats N` | 1 | Number of full runs to average. Use 3 or more for stable results. |
| `--no-odirect` | — | Disable O\_DIRECT so I/O goes through the page cache. Useful for isolating syscall overhead. |
| `--clear-cache` | — | Drop the page cache before each run (`sudo` required). Use this with O\_DIRECT to avoid warm-cache effects. |
| `--keep-files` | — | Do not delete test files after the run. Useful for inspecting results. |

## Measuring syscall counts

`examples/bench_syscalls.py` and `examples/compare_syscalls.sh` let you compare how many syscalls each implementation issues for the same workload.

```bash
# Automated comparison: runs both modes and prints syscall counts side by side
./examples/compare_syscalls.sh 100 10 32
# Arguments: num_files file_size_mb queue_depth

# Manual measurement with strace
strace -c -f python3 examples/bench_syscalls.py --mode sync  --num-files 100 --file-size-mb 10
strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32
```

The sync path issues one `read(2)` or `write(2)` syscall per block. The io_uring path issues one `io_uring_enter(2)` per batch, which is the source of the syscall reduction.
