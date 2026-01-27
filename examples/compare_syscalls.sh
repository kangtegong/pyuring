#!/bin/bash
# 시스템 콜 비교 스크립트
# strace를 사용하여 동기/비동기 I/O의 시스템 콜 횟수를 비교

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUM_FILES=${1:-100}
FILE_SIZE_MB=${2:-10}
QD=${3:-32}

echo "=== 시스템 콜 비교 ==="
echo "파일 개수: $NUM_FILES"
echo "파일 크기: ${FILE_SIZE_MB}MB"
echo "Queue depth: $QD"
echo ""

# 동기 방식 시스템 콜 측정
echo "=== 동기 I/O (os.read/os.write) 시스템 콜 측정 ==="
strace -c -f python3 "$SCRIPT_DIR/bench_syscalls.py" --mode sync \
    --num-files "$NUM_FILES" --file-size-mb "$FILE_SIZE_MB" 2>&1 | \
    grep -A 100 "% time" | head -30

echo ""
echo "=== 비동기 I/O (io_uring) 시스템 콜 측정 ==="
strace -c -f python3 "$SCRIPT_DIR/bench_syscalls.py" --mode async \
    --num-files "$NUM_FILES" --file-size-mb "$FILE_SIZE_MB" --qd "$QD" 2>&1 | \
    grep -A 100 "% time" | head -30

