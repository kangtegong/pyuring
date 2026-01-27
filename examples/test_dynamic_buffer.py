#!/usr/bin/env python3
"""
동적 버퍼 크기 조정 기능 검증 테스트

실제로 파일을 읽고 쓰는 단위가 동적으로 조정되는지 확인합니다.
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
    """버퍼 크기 조정을 추적하는 클래스"""
    
    def __init__(self):
        self.calls: List[Tuple[int, int, int]] = []  # (offset, total, returned_size)
        self.expected_sizes: List[int] = []
    
    def callback(self, current_offset: int, total_bytes: int, default_block_size: int) -> int:
        """콜백 함수 - 호출 정보를 기록하고 크기 반환"""
        # 예상 크기 계산 (간단한 예제: 진행률에 따라 증가)
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
    """copy_path_dynamic의 동적 버퍼 크기 조정 테스트"""
    print("=" * 80)
    print("테스트 1: copy_path_dynamic 동적 버퍼 크기 조정")
    print("=" * 80)
    
    file_size_mb = 5
    file_size = file_size_mb * 1024 * 1024
    default_block_size = 64 * 1024  # 64KB
    
    with tempfile.TemporaryDirectory(prefix="test_dynamic_") as tmpdir:
        tmp_path = Path(tmpdir)
        src_file = tmp_path / "source.dat"
        dst_file = tmp_path / "dest.dat"
        
        # 소스 파일 생성
        with open(src_file, "wb") as f:
            # 패턴 데이터 생성 (위치를 확인할 수 있도록)
            for i in range(0, file_size, 1024):
                chunk = f"CHUNK_{i:010d}_".encode() * (1024 // 20)
                f.write(chunk[:min(1024, file_size - i)])
        
        # 버퍼 크기 추적기 생성
        tracker = BufferSizeTracker()
        
        print(f"기본 블록 크기: {default_block_size / 1024:.0f}KB")
        
        try:
            copied = copy_path_dynamic(
                str(src_file),
                str(dst_file),
                qd=8,
                block_size=default_block_size,
                buffer_size_cb=tracker.callback,
                fsync=False
            )
            
            print(f"복사 완료: {copied:,} bytes")
            
            # 버퍼 크기 변화 확인
            sizes = [size for _, _, size in tracker.calls]
            unique_sizes = sorted(set(sizes))
            print(f"콜백 호출: {len(tracker.calls)}회")
            print(f"사용된 버퍼 크기: {[f'{s/1024:.0f}KB' for s in unique_sizes]}")
            
            # 파일 검증
            with open(src_file, "rb") as f:
                src_data = f.read()
            with open(dst_file, "rb") as f:
                dst_data = f.read()
            
            if src_data != dst_data:
                print("✗ 파일 내용 불일치!")
                return False
            
            # 예상 동작 확인
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
                print("✓ 동적 버퍼 크기 조정 정상 동작")
            else:
                print("✗ 버퍼 크기 조정 오류")
            
            return all_correct
            
        except UringError as e:
            print(f"✗ 오류 발생: {e}")
            return False


def test_write_newfile_dynamic():
    """write_newfile_dynamic의 동적 버퍼 크기 조정 테스트"""
    print("\n" + "=" * 80)
    print("테스트 2: write_newfile_dynamic 동적 버퍼 크기 조정")
    print("=" * 80)
    
    total_mb = 10
    default_block_size = 4 * 1024  # 4KB
    
    with tempfile.TemporaryDirectory(prefix="test_dynamic_") as tmpdir:
        tmp_path = Path(tmpdir)
        dst_file = tmp_path / "test_write.dat"
        
        # 버퍼 크기 추적기 생성
        tracker = BufferSizeTracker()
        
        print(f"기본 블록 크기: {default_block_size / 1024:.0f}KB")
        
        try:
            written = write_newfile_dynamic(
                str(dst_file),
                total_mb=total_mb,
                block_size=default_block_size,
                qd=16,
                fsync=False,
                buffer_size_cb=tracker.callback
            )
            
            print(f"쓰기 완료: {written:,} bytes")
            
            # 버퍼 크기 변화 확인
            sizes = [size for _, _, size in tracker.calls]
            unique_sizes = sorted(set(sizes))
            print(f"콜백 호출: {len(tracker.calls)}회")
            print(f"사용된 버퍼 크기: {[f'{s/1024:.0f}KB' for s in unique_sizes]}")
            
            # 파일 크기 확인
            actual_size = dst_file.stat().st_size
            expected_size = total_mb * 1024 * 1024
            
            if abs(actual_size - expected_size) >= 1024:
                print(f"✗ 파일 크기 불일치 (예상: {expected_size:,}, 실제: {actual_size:,})")
                return False
            
            # 예상 동작 확인
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
                print("✓ 동적 버퍼 크기 조정 정상 동작")
            else:
                print("✗ 버퍼 크기 조정 오류")
            
            return all_correct
            
        except UringError as e:
            print(f"✗ 오류 발생: {e}")
            return False


def test_linear_buffer_size():
    """선형 증가 버퍼 크기 전략 테스트"""
    print("\n" + "=" * 80)
    print("테스트 3: 선형 증가 버퍼 크기 전략")
    print("=" * 80)
    
    file_size_mb = 3
    file_size = file_size_mb * 1024 * 1024
    default_block_size = 32 * 1024  # 32KB
    
    with tempfile.TemporaryDirectory(prefix="test_linear_") as tmpdir:
        tmp_path = Path(tmpdir)
        src_file = tmp_path / "source.dat"
        dst_file = tmp_path / "dest.dat"
        
        # 소스 파일 생성
        with open(src_file, "wb") as f:
            f.write(b"X" * file_size)
        
        # 선형 증가 콜백
        calls = []
        def linear_callback(offset: int, total: int, default: int) -> int:
            if total == 0:
                return default
            progress = offset / total
            # 1x에서 8x까지 선형 증가
            multiplier = 1.0 + (progress * 7.0)
            size = int(default * multiplier)
            calls.append((offset, total, size, progress))
            return size
        
        print(f"기본 블록 크기: {default_block_size / 1024:.0f}KB (예상 범위: {default_block_size / 1024:.0f}KB ~ {default_block_size * 8 / 1024:.0f}KB)")
        
        try:
            copied = copy_path_dynamic(
                str(src_file),
                str(dst_file),
                qd=8,
                block_size=default_block_size,
                buffer_size_cb=linear_callback,
                fsync=False
            )
            
            print(f"복사 완료: {copied:,} bytes")
            
            # 선형 증가 확인
            sizes = [size for _, _, size, _ in calls]
            min_size = min(sizes)
            max_size = max(sizes)
            print(f"콜백 호출: {len(calls)}회")
            print(f"버퍼 크기 범위: {min_size / 1024:.0f}KB ~ {max_size / 1024:.0f}KB")
            
            # 크기 범위 검증
            if min_size >= default_block_size * 0.9 and max_size <= default_block_size * 8.1:
                print("✓ 버퍼 크기 범위 정상")
            else:
                print(f"✗ 버퍼 크기 범위 오류 (예상: {default_block_size/1024:.0f}KB ~ {default_block_size*8/1024:.0f}KB)")
                return False
            
            # 파일 검증
            with open(src_file, "rb") as f:
                src_data = f.read()
            with open(dst_file, "rb") as f:
                dst_data = f.read()
            
            if src_data == dst_data:
                print("✓ 파일 내용 일치")
                return True
            else:
                print("✗ 파일 내용 불일치!")
                return False
                
        except UringError as e:
            print(f"✗ 오류 발생: {e}")
            return False


def main():
    """모든 테스트 실행"""
    print("동적 버퍼 크기 조정 기능 검증 테스트")
    print("=" * 80)
    
    results = []
    
    # 테스트 1: copy_path_dynamic
    results.append(("copy_path_dynamic", test_copy_path_dynamic()))
    
    # 테스트 2: write_newfile_dynamic
    results.append(("write_newfile_dynamic", test_write_newfile_dynamic()))
    
    # 테스트 3: 선형 증가 전략
    results.append(("linear_buffer_size", test_linear_buffer_size()))
    
    # 결과 요약
    print("\n" + "=" * 80)
    print("테스트 결과 요약")
    print("=" * 80)
    
    all_passed = True
    for test_name, result in results:
        status = "✓ 통과" if result else "✗ 실패"
        print(f"{test_name:<30} {status}")
        if not result:
            all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("모든 테스트 통과!")
        return 0
    else:
        print("일부 테스트 실패")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

