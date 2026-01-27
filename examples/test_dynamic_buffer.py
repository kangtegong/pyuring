#!/usr/bin/env python3
"""
Dynamic buffer size adjustment verification test

Verifies that file read/write units are dynamically adjusted.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

# pyiouring import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import copy_path_dynamic, write_newfile_dynamic, UringError


class BufferSizeTracker:
    """Class to track buffer size adjustments"""
    
    def __init__(self):
        self.calls: List[Tuple[int, int, int]] = []  # (offset, total, returned_size)
        self.expected_sizes: List[int] = []
    
    def callback(self, current_offset: int, total_bytes: int, default_block_size: int) -> int:
        """Callback function - records call information and returns size"""
        # Calculate expected size (simple example: increase based on progress)
        progress = current_offset / total_bytes if total_bytes > 0 else 0.0
        
        if progress < 0.25:
            size = default_block_size
        elif progress < 0.5:
            size = default_block_size * 2
        elif progress < 0.75:
            size = default_block_size * 4
        else:
            size = default_block_size * 8
        
        self.calls.append((current_offset, total_bytes, size))
        self.expected_sizes.append(size)
        return size


def test_copy_path_dynamic():
    """Test dynamic buffer size adjustment for copy_path_dynamic"""
    print("=" * 80)
    print("Test 1: copy_path_dynamic dynamic buffer size adjustment")
    print("=" * 80)
    
    file_size_mb = 5
    file_size = file_size_mb * 1024 * 1024
    default_block_size = 64 * 1024  # 64KB
    
    with tempfile.TemporaryDirectory(prefix="test_dynamic_") as tmpdir:
        tmp_path = Path(tmpdir)
        src_file = tmp_path / "source.dat"
        dst_file = tmp_path / "dest.dat"
        
        # Create source file
        with open(src_file, "wb") as f:
            # Generate pattern data (to verify position)
            for i in range(0, file_size, 1024):
                chunk = f"CHUNK_{i:010d}_".encode() * (1024 // 20)
                f.write(chunk[:min(1024, file_size - i)])
        
        # Create buffer size tracker
        tracker = BufferSizeTracker()
        
        print(f"Default block size: {default_block_size / 1024:.0f}KB")
        
        try:
            copied = copy_path_dynamic(
                str(src_file),
                str(dst_file),
                qd=8,
                block_size=default_block_size,
                buffer_size_cb=tracker.callback,
                fsync=False
            )
            
            print(f"Copy completed: {copied:,} bytes")
            
            # Check buffer size changes
            sizes = [size for _, _, size in tracker.calls]
            unique_sizes = sorted(set(sizes))
            print(f"Callback calls: {len(tracker.calls)} times")
            print(f"Buffer sizes used: {[f'{s/1024:.0f}KB' for s in unique_sizes]}")
            
            # Verify file
            with open(src_file, "rb") as f:
                src_data = f.read()
            with open(dst_file, "rb") as f:
                dst_data = f.read()
            
            if src_data != dst_data:
                print("✗ File content mismatch!")
                return False
            
            # Verify expected behavior
            progress_ranges = [
                (0.0, 0.25, default_block_size),
                (0.25, 0.5, default_block_size * 2),
                (0.5, 0.75, default_block_size * 4),
                (0.75, 1.0, default_block_size * 8),
            ]
            
            all_correct = True
            for offset, total, size in tracker.calls:
                progress = offset / total if total > 0 else 0
                expected_size = None
                for min_prog, max_prog, exp_size in progress_ranges:
                    if min_prog <= progress < max_prog:
                        expected_size = exp_size
                        break
                
                if expected_size and size != expected_size:
                    all_correct = False
                    break
            
            if all_correct:
                print("✓ Dynamic buffer size adjustment working correctly")
            else:
                print("✗ Buffer size adjustment error")
            
            return all_correct
            
        except UringError as e:
            print(f"✗ Error occurred: {e}")
            return False


def test_write_newfile_dynamic():
    """Test dynamic buffer size adjustment for write_newfile_dynamic"""
    print("\n" + "=" * 80)
    print("Test 2: write_newfile_dynamic dynamic buffer size adjustment")
    print("=" * 80)
    
    total_mb = 10
    default_block_size = 4 * 1024  # 4KB
    
    with tempfile.TemporaryDirectory(prefix="test_dynamic_") as tmpdir:
        tmp_path = Path(tmpdir)
        dst_file = tmp_path / "test_write.dat"
        
        # Create buffer size tracker
        tracker = BufferSizeTracker()
        
        print(f"Default block size: {default_block_size / 1024:.0f}KB")
        
        try:
            written = write_newfile_dynamic(
                str(dst_file),
                total_mb=total_mb,
                block_size=default_block_size,
                qd=16,
                fsync=False,
                buffer_size_cb=tracker.callback
            )
            
            print(f"Write completed: {written:,} bytes")
            
            # Check buffer size changes
            sizes = [size for _, _, size in tracker.calls]
            unique_sizes = sorted(set(sizes))
            print(f"Callback calls: {len(tracker.calls)} times")
            print(f"Buffer sizes used: {[f'{s/1024:.0f}KB' for s in unique_sizes]}")
            
            # Check file size
            actual_size = dst_file.stat().st_size
            expected_size = total_mb * 1024 * 1024
            
            if abs(actual_size - expected_size) >= 1024:
                print(f"✗ File size mismatch (expected: {expected_size:,}, actual: {actual_size:,})")
                return False
            
            # Verify expected behavior
            progress_ranges = [
                (0.0, 0.25, default_block_size),
                (0.25, 0.5, default_block_size * 2),
                (0.5, 0.75, default_block_size * 4),
                (0.75, 1.0, default_block_size * 8),
            ]
            
            all_correct = True
            for offset, total, size in tracker.calls:
                progress = offset / total if total > 0 else 0
                expected_size = None
                for min_prog, max_prog, exp_size in progress_ranges:
                    if min_prog <= progress < max_prog:
                        expected_size = exp_size
                        break
                
                if expected_size and size != expected_size:
                    all_correct = False
                    break
            
            if all_correct:
                print("✓ Dynamic buffer size adjustment working correctly")
            else:
                print("✗ Buffer size adjustment error")
            
            return all_correct
            
        except UringError as e:
            print(f"✗ Error occurred: {e}")
            return False


def test_linear_buffer_size():
    """Test linear increase buffer size strategy"""
    print("\n" + "=" * 80)
    print("Test 3: Linear increase buffer size strategy")
    print("=" * 80)
    
    file_size_mb = 3
    file_size = file_size_mb * 1024 * 1024
    default_block_size = 32 * 1024  # 32KB
    
    with tempfile.TemporaryDirectory(prefix="test_linear_") as tmpdir:
        tmp_path = Path(tmpdir)
        src_file = tmp_path / "source.dat"
        dst_file = tmp_path / "dest.dat"
        
        # Create source file
        with open(src_file, "wb") as f:
            f.write(b"X" * file_size)
        
        # Linear increase callback
        calls = []
        def linear_callback(offset: int, total: int, default: int) -> int:
            if total == 0:
                return default
            progress = offset / total
            # Linear increase from 1x to 8x
            multiplier = 1.0 + (progress * 7.0)
            size = int(default * multiplier)
            calls.append((offset, total, size, progress))
            return size
        
        print(f"Default block size: {default_block_size / 1024:.0f}KB (expected range: {default_block_size / 1024:.0f}KB ~ {default_block_size * 8 / 1024:.0f}KB)")
        
        try:
            copied = copy_path_dynamic(
                str(src_file),
                str(dst_file),
                qd=8,
                block_size=default_block_size,
                buffer_size_cb=linear_callback,
                fsync=False
            )
            
            print(f"Copy completed: {copied:,} bytes")
            
            # Verify linear increase
            sizes = [size for _, _, size, _ in calls]
            min_size = min(sizes)
            max_size = max(sizes)
            print(f"Callback calls: {len(calls)} times")
            print(f"Buffer size range: {min_size / 1024:.0f}KB ~ {max_size / 1024:.0f}KB")
            
            # Verify size range
            if min_size >= default_block_size * 0.9 and max_size <= default_block_size * 8.1:
                print("✓ Buffer size range correct")
            else:
                print(f"✗ Buffer size range error (expected: {default_block_size/1024:.0f}KB ~ {default_block_size*8/1024:.0f}KB)")
                return False
            
            # Verify file
            with open(src_file, "rb") as f:
                src_data = f.read()
            with open(dst_file, "rb") as f:
                dst_data = f.read()
            
            if src_data == dst_data:
                print("✓ File content matches")
                return True
            else:
                print("✗ File content mismatch!")
                return False
                
        except UringError as e:
            print(f"✗ Error occurred: {e}")
            return False


def main():
    """Run all tests"""
    print("Dynamic buffer size adjustment verification test")
    print("=" * 80)
    
    results = []
    
    # Test 1: copy_path_dynamic
    results.append(("copy_path_dynamic", test_copy_path_dynamic()))
    
    # Test 2: write_newfile_dynamic
    results.append(("write_newfile_dynamic", test_write_newfile_dynamic()))
    
    # Test 3: Linear increase strategy
    results.append(("linear_buffer_size", test_linear_buffer_size()))
    
    # Result summary
    print("\n" + "=" * 80)
    print("Test result summary")
    print("=" * 80)
    
    all_passed = True
    for test_name, result in results:
        status = "✓ Passed" if result else "✗ Failed"
        print(f"{test_name:<30} {status}")
        if not result:
            all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
