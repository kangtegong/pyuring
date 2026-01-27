#!/usr/bin/env python3
"""
Demo script showing dynamic buffer size adjustment in io_uring copy (read->write).
This demonstrates how to dynamically adjust the buffer size for both reading and writing
to SSD, allowing for adaptive flush sizes based on progress or other factors.
"""

import os
import sys
import time
from uringwrap import copy_path_dynamic, UringError


def adaptive_buffer_size(current_offset: int, total_bytes: int, default_block_size: int) -> int:
    """
    Example callback that adjusts buffer size based on progress.
    - First 25%: use default size (small, fast start)
    - Next 25%: use 2x default size
    - Next 25%: use 4x default size  
    - Last 25%: use 8x default size (large, efficient flush)
    
    This strategy:
    - Starts with small buffers for low latency
    - Gradually increases for better throughput
    - Uses large buffers at the end for efficient SSD flush
    """
    if total_bytes == 0:
        return default_block_size
    
    progress = current_offset / total_bytes
    
    if progress < 0.25:
        return default_block_size
    elif progress < 0.5:
        return default_block_size * 2
    elif progress < 0.75:
        return default_block_size * 4
    else:
        return default_block_size * 8


def linear_increase_buffer_size(current_offset: int, total_bytes: int, default_block_size: int) -> int:
    """
    Example callback that linearly increases buffer size from 1x to 16x.
    """
    if total_bytes == 0:
        return default_block_size
    
    progress = current_offset / total_bytes
    multiplier = 1.0 + (progress * 15.0)  # 1.0 to 16.0
    return int(default_block_size * multiplier)


def stepwise_buffer_size(current_offset: int, total_bytes: int, default_block_size: int) -> int:
    """
    Example callback with stepwise increases at specific thresholds.
    """
    if total_bytes == 0:
        return default_block_size
    
    progress = current_offset / total_bytes
    
    # Step 1: 0-10% -> 1x (warmup)
    # Step 2: 10-30% -> 2x
    # Step 3: 30-60% -> 4x
    # Step 4: 60-100% -> 8x (large flush for SSD efficiency)
    if progress < 0.1:
        return default_block_size
    elif progress < 0.3:
        return default_block_size * 2
    elif progress < 0.6:
        return default_block_size * 4
    else:
        return default_block_size * 8


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <src_file> <dst_file> [strategy]")
        print("")
        print("Strategies:")
        print("  adaptive  - Gradually increase buffer size (default)")
        print("  linear    - Linear increase from 1x to 16x")
        print("  stepwise  - Stepwise increases at thresholds")
        print("  fixed     - Use fixed block size (no dynamic adjustment)")
        print("")
        print("Example:")
        print(f"  python {sys.argv[0]} /tmp/source.dat /tmp/dest.dat adaptive")
        sys.exit(1)
    
    src_file = sys.argv[1]
    dst_file = sys.argv[2]
    strategy = sys.argv[3] if len(sys.argv) > 3 else "adaptive"
    
    if not os.path.exists(src_file):
        print(f"Error: Source file '{src_file}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    file_size = os.path.getsize(src_file)
    print(f"Source file: {src_file}")
    print(f"Destination file: {dst_file}")
    print(f"File size: {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
    print(f"Strategy: {strategy}")
    print("")
    
    # Choose buffer size callback
    buffer_size_cb = None
    if strategy == "adaptive":
        buffer_size_cb = adaptive_buffer_size
        print("Using adaptive buffer size (gradually increases)")
    elif strategy == "linear":
        buffer_size_cb = linear_increase_buffer_size
        print("Using linear buffer size increase")
    elif strategy == "stepwise":
        buffer_size_cb = stepwise_buffer_size
        print("Using stepwise buffer size increases")
    elif strategy == "fixed":
        buffer_size_cb = None
        print("Using fixed block size (no dynamic adjustment)")
    else:
        print(f"Unknown strategy: {strategy}", file=sys.stderr)
        sys.exit(1)
    
    default_block_size = 64 * 1024  # 64KB default
    
    try:
        start = time.perf_counter()
        
        copied = copy_path_dynamic(
            src_file,
            dst_file,
            qd=32,
            block_size=default_block_size,
            buffer_size_cb=buffer_size_cb,
            fsync=True,  # Flush to SSD at the end
        )
        
        elapsed = time.perf_counter() - start
        
        print(f"\nResults:")
        print(f"  Copied: {copied:,} bytes ({copied / (1024*1024):.2f} MB)")
        print(f"  Time: {elapsed:.2f} seconds")
        print(f"  Throughput: {copied / elapsed / (1024*1024):.2f} MB/s")
        
        # Verify file size
        if os.path.exists(dst_file):
            actual_size = os.path.getsize(dst_file)
            print(f"  Destination file size: {actual_size:,} bytes")
            
            if actual_size == copied == file_size:
                print("  ✓ File sizes match")
            else:
                print(f"  ⚠ Warning: Size mismatch (src={file_size}, dst={actual_size}, copied={copied})")
        else:
            print("  ⚠ Warning: Destination file not found")
            
    except UringError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

