#!/usr/bin/env python3
"""
Demo script showing dynamic buffer size adjustment in io_uring writes.
"""

import os
import sys
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import write_newfile_dynamic, UringError


def adaptive_buffer_size(current_offset: int, total_bytes: int, default_block_size: int) -> int:
    """
    Example callback that adjusts buffer size based on progress.
    - First 25%: use default size
    - Next 25%: use 2x default size
    - Next 25%: use 4x default size
    - Last 25%: use 8x default size
    """
    progress = current_offset / total_bytes if total_bytes > 0 else 0.0
    
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
    Example callback that linearly increases buffer size.
    """
    # Scale from default_block_size to 16x default_block_size
    progress = current_offset / total_bytes if total_bytes > 0 else 0.0
    multiplier = 1.0 + (progress * 15.0)  # 1.0 to 16.0
    return int(default_block_size * multiplier)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <output_file> [total_mb] [default_block_size]")
        print("Example: python demo_dynamic_buffer.py /tmp/test.dat 100 4096")
        sys.exit(1)
    
    output_file = sys.argv[1]
    total_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    default_block_size = int(sys.argv[3]) if len(sys.argv) > 3 else 4096
    
    print(f"Writing {total_mb} MB to {output_file}")
    print(f"Default block size: {default_block_size} bytes")
    print("Using adaptive buffer size (increases as we progress)")
    
    try:
        import time
        start = time.perf_counter()
        
        written = write_newfile_dynamic(
            output_file,
            total_mb=total_mb,
            block_size=default_block_size,
            qd=256,
            fsync=True,
            dsync=False,
            buffer_size_cb=adaptive_buffer_size,
        )
        
        elapsed = time.perf_counter() - start
        print(f"\nWritten: {written:,} bytes ({written / (1024*1024):.2f} MB)")
        print(f"Time: {elapsed:.2f} seconds")
        print(f"Throughput: {written / elapsed / (1024*1024):.2f} MB/s")
        
        # Verify file size
        actual_size = os.path.getsize(output_file)
        print(f"File size: {actual_size:,} bytes")
        
        if actual_size == written:
            print("✓ File size matches written bytes")
        else:
            print(f"⚠ Warning: File size ({actual_size}) != written bytes ({written})")
            
    except UringError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

