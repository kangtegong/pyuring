# 사용 가이드 (Usage Guide)

이 문서는 `pyiouring` 패키지를 사용하는 방법을 설명합니다.

## 설치

먼저 패키지를 설치해야 합니다:

```bash
# 저장소 클론
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering

# 패키지 설치
pip install -e .
```

자세한 설치 방법은 [INSTALLATION.md](INSTALLATION.md)를 참조하세요.

## 기본 사용법

### 패키지 import

```python
import pyiouring
```

### 파일 복사

가장 간단한 사용법:

```python
# 기본 설정으로 파일 복사
copied_bytes = pyiouring.copy_path("/tmp/source.dat", "/tmp/dest.dat")
print(f"Copied {copied_bytes:,} bytes")
```

옵션 지정:

```python
copied_bytes = pyiouring.copy_path(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=64,           # Queue depth
    block_size=65536  # Block size (64KB)
)
```

### 동적 버퍼 크기 조정으로 파일 복사

진행 상황에 따라 버퍼 크기를 동적으로 조정:

```python
def adaptive_buffer_size(current_offset, total_bytes, default_block_size):
    """진행 상황에 따라 버퍼 크기 조정"""
    if total_bytes == 0:
        return default_block_size
    
    progress = current_offset / total_bytes
    
    if progress < 0.25:
        return default_block_size      # 처음 25%: 기본 크기
    elif progress < 0.5:
        return default_block_size * 2  # 다음 25%: 2배
    elif progress < 0.75:
        return default_block_size * 4  # 다음 25%: 4배
    else:
        return default_block_size * 8  # 마지막 25%: 8배

# 동적 버퍼 크기로 복사
copied_bytes = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=32,
    block_size=65536,
    buffer_size_cb=adaptive_buffer_size,
    fsync=True  # SSD에 flush
)
```

### 파일 쓰기

새 파일을 생성하고 쓰기:

```python
# 기본 파일 쓰기
written_bytes = pyiouring.write_newfile(
    "/tmp/newfile.dat",
    total_mb=100,      # 100MB
    block_size=4096,   # 4KB 블록
    qd=256,            # Queue depth
    fsync=True         # 마지막에 fsync
)
```

동적 버퍼 크기로 쓰기:

```python
def linear_increase(offset, total, default):
    """선형적으로 버퍼 크기 증가"""
    if total == 0:
        return default
    progress = offset / total
    multiplier = 1.0 + (progress * 15.0)  # 1x ~ 16x
    return int(default * multiplier)

written_bytes = pyiouring.write_newfile_dynamic(
    "/tmp/newfile.dat",
    total_mb=100,
    block_size=4096,
    qd=256,
    fsync=True,
    buffer_size_cb=linear_increase
)
```

### UringCtx 사용 (고급)

더 세밀한 제어가 필요한 경우:

```python
import os
import pyiouring

# Context 생성
with pyiouring.UringCtx(entries=64) as ctx:
    # 파일 열기
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # 동기 읽기
        data = ctx.read(fd, length=4096, offset=0)
        print(f"Read {len(data)} bytes")
        
        # 배치 읽기
        data = ctx.read_batch(fd, block_size=4096, blocks=10, offset=0)
        print(f"Read {len(data)} bytes in batch")
        
        # 여러 오프셋에서 읽기
        offsets = [0, 4096, 8192, 12288]
        data = ctx.read_offsets(fd, block_size=4096, offsets=offsets)
        print(f"Read {len(data)} bytes from {len(offsets)} offsets")
    finally:
        os.close(fd)
```

### 비동기 읽기/쓰기 API

io_uring의 비동기 기능을 직접 사용하려면:

```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # 비동기 읽기 제출
        buf = bytearray(4096)
        ctx.read_async(fd, buf, offset=0, user_data=1)
        
        # 작업 제출
        ctx.submit()
        
        # 완료 대기 (블로킹)
        user_data, result = ctx.wait_completion()
        print(f"Read {result} bytes (user_data={user_data})")
        
        # 또는 논블로킹으로 확인
        completion = ctx.peek_completion()
        if completion:
            user_data, result = completion
            print(f"Read {result} bytes")
    finally:
        os.close(fd)
```

비동기 쓰기:

```python
with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        # 여러 쓰기 작업 제출
        data1 = b"Chunk 1"
        data2 = b"Chunk 2"
        data3 = b"Chunk 3"
        
        ctx.write_async(fd, data1, offset=0, user_data=1)
        ctx.write_async(fd, data2, offset=len(data1), user_data=2)
        ctx.write_async(fd, data3, offset=len(data1)+len(data2), user_data=3)
        
        # 모든 작업 제출
        ctx.submit()
        
        # 모든 완료 대기
        for _ in range(3):
            user_data, result = ctx.wait_completion()
            print(f"Write {user_data}: {result} bytes written")
    finally:
        os.close(fd)
```

### 동적 버퍼 풀 (BufferPool)

동적으로 버퍼 크기를 조정하면서 비동기 I/O를 수행:

```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    # 버퍼 풀 생성 (4개 버퍼, 각 4KB로 시작)
    with pyiouring.BufferPool.create(initial_count=4, initial_size=4096) as pool:
        fd = os.open("/tmp/test.dat", os.O_RDONLY)
        try:
            # 첫 번째 읽기: 4KB
            buf_ptr, buf_size = pool.get_ptr(0)
            pool.set_size(0, 4096)
            ctx.read_async_ptr(fd, buf_ptr, 4096, offset=0, user_data=1)
            
            # 두 번째 읽기: 버퍼 크기를 8KB로 조정
            pool.resize(1, 8192)
            buf_ptr, buf_size = pool.get_ptr(1)
            pool.set_size(1, 8192)
            ctx.read_async_ptr(fd, buf_ptr, 8192, offset=4096, user_data=2)
            
            # 세 번째 읽기: 버퍼 크기를 16KB로 조정
            pool.resize(2, 16384)
            buf_ptr, buf_size = pool.get_ptr(2)
            pool.set_size(2, 16384)
            ctx.read_async_ptr(fd, buf_ptr, 16384, offset=12288, user_data=3)
            
            # 모든 작업 제출
            ctx.submit()
            
            # 완료 처리
            for _ in range(3):
                user_data, result = ctx.wait_completion()
                print(f"Read {user_data}: {result} bytes")
                
                # 버퍼 데이터 읽기
                if user_data == 1:
                    data = pool.get(0)
                elif user_data == 2:
                    data = pool.get(1)
                elif user_data == 3:
                    data = pool.get(2)
                print(f"Buffer data: {data[:50]}...")
        finally:
            os.close(fd)
```

적응형 버퍼 크기 조정 예제:

```python
def adaptive_read_with_pool(ctx, fd, file_size, pool):
    """파일 위치에 따라 버퍼 크기를 동적으로 조정하며 읽기"""
    offset = 0
    user_data = 1
    slot = 0
    
    while offset < file_size:
        # 진행 상황에 따라 버퍼 크기 결정
        progress = offset / file_size
        if progress < 0.25:
            buf_size = 4096
            target_slot = 0
        elif progress < 0.5:
            buf_size = 8192
            target_slot = 1
        elif progress < 0.75:
            buf_size = 16384
            target_slot = 2
        else:
            buf_size = 32768
            target_slot = 3
        
        # 버퍼 크기 조정
        pool.resize(target_slot, buf_size)
        pool.set_size(target_slot, min(buf_size, file_size - offset))
        
        # 비동기 읽기 제출
        buf_ptr, _ = pool.get_ptr(target_slot)
        ctx.read_async_ptr(fd, buf_ptr, min(buf_size, file_size - offset), 
                          offset=offset, user_data=user_data)
        
        offset += buf_size
        user_data += 1
        
        # 주기적으로 제출
        if user_data % 8 == 0:
            ctx.submit()
    
    # 남은 작업 제출
    ctx.submit()
    
    # 모든 완료 대기
    results = []
    for _ in range(user_data - 1):
        user_data_result, result = ctx.wait_completion()
        results.append((user_data_result, result))
    
    return results
```

## 에러 처리

```python
import pyiouring

try:
    copied = pyiouring.copy_path("/nonexistent/file", "/tmp/dest.dat")
except pyiouring.UringError as e:
    print(f"Error: {e}")
```

## 예제

### 예제 1: 간단한 파일 복사

```python
import pyiouring

# 파일 복사
copied = pyiouring.copy_path("input.txt", "output.txt")
print(f"Copied {copied} bytes")
```

### 예제 2: 동적 버퍼 크기로 대용량 파일 복사

```python
import pyiouring

def stepwise_buffer_size(offset, total, default):
    """단계적으로 버퍼 크기 증가"""
    if total == 0:
        return default
    
    progress = offset / total
    
    if progress < 0.1:
        return default
    elif progress < 0.3:
        return default * 2
    elif progress < 0.6:
        return default * 4
    else:
        return default * 8

# 대용량 파일 복사
copied = pyiouring.copy_path_dynamic(
    "/path/to/large_file.dat",
    "/path/to/copy.dat",
    qd=64,
    block_size=65536,
    buffer_size_cb=stepwise_buffer_size,
    fsync=True
)
print(f"Copied {copied:,} bytes")
```

### 예제 3: 여러 파일 생성

```python
import pyiouring
import os

# 디렉토리 생성
os.makedirs("/tmp/many_files", exist_ok=True)

# 여러 파일 생성
total_written = pyiouring.write_manyfiles(
    "/tmp/many_files",
    nfiles=100,
    mb_per_file=10,
    block_size=4096,
    qd=256,
    fsync_end=True
)
print(f"Total written: {total_written:,} bytes")
```

## API 참조

### 함수

- `copy_path(src_path, dst_path, *, qd=32, block_size=1048576)`: 파일 복사
- `copy_path_dynamic(src_path, dst_path, *, qd=32, block_size=1048576, buffer_size_cb=None, fsync=False)`: 동적 버퍼 크기로 파일 복사
- `write_newfile(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False)`: 새 파일 쓰기
- `write_newfile_dynamic(dst_path, *, total_mb, block_size=4096, qd=256, fsync=False, dsync=False, buffer_size_cb=None)`: 동적 버퍼 크기로 새 파일 쓰기
- `write_manyfiles(dir_path, *, nfiles, mb_per_file, block_size=4096, qd=256, fsync_end=False)`: 여러 파일 쓰기

### 클래스

- `UringCtx(entries=64)`: io_uring context 관리자
  
  **동기 메서드:**
  - `read(fd, length, offset=0)`: 동기 읽기
  - `write(fd, data, offset=0)`: 동기 쓰기
  - `read_batch(fd, block_size, blocks, offset=0)`: 배치 읽기
  - `read_offsets(fd, block_size, offsets, *, offset_bytes=True)`: 여러 오프셋에서 읽기
  
  **비동기 메서드:**
  - `read_async(fd, buf, offset=0, user_data=0)`: 비동기 읽기 제출
  - `write_async(fd, data, offset=0, user_data=0)`: 비동기 쓰기 제출
  - `read_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)`: 포인터를 사용한 비동기 읽기
  - `write_async_ptr(fd, buf_ptr, buf_len, offset=0, user_data=0)`: 포인터를 사용한 비동기 쓰기
  - `submit()`: 대기 중인 작업 제출
  - `submit_and_wait(wait_nr=1)`: 제출 후 완료 대기
  - `wait_completion()`: 완료 대기 (블로킹), `(user_data, result)` 튜플 반환
  - `peek_completion()`: 완료 확인 (논블로킹), 완료가 있으면 `(user_data, result)` 튜플, 없으면 `None` 반환

- `BufferPool`: 동적 버퍼 크기 관리 풀
  
  **클래스 메서드:**
  - `BufferPool.create(initial_count=8, initial_size=4096)`: 버퍼 풀 생성
  
  **인스턴스 메서드:**
  - `resize(index, new_size)`: 버퍼 크기 동적 조정
  - `get(index)`: 버퍼 데이터를 bytes로 반환
  - `get_ptr(index)`: 버퍼 포인터와 크기를 `(ptr, size)` 튜플로 반환
  - `set_size(index, size)`: 버퍼 크기 설정 (재할당 없음, capacity 이내)
  - `close()`: 버퍼 풀 해제

### 예외

- `UringError`: io_uring 관련 오류

## 성능 팁

1. **Queue Depth (qd)**: 더 높은 qd는 더 많은 병렬 I/O를 허용하지만 메모리 사용량도 증가합니다.
2. **Block Size**: 일반적으로 64KB~1MB가 좋은 성능을 보입니다.
3. **동적 버퍼 크기**: 작은 버퍼로 시작하고 점진적으로 증가시키면 초기 지연을 줄이면서 전체 처리량을 향상시킬 수 있습니다.
4. **fsync**: 데이터 무결성이 중요할 때만 사용하세요 (성능 저하).

## 추가 리소스

- [README.md](README.md): 프로젝트 개요
- [INSTALLATION.md](INSTALLATION.md): 상세 설치 가이드
