#!/bin/bash
# System call comparison script
# Compare system call counts for synchronous/asynchronous I/O using strace

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUM_FILES=${1:-100}
FILE_SIZE_MB=${2:-10}
QD=${3:-32}

echo "=== System Call Comparison ==="
echo "Number of files: $NUM_FILES"
echo "File size: ${FILE_SIZE_MB}MB"
echo "Queue depth: $QD"
echo ""

# Measure system calls for synchronous mode
echo "=== Synchronous I/O (os.read/os.write) System Call Measurement ==="
strace -c -f python3 "$SCRIPT_DIR/bench_syscalls.py" --mode sync \
    --num-files "$NUM_FILES" --file-size-mb "$FILE_SIZE_MB" 2>&1 | \
    grep -A 100 "% time" | head -30

echo ""
echo "=== Asynchronous I/O (io_uring) System Call Measurement ==="
strace -c -f python3 "$SCRIPT_DIR/bench_syscalls.py" --mode async \
    --num-files "$NUM_FILES" --file-size-mb "$FILE_SIZE_MB" --qd "$QD" 2>&1 | \
    grep -A 100 "% time" | head -30
