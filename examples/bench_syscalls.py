#!/usr/bin/env python3
"""
시스템 콜 호출 횟수 측정 스크립트

strace를 사용하여 동기/비동기 I/O의 시스템 콜 횟수를 측정합니다.
이 스크립트는 strace로 래핑되어 실행됩니다.
"""

import os
import sys
import tempfile
from pathlib import Path

# pyiouring import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyiouring import UringCtx, BufferPool


def sync_write_read(num_files: int, file_size_mb: int):
    """동기 방식으로 파일 쓰기/읽기"""
    import time
    
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    with tempfile.TemporaryDirectory(prefix="iouring_syscall_") as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 쓰기
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            try:
                offset = 0
                chunk_size = 65536
                while offset < len(data):
                    chunk = data[offset:offset + chunk_size]
                    os.write(fd, chunk)
                    offset += len(chunk)
            finally:
                os.close(fd)
        
        # 읽기
        for i in range(num_files):
            file_path = tmp_path / f"test_{i:03d}.dat"
            fd = os.open(file_path, os.O_RDONLY)
            try:
                chunk_size = 65536
                while True:
                    chunk = os.read(fd, chunk_size)
                    if not chunk:
                        break
            finally:
                os.close(fd)


def async_write_read(num_files: int, file_size_mb: int, qd: int):
    """비동기 방식으로 파일 쓰기/읽기"""
    import time
    import ctypes
    
    file_size = file_size_mb * 1024 * 1024
    data = b"X" * file_size
    
    with tempfile.TemporaryDirectory(prefix="iouring_syscall_") as tmpdir:
        tmp_path = Path(tmpdir)
        
        with UringCtx(entries=qd * 2) as ctx:
            with BufferPool.create(initial_count=qd, initial_size=file_size) as pool:
                # 쓰기
                file_idx = 0
                inflight = 0
                
                # 초기 작업 제출
                while file_idx < num_files and inflight < qd:
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
                    slot = inflight % qd
                    
                    # 버퍼에 데이터 복사
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    pool.set_size(slot, len(data))
                    ctypes.memmove(buf_ptr, data, len(data))
                    
                    # 비동기 쓰기 제출 (user_data에 fd 인코딩)
                    user_data_encoded = (fd << 32) | slot
                    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                
                ctx.submit()
                
                # 나머지 작업 처리
                while file_idx < num_files:
                    user_data_encoded, result = ctx.wait_completion()
                    # fd 추출 및 닫기
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                    
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
                    slot = inflight % qd
                    
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    pool.set_size(slot, len(data))
                    ctypes.memmove(buf_ptr, data, len(data))
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.write_async_ptr(fd, buf_ptr, len(data), offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                    
                    ctx.submit()
                
                # 남은 완료 대기
                while inflight > 0:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                
                # 읽기
                file_idx = 0
                inflight = 0
                
                # 초기 작업 제출
                while file_idx < num_files and inflight < qd:
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_RDONLY)
                    slot = inflight % qd
                    
                    pool.set_size(slot, file_size)
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.read_async_ptr(fd, buf_ptr, file_size, offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                
                ctx.submit()
                
                # 나머지 작업 처리
                while file_idx < num_files:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1
                    
                    file_path = tmp_path / f"test_{file_idx:03d}.dat"
                    fd = os.open(file_path, os.O_RDONLY)
                    slot = inflight % qd
                    
                    pool.set_size(slot, file_size)
                    buf_ptr, buf_size = pool.get_ptr(slot)
                    
                    user_data_encoded = (fd << 32) | slot
                    ctx.read_async_ptr(fd, buf_ptr, file_size, offset=0, user_data=user_data_encoded)
                    inflight += 1
                    file_idx += 1
                    
                    ctx.submit()
                
                # 남은 완료 대기
                while inflight > 0:
                    user_data_encoded, result = ctx.wait_completion()
                    fd = user_data_encoded >> 32
                    os.close(fd)
                    inflight -= 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="시스템 콜 측정 스크립트")
    parser.add_argument("--mode", choices=["sync", "async"], required=True, help="측정 모드")
    parser.add_argument("--num-files", type=int, default=100, help="파일 개수")
    parser.add_argument("--file-size-mb", type=int, default=10, help="파일 크기 (MB)")
    parser.add_argument("--qd", type=int, default=32, help="Queue depth (async 모드)")
    
    args = parser.parse_args()
    
    if args.mode == "sync":
        sync_write_read(args.num_files, args.file_size_mb)
    else:
        async_write_read(args.num_files, args.file_size_mb, args.qd)


if __name__ == "__main__":
    main()

