#!/usr/bin/env python3
"""
벤치마크: 동기 I/O (os.read/os.write) vs 비동기 I/O (io_uring)

10MB 크기의 파일 100개를 생성하고 읽는 작업을 수행하며:
- 속도 비교
- 시스템 콜 호출 횟수 비교 (strace 사용)

사용법:
    # 기본 벤치마크 (100개 파일, 각 10MB)
    python3 examples/bench_async_vs_sync.py
    
    # 커스텀 설정
    python3 examples/bench_async_vs_sync.py --num-files 50 --file-size-mb 20 --qd 64
    
    # 시스템 콜 측정 (strace 필요)
    python3 examples/bench_async_vs_sync.py --measure-syscalls
    
    # 시스템 콜만 측정 (별도 스크립트)
    strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10
    strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32
    
    # 쉘 스크립트로 비교
    ./examples/compare_syscalls.sh 100 10 32
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Tuple

# pyiouring import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import UringCtx, BufferPool, UringError


def create_test_files(base_dir: Path, num_files: int, file_size_mb: int) -> List[Path]:
    """테스트용 파일 목록 생성 (빈 파일)"""
    file_paths = []
    for i in range(num_files):
        file_path = base_dir / f"test_{i:03d}.dat"
        file_paths.append(file_path)
    return file_paths


def sync_write(file_path: Path, data: bytes, use_odirect: bool = False) -> int:
    """동기 방식으로 파일 쓰기 (os.write)"""
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags, 0o644)
    try:
        total_written = 0
        offset = 0
        chunk_size = 65536  # 64KB chunks
        
        while offset < len(data):
            chunk = data[offset:offset + chunk_size]
            written = os.write(fd, chunk)
            total_written += written
            offset += written
        os.fsync(fd)  # 디스크에 강제 쓰기
        return total_written
    finally:
        os.close(fd)


def sync_read(file_path: Path, use_odirect: bool = False) -> bytes:
    """동기 방식으로 파일 읽기 (os.read)"""
    flags = os.O_RDONLY
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags)
    try:
        data = bytearray()
        chunk_size = 65536  # 64KB chunks
        
        while True:
            chunk = os.read(fd, chunk_size)
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)
    finally:
        os.close(fd)


def async_write_uring(ctx: UringCtx, file_path: Path, data: bytes, pool: BufferPool, slot: int, user_data: int, use_odirect: bool = False) -> None:
    """비동기 방식으로 파일 쓰기 제출 (io_uring)"""
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags, 0o644)
    
    # 버퍼에 데이터 복사
    buf_ptr, buf_size = pool.get_ptr(slot)
    pool.set_size(slot, len(data))
    
    # 데이터를 버퍼에 복사
    import ctypes
    ctypes.memmove(buf_ptr, data, len(data))
    
    # 비동기 쓰기 제출 (user_data에 fd를 인코딩: 상위 32비트는 fd, 하위 32비트는 slot)
    user_data_encoded = (fd << 32) | slot
    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)


def async_read_uring(ctx: UringCtx, file_path: Path, pool: BufferPool, slot: int, expected_size: int, user_data: int, use_odirect: bool = False) -> None:
    """비동기 방식으로 파일 읽기 제출 (io_uring)"""
    flags = os.O_RDONLY
    if use_odirect:
        flags |= os.O_DIRECT
    fd = os.open(file_path, flags)
    
    # 버퍼 크기 설정
    pool.set_size(slot, expected_size)
    buf_ptr, buf_size = pool.get_ptr(slot)
    
    # 비동기 읽기 제출 (user_data에 fd를 인코딩)
    user_data_encoded = (fd << 32) | slot
    ctx.read_async_ptr(fd, buf_ptr, expected_size, offset=0, user_data=user_data_encoded)


def benchmark_sync_write(file_paths: List[Path], file_size_mb: int, use_odirect: bool = False) -> Tuple[float, int]:
    """동기 쓰기 벤치마크"""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    start_time = time.perf_counter()
    total_written = 0
    
    for file_path in file_paths:
        written = sync_write(file_path, data, use_odirect)
        total_written += written
    
    end_time = time.perf_counter()
    elapsed = end_time - start_time
    
    return elapsed, total_written


def benchmark_sync_read(file_paths: List[Path], use_odirect: bool = False) -> Tuple[float, int]:
    """동기 읽기 벤치마크"""
    start_time = time.perf_counter()
    total_read = 0
    
    for file_path in file_paths:
        data = sync_read(file_path, use_odirect)
        total_read += len(data)
    
    end_time = time.perf_counter()
    elapsed = end_time - start_time
    
    return elapsed, total_read


def benchmark_async_write(file_paths: List[Path], file_size_mb: int, qd: int, use_odirect: bool = False) -> Tuple[float, int]:
    """비동기 쓰기 벤치마크"""
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    # 버퍼 풀 생성 (큐 뎁스만큼)
    with UringCtx(entries=qd * 2) as ctx:
        with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
            start_time = time.perf_counter()
            total_written = 0
            inflight = 0
            file_idx = 0
            fd_map = {}  # user_data -> fd 매핑
            
            # 초기 작업 제출
            while file_idx < len(file_paths) and inflight < qd:
                slot = inflight % qd
                async_write_uring(ctx, file_paths[file_idx], data, pool, slot, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
            
            # 주기적으로 제출
            if inflight > 0:
                ctx.submit()
            
            # 나머지 작업 처리
            while file_idx < len(file_paths):
                # 완료 대기
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(f"Write failed: {result}")
                
                # fd 추출 및 닫기
                fd = user_data_encoded >> 32
                os.fsync(fd)  # 디스크에 강제 쓰기
                os.close(fd)
                
                total_written += result
                inflight -= 1
                
                # 새 작업 제출
                slot = inflight % qd
                async_write_uring(ctx, file_paths[file_idx], data, pool, slot, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
                
                ctx.submit()
            
            # 남은 완료 대기
            while inflight > 0:
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(f"Write failed: {result}")
                
                fd = user_data_encoded >> 32
                os.fsync(fd)
                os.close(fd)
                
                total_written += result
                inflight -= 1
            
            end_time = time.perf_counter()
            elapsed = end_time - start_time
    
    return elapsed, total_written


def benchmark_async_read(file_paths: List[Path], file_size_mb: int, qd: int, use_odirect: bool = False) -> Tuple[float, int]:
    """비동기 읽기 벤치마크"""
    file_size = file_size_mb * 1024 * 1024
    
    with UringCtx(entries=qd * 2) as ctx:
        with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
            start_time = time.perf_counter()
            total_read = 0
            inflight = 0
            file_idx = 0
            
            # 초기 작업 제출
            while file_idx < len(file_paths) and inflight < qd:
                slot = inflight % qd
                async_read_uring(ctx, file_paths[file_idx], pool, slot, file_size, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
            
            # 주기적으로 제출
            if inflight > 0:
                ctx.submit()
            
            # 나머지 작업 처리
            while file_idx < len(file_paths):
                # 완료 대기
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(f"Read failed: {result}")
                
                # fd 추출 및 닫기
                fd = user_data_encoded >> 32
                slot = user_data_encoded & 0xFFFFFFFF
                os.close(fd)
                
                total_read += result
                inflight -= 1
                
                # 새 작업 제출
                slot = inflight % qd
                async_read_uring(ctx, file_paths[file_idx], pool, slot, file_size, file_idx, use_odirect)
                inflight += 1
                file_idx += 1
                
                ctx.submit()
            
            # 남은 완료 대기
            while inflight > 0:
                user_data_encoded, result = ctx.wait_completion()
                if result < 0:
                    raise UringError(f"Read failed: {result}")
                
                fd = user_data_encoded >> 32
                os.close(fd)
                
                total_read += result
                inflight -= 1
            
            end_time = time.perf_counter()
            elapsed = end_time - start_time
    
    return elapsed, total_read


def count_syscalls(command: list[str], label: str) -> dict:
    """strace를 사용하여 시스템 콜 횟수 측정"""
    print(f"\n=== {label} 시스템 콜 측정 중... ===")
    
    try:
        # strace 실행
        strace_cmd = ["strace", "-c", "-f"] + command
        result = subprocess.run(
            strace_cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            print(f"Warning: strace command failed: {result.stderr}")
            return {}
        
        # strace 출력 파싱
        syscall_counts = {}
        lines = result.stderr.split('\n')
        
        for line in lines:
            if '%' in line and 'time' in line.lower():
                # 헤더 라인 스킵
                continue
            parts = line.strip().split()
            if len(parts) >= 4:
                try:
                    count = int(parts[0])
                    syscall_name = parts[-1]
                    if syscall_name and count > 0:
                        syscall_counts[syscall_name] = count
                except (ValueError, IndexError):
                    continue
        
        return syscall_counts
    
    except subprocess.TimeoutExpanded:
        print(f"Warning: strace command timed out")
        return {}
    except FileNotFoundError:
        print(f"Warning: strace not found. Install with: sudo apt-get install strace")
        return {}


def main():
    parser = argparse.ArgumentParser(description="동기 vs 비동기 I/O 벤치마크")
    parser.add_argument("--num-files", type=int, default=100, help="파일 개수 (기본: 100)")
    parser.add_argument("--file-size-mb", type=int, default=10, help="파일 크기 (MB, 기본: 10)")
    parser.add_argument("--qd", type=int, default=32, help="Queue depth (기본: 32)")
    parser.add_argument("--measure-syscalls", action="store_true", help="시스템 콜 측정 (strace 필요)")
    parser.add_argument("--keep-files", action="store_true", help="테스트 파일 유지")
    parser.add_argument("--odirect", action="store_true", help="O_DIRECT 사용 (페이지 캐시 우회, 실제 디스크 I/O)")
    parser.add_argument("--repeats", type=int, default=1, help="반복 횟수 (평균 계산)")
    parser.add_argument("--clear-cache", action="store_true", help="테스트 전 페이지 캐시 비우기 (sudo 필요)")
    
    args = parser.parse_args()
    
    # 임시 디렉토리 생성
    with tempfile.TemporaryDirectory(prefix="iouring_bench_") as tmpdir:
        tmp_path = Path(tmpdir)
        test_dir = tmp_path / "test_files"
        test_dir.mkdir()
        
        file_paths = create_test_files(test_dir, args.num_files, args.file_size_mb)
        file_size_mb = args.file_size_mb
        total_size_gb = (args.num_files * file_size_mb) / 1024
        
        print(f"=== 벤치마크 설정 ===")
        print(f"파일 개수: {args.num_files}")
        print(f"파일 크기: {file_size_mb} MB")
        print(f"총 크기: {total_size_gb:.2f} GB")
        print(f"Queue depth: {args.qd}")
        print(f"O_DIRECT: {'사용' if args.odirect else '미사용'}")
        print(f"반복 횟수: {args.repeats}")
        if args.clear_cache:
            print("페이지 캐시 비우기 중...")
            try:
                subprocess.run(["sync"], check=True)
                subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"], check=True)
                print("페이지 캐시 비움 완료")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("Warning: 페이지 캐시를 비울 수 없습니다 (sudo 필요)")
        print()
        
        # 반복 측정을 위한 리스트
        sync_write_times = []
        async_write_times = []
        sync_read_times = []
        async_read_times = []
        
        for repeat in range(args.repeats):
            if args.repeats > 1:
                print(f"=== 반복 {repeat + 1}/{args.repeats} ===")
            
            # ========== 동기 쓰기 ==========
            if repeat == 0 or args.repeats > 1:
                print("=== 동기 쓰기 (os.write) ===")
            sync_write_time, sync_write_bytes = benchmark_sync_write(file_paths, file_size_mb, args.odirect)
            sync_write_times.append(sync_write_time)
            sync_write_mb_s = (sync_write_bytes / (1024 * 1024)) / sync_write_time if sync_write_time > 0 else 0
            if repeat == 0 or args.repeats > 1:
                print(f"시간: {sync_write_time:.4f}초")
                print(f"처리량: {sync_write_mb_s:.2f} MB/s")
                print(f"총 쓰기: {sync_write_bytes / (1024 * 1024):.2f} MB")
                print()
            
            # ========== 비동기 쓰기 ==========
            if repeat == 0 or args.repeats > 1:
                print("=== 비동기 쓰기 (io_uring) ===")
            async_write_time, async_write_bytes = benchmark_async_write(file_paths, file_size_mb, args.qd, args.odirect)
            async_write_times.append(async_write_time)
            async_write_mb_s = (async_write_bytes / (1024 * 1024)) / async_write_time if async_write_time > 0 else 0
            if repeat == 0 or args.repeats > 1:
                print(f"시간: {async_write_time:.4f}초")
                print(f"처리량: {async_write_mb_s:.2f} MB/s")
                print(f"총 쓰기: {async_write_bytes / (1024 * 1024):.2f} MB")
                print()
            
            # ========== 동기 읽기 ==========
            if repeat == 0 or args.repeats > 1:
                print("=== 동기 읽기 (os.read) ===")
            sync_read_time, sync_read_bytes = benchmark_sync_read(file_paths, args.odirect)
            sync_read_times.append(sync_read_time)
            sync_read_mb_s = (sync_read_bytes / (1024 * 1024)) / sync_read_time if sync_read_time > 0 else 0
            if repeat == 0 or args.repeats > 1:
                print(f"시간: {sync_read_time:.4f}초")
                print(f"처리량: {sync_read_mb_s:.2f} MB/s")
                print(f"총 읽기: {sync_read_bytes / (1024 * 1024):.2f} MB")
                print()
            
            # ========== 비동기 읽기 ==========
            if repeat == 0 or args.repeats > 1:
                print("=== 비동기 읽기 (io_uring) ===")
            async_read_time, async_read_bytes = benchmark_async_read(file_paths, file_size_mb, args.qd, args.odirect)
            async_read_times.append(async_read_time)
            async_read_mb_s = (async_read_bytes / (1024 * 1024)) / async_read_time if async_read_time > 0 else 0
            if repeat == 0 or args.repeats > 1:
                print(f"시간: {async_read_time:.4f}초")
                print(f"처리량: {async_read_mb_s:.2f} MB/s")
                print(f"총 읽기: {async_read_bytes / (1024 * 1024):.2f} MB")
                print()
        
        # 평균 계산
        avg_sync_write_time = sum(sync_write_times) / len(sync_write_times)
        avg_async_write_time = sum(async_write_times) / len(async_write_times)
        avg_sync_read_time = sum(sync_read_times) / len(sync_read_times)
        avg_async_read_time = sum(async_read_times) / len(async_read_times)
        
        avg_sync_write_mb_s = (sync_write_bytes / (1024 * 1024)) / avg_sync_write_time if avg_sync_write_time > 0 else 0
        avg_async_write_mb_s = (async_write_bytes / (1024 * 1024)) / avg_async_write_time if avg_async_write_time > 0 else 0
        avg_sync_read_mb_s = (sync_read_bytes / (1024 * 1024)) / avg_sync_read_time if avg_sync_read_time > 0 else 0
        avg_async_read_mb_s = (async_read_bytes / (1024 * 1024)) / avg_async_read_time if avg_async_read_time > 0 else 0
        
        # ========== 결과 요약 ==========
        print("=" * 80)
        print("=== 결과 요약 ===")
        print("=" * 80)
        if args.repeats > 1:
            print(f"{'작업':<20} {'평균 시간(초)':<18} {'평균 처리량(MB/s)':<20} {'속도 향상':<15}")
            print("-" * 80)
            
            write_speedup = avg_sync_write_time / avg_async_write_time if avg_async_write_time > 0 else 0
            read_speedup = avg_sync_read_time / avg_async_read_time if avg_async_read_time > 0 else 0
            
            print(f"{'동기 쓰기':<20} {avg_sync_write_time:<18.4f} {avg_sync_write_mb_s:<20.2f} {'1.00x':<15}")
            print(f"{'비동기 쓰기':<20} {avg_async_write_time:<18.4f} {avg_async_write_mb_s:<20.2f} {write_speedup:<15.2f}x")
            print(f"{'동기 읽기':<20} {avg_sync_read_time:<18.4f} {avg_sync_read_mb_s:<20.2f} {'1.00x':<15}")
            print(f"{'비동기 읽기':<20} {avg_async_read_time:<18.4f} {avg_async_read_mb_s:<20.2f} {read_speedup:<15.2f}x")
        else:
            print(f"{'작업':<20} {'시간(초)':<15} {'처리량(MB/s)':<15} {'속도 향상':<15}")
            print("-" * 80)
            
            write_speedup = avg_sync_write_time / avg_async_write_time if avg_async_write_time > 0 else 0
            read_speedup = avg_sync_read_time / avg_async_read_time if avg_async_read_time > 0 else 0
            
            print(f"{'동기 쓰기':<20} {avg_sync_write_time:<15.4f} {avg_sync_write_mb_s:<15.2f} {'1.00x':<15}")
            print(f"{'비동기 쓰기':<20} {avg_async_write_time:<15.4f} {avg_async_write_mb_s:<15.2f} {write_speedup:<15.2f}x")
            print(f"{'동기 읽기':<20} {avg_sync_read_time:<15.4f} {avg_sync_read_mb_s:<15.2f} {'1.00x':<15}")
            print(f"{'비동기 읽기':<20} {avg_async_read_time:<15.4f} {avg_async_read_mb_s:<15.2f} {read_speedup:<15.2f}x")
        
        print()
        print("=" * 80)
        print("=== 성능 분석 ===")
        print("=" * 80)
        
        # 쓰기 분석
        write_time_saved = avg_sync_write_time - avg_async_write_time
        write_percent_faster = ((avg_sync_write_time - avg_async_write_time) / avg_sync_write_time) * 100
        print(f"\n📝 쓰기 성능:")
        print(f"   동기:   {avg_sync_write_time:.4f}초 ({avg_sync_write_mb_s:.2f} MB/s)")
        print(f"   비동기: {avg_async_write_time:.4f}초 ({avg_async_write_mb_s:.2f} MB/s)")
        print(f"   → {write_speedup:.2f}x {'빠름' if write_speedup > 1 else '느림'} ({write_time_saved:.4f}초 절약, {write_percent_faster:.1f}% 향상)")
        
        # 읽기 분석
        read_time_saved = avg_sync_read_time - avg_async_read_time
        read_percent_faster = ((avg_sync_read_time - avg_async_read_time) / avg_sync_read_time) * 100 if avg_sync_read_time > 0 else 0
        print(f"\n📖 읽기 성능:")
        print(f"   동기:   {avg_sync_read_time:.4f}초 ({avg_sync_read_mb_s:.2f} MB/s)")
        print(f"   비동기: {avg_async_read_time:.4f}초 ({avg_async_read_mb_s:.2f} MB/s)")
        if read_speedup > 1:
            print(f"   → {read_speedup:.2f}x 빠름 ({read_time_saved:.4f}초 절약, {read_percent_faster:.1f}% 향상)")
        else:
            print(f"   → {1/read_speedup:.2f}x 느림 ({-read_time_saved:.4f}초 더 소요, {-read_percent_faster:.1f}% 저하)")
        
        # 전체 분석
        total_sync_time = avg_sync_write_time + avg_sync_read_time
        total_async_time = avg_async_write_time + avg_async_read_time
        total_speedup = total_sync_time / total_async_time if total_async_time > 0 else 0
        total_time_saved = total_sync_time - total_async_time
        
        print(f"\n📊 전체 성능:")
        print(f"   동기:   {total_sync_time:.4f}초 (쓰기 {avg_sync_write_time:.4f}초 + 읽기 {avg_sync_read_time:.4f}초)")
        print(f"   비동기: {total_async_time:.4f}초 (쓰기 {avg_async_write_time:.4f}초 + 읽기 {avg_async_read_time:.4f}초)")
        print(f"   → {total_speedup:.2f}x {'빠름' if total_speedup > 1 else '느림'} ({total_time_saved:.4f}초 절약)")
        
        if args.repeats > 1:
            # 표준 편차 계산
            import statistics
            if len(sync_write_times) > 1:
                sync_write_std = statistics.stdev(sync_write_times)
                async_write_std = statistics.stdev(async_write_times)
                sync_read_std = statistics.stdev(sync_read_times)
                async_read_std = statistics.stdev(async_read_times)
                print(f"\n📈 통계 (표준 편차):")
                print(f"   동기 쓰기:   {sync_write_std:.4f}초")
                print(f"   비동기 쓰기: {async_write_std:.4f}초")
                print(f"   동기 읽기:   {sync_read_std:.4f}초")
                print(f"   비동기 읽기: {async_read_std:.4f}초")
        
        print()
        
        # ========== 시스템 콜 측정 ==========
        if args.measure_syscalls:
            print("=" * 60)
            print("=== 시스템 콜 측정 ===")
            print("=" * 60)
            print("참고: 시스템 콜 측정을 위해 별도 스크립트를 실행합니다.")
            print("      각 방식의 시스템 콜을 정확히 측정하려면:")
            print("      python3 examples/bench_syscalls.py --mode sync")
            print("      python3 examples/bench_syscalls.py --mode async")
            print()
        
        # 파일 유지 옵션
        if args.keep_files:
            keep_dir = Path("/tmp/iouring_bench_files")
            keep_dir.mkdir(exist_ok=True)
            shutil.copytree(test_dir, keep_dir / "test_files", dirs_exist_ok=True)
            print(f"테스트 파일이 {keep_dir}에 저장되었습니다.")


if __name__ == "__main__":
    main()

