# Python에서 io_uring 써보기 (kernel 5.15)

Python이 io_uring을 "직접" 지원하진 않아서, 보통은 **liburing(C)** 를 얇게 감싼 `.so`를 만들고 Python에서 `ctypes`로 호출하는 방식이 가장 간단합니다.

이 레포는 다음을 제공합니다:

- `csrc/uring_wrap.c`: liburing 기반 io_uring read/write 래퍼 (동기 및 비동기)
- `pyiouring/`: Python 패키지 (ctypes 바인딩)
- `examples/`: 데모 및 벤치마크 코드
- **비동기 읽기/쓰기 API**: io_uring의 비동기 기능을 직접 사용
- **동적 버퍼 크기 조정**: 런타임에 읽기/쓰기 버퍼 크기를 동적으로 조정하는 기능
- **BufferPool**: 동적으로 버퍼 크기를 조정할 수 있는 버퍼 풀

## 설치

### Python 패키지로 설치 (권장)

```bash
# 저장소 클론
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering

# 패키지 설치
pip install -e .
```

### 사용하기

**기본 파일 복사:**
```python
import pyiouring

# 파일 복사
copied = pyiouring.copy_path("/tmp/source.dat", "/tmp/dest.dat")
```

**동적 버퍼 크기로 복사:**
```python
def adaptive_size(offset, total, default):
    progress = offset / total if total > 0 else 0
    if progress < 0.25:
        return default
    elif progress < 0.5:
        return default * 2
    else:
        return default * 4

copied = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    buffer_size_cb=adaptive_size,
    fsync=True
)
```

**비동기 읽기/쓰기:**
```python
import os
import pyiouring

with pyiouring.UringCtx(entries=64) as ctx:
    fd = os.open("/tmp/test.dat", os.O_RDONLY)
    try:
        # 비동기 읽기 제출
        buf = bytearray(4096)
        ctx.read_async(fd, buf, offset=0, user_data=1)
        ctx.submit()
        
        # 완료 대기
        user_data, result = ctx.wait_completion()
        print(f"Read {result} bytes")
    finally:
        os.close(fd)
```

**동적 버퍼 풀 사용:**
```python
with pyiouring.UringCtx(entries=64) as ctx:
    with pyiouring.BufferPool.create(initial_count=4, initial_size=4096) as pool:
        fd = os.open("/tmp/test.dat", os.O_RDONLY)
        try:
            # 버퍼 크기 동적 조정
            pool.resize(0, 8192)  # 4KB -> 8KB
            buf_ptr, buf_size = pool.get_ptr(0)
            pool.set_size(0, 8192)
            
            # 비동기 읽기
            ctx.read_async_ptr(fd, buf_ptr, 8192, offset=0, user_data=1)
            ctx.submit()
            
            user_data, result = ctx.wait_completion()
            data = pool.get(0)  # 읽은 데이터 가져오기
        finally:
            os.close(fd)
```

자세한 설치 및 사용 방법은 다음 문서를 참조하세요:
- [INSTALLATION.md](INSTALLATION.md): 상세 설치 가이드
- [USAGE.md](USAGE.md): 사용 가이드 및 API 참조
- [examples/BENCHMARKS.md](examples/BENCHMARKS.md): 벤치마크 가이드

### 소스에서 빌드 (개발 모드)

```bash
# 저장소 클론
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering

# 의존성 설치 (옵션 A: 시스템 라이브러리 사용)
sudo apt-get install -y liburing-dev
make

# 또는 옵션 B: vendored liburing 사용
make fetch-liburing
make

```

## 벤치마크

동기 vs 비동기 I/O 성능 비교:

```bash
# 기본 벤치마크
python3 examples/bench_async_vs_sync.py

# 자세한 사용법은 examples/BENCHMARKS.md 참조
```

### 5) 동적 버퍼 크기 조정 (런타임)

io_uring에서 한 번에 읽어들이고 SSD에 write하는(flush하는) 버퍼 크기를 **런타임에 동적으로 조정**할 수 있습니다.

`write_newfile_dynamic` 함수를 사용하면 각 write 전에 콜백 함수를 호출하여 버퍼 크기를 결정할 수 있습니다:

```python
import pyiouring

def adaptive_size(current_offset, total_bytes, default_block_size):
    """진행 상황에 따라 버퍼 크기를 조정"""
    progress = current_offset / total_bytes
    if progress < 0.25:
        return default_block_size      # 처음 25%: 기본 크기
    elif progress < 0.5:
        return default_block_size * 2  # 다음 25%: 2배
    elif progress < 0.75:
        return default_block_size * 4  # 다음 25%: 4배
    else:
        return default_block_size * 8  # 마지막 25%: 8배

# 동적 버퍼 크기로 파일 쓰기
written = pyiouring.write_newfile_dynamic(
    "/tmp/test.dat",
    total_mb=100,
    block_size=4096,  # 기본 블록 크기
    qd=256,
    fsync=True,
    buffer_size_cb=adaptive_size,  # 콜백 함수
)
```

### 읽기+쓰기 복사에서 동적 버퍼 크기 조정

파일을 읽어서 다른 파일로 복사할 때도 동적으로 버퍼 크기를 조정할 수 있습니다:

```python
import pyiouring

def adaptive_size(current_offset, total_bytes, default_block_size):
    """진행 상황에 따라 버퍼 크기 조정"""
    progress = current_offset / total_bytes
    if progress < 0.25:
        return default_block_size      # 처음 25%: 기본 크기
    elif progress < 0.5:
        return default_block_size * 2  # 다음 25%: 2배
    elif progress < 0.75:
        return default_block_size * 4  # 다음 25%: 4배
    else:
        return default_block_size * 8  # 마지막 25%: 8배 (SSD flush 효율)

# 동적 버퍼 크기로 파일 복사 (읽기+쓰기)
copied = pyiouring.copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=32,
    block_size=65536,  # 기본 블록 크기 (64KB)
    buffer_size_cb=adaptive_size,  # 콜백 함수
    fsync=True,  # SSD에 flush
)
```

이 기능을 사용하면:
- **작은 버퍼로 시작**하여 초기 지연 시간을 줄이고
- **진행하면서 버퍼 크기를 증가**시켜 전체 처리량을 향상시킬 수 있습니다
- **SSD flush 효율**을 높이기 위해 마지막 부분에서 큰 버퍼를 사용할 수 있습니다

## 주요 기능

### 비동기 I/O API
- `read_async()`, `write_async()`: 비동기 읽기/쓰기 제출
- `wait_completion()`, `peek_completion()`: 완료 처리
- `submit()`, `submit_and_wait()`: 작업 제출 및 대기

### 동적 버퍼 관리
- `BufferPool`: 런타임에 버퍼 크기를 동적으로 조정
- `resize()`: 버퍼 크기 재할당
- `get()`, `get_ptr()`: 버퍼 데이터 접근

### 고수준 API
- `copy_path()`, `copy_path_dynamic()`: 파일 복사
- `write_newfile()`, `write_newfile_dynamic()`: 새 파일 쓰기
- `write_manyfiles()`: 여러 파일 동시 쓰기

## 참고

- 동기 API와 비동기 API 모두 지원합니다.
- 비동기 API를 사용하면 여러 I/O 작업을 병렬로 처리할 수 있습니다.
- `BufferPool`을 사용하면 런타임에 버퍼 크기를 조정하면서 효율적인 메모리 사용이 가능합니다.
