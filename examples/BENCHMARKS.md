# Benchmark Guide

## Synchronous vs Asynchronous I/O Benchmark

### Basic Usage

```bash
# Default settings (100 files, 10MB each)
python3 examples/bench_async_vs_sync.py

# Custom settings
python3 examples/bench_async_vs_sync.py --num-files 50 --file-size-mb 20 --qd 64

# Repeated measurements (average calculation)
python3 examples/bench_async_vs_sync.py --num-files 100 --file-size-mb 10 --qd 32 --repeats 3
```

### Main Options

- `--num-files N`: Number of files (default: 100)

- `--file-size-mb N`: File size in MB (default: 10)

- `--qd N`: Queue depth (default: 32)

- `--repeats N`: Number of repetitions (default: 1)

- `--no-odirect`: Disable O_DIRECT (by default O_DIRECT is enabled for direct disk I/O, bypassing page cache)

- `--clear-cache`: Clear page cache before test (requires sudo)

- `--keep-files`: Keep test files

### System Call Measurement

```bash
# Measure system calls in synchronous mode
strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10

# Measure system calls in asynchronous mode
strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32

# Automatic comparison with shell script
./examples/compare_syscalls.sh 100 10 32
```

### Expected Results

Generally, asynchronous I/O shows:

- **Write**: 1.5-2x faster (system call batching effect)
- **Read**: Small difference when page cache hits
- **System calls**: Approximately 30x reduction (32,000 → 1,000)

### Notes

- O_DIRECT is enabled by default for direct disk I/O; use `--no-odirect` to use page cache
- Use the `--repeats` option for more accurate measurements with multiple iterations
