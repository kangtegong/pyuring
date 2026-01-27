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

# 테스트
python3 python/demo_read.py /etc/hosts 256
```

## 상세 가이드

### 3) 실행

**파일 읽기:**
```bash
python3 examples/demo_read.py /etc/hosts 256
```

**파일 쓰기:**
```bash
python3 examples/demo_write_tmp.py
```

**파일 복사:**
```bash
python3 examples/demo_copy.py /tmp/src.dat /tmp/dst.dat --qd 32 --block-size 1048576
```

**비동기 API 데모:**
```bash
python3 examples/demo_async_api.py
```

### 4) 속도 비교(벤치마크)

`sudo` 없이도 동작 가능한 형태로, **Python `os.pread` 루프(블록 단위) vs io_uring 배치 제출(C 래퍼)** 를 비교합니다.

```bash
make fetch-liburing
make
python3 examples/bench_read.py --size-mb 256 --block-size 4096 --blocks 4096 --iters 20
```

주의: 권한상 drop_caches를 못 하기 때문에 보통 “페이지캐시 히트” 상태가 되어, 디스크 성능이 아니라 **Python 루프/시스템콜 오버헤드** 차이가 크게 반영됩니다.

또 한 가지 중요한 점: 이 레포의 io_uring 래퍼는 “Python에서 io_uring을 호출해보기”에 초점을 둔 **간단한 구현**이라,
페이지캐시 히트(메모리에서 읽힘) 같은 상황에선 오히려 `os.pread` 루프가 더 빠르게 나올 수 있습니다.

io_uring이 유의미하게 이득을 보는 케이스는 보통:

- **실제 디스크 I/O 지연이 있는 상황**(캐시 미스)에서
- **여러 요청을 동시에(in-flight) 걸어** latency를 겹치거나
- SQPOLL / 고정 버퍼/FD 등록 등으로 syscall/오버헤드를 더 줄였을 때

**랜덤 읽기 벤치마크:**
```bash
python3 examples/bench_rand_read.py --size-mb 1024 --block-size 4096 --reads 256 --iters 30
```

**복사 벤치마크:**
```bash
python3 examples/bench_copy.py --size-mb 512 --qd 32 --uring-block-size 1048576 --block-size 65536
```

**새 파일 쓰기 벤치마크:**
```bash
python3 examples/bench_writev_newfile.py --total-mb 512 --block-size 4096 --vec 64 --repeats 7
```

### 5) 동적 버퍼 크기 조정 (런타임)

io_uring에서 한 번에 읽어들이고 SSD에 write하는(flush하는) 버퍼 크기를 **런타임에 동적으로 조정**할 수 있습니다.

`write_newfile_dynamic` 함수를 사용하면 각 write 전에 콜백 함수를 호출하여 버퍼 크기를 결정할 수 있습니다:

```python
from uringwrap import write_newfile_dynamic

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
written = write_newfile_dynamic(
    "/tmp/test.dat",
    total_mb=100,
    block_size=4096,  # 기본 블록 크기
    qd=256,
    fsync=True,
    buffer_size_cb=adaptive_size,  # 콜백 함수
)
```

데모 스크립트 실행:

```bash
python3 examples/demo_dynamic_buffer.py /tmp/test.dat 100 4096
```

### 읽기+쓰기 복사에서 동적 버퍼 크기 조정

파일을 읽어서 다른 파일로 복사할 때도 동적으로 버퍼 크기를 조정할 수 있습니다:

```python
from uringwrap import copy_path_dynamic

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
copied = copy_path_dynamic(
    "/tmp/source.dat",
    "/tmp/dest.dat",
    qd=32,
    block_size=65536,  # 기본 블록 크기 (64KB)
    buffer_size_cb=adaptive_size,  # 콜백 함수
    fsync=True,  # SSD에 flush
)
```

데모 스크립트 실행:

```bash
# 소스 파일 생성 (테스트용)
dd if=/dev/urandom of=/tmp/source.dat bs=1M count=100

# 동적 버퍼 크기로 복사
python3 examples/demo_copy_dynamic.py /tmp/source.dat /tmp/dest.dat adaptive
```

사용 가능한 전략:
- `adaptive`: 점진적으로 버퍼 크기 증가 (기본값)
- `linear`: 1x에서 16x까지 선형 증가
- `stepwise`: 특정 임계값에서 단계적 증가
- `fixed`: 고정 블록 크기 (동적 조정 없음)

이 기능을 사용하면:
- **작은 버퍼로 시작**하여 초기 지연 시간을 줄이고
- **진행하면서 버퍼 크기를 증가**시켜 전체 처리량을 향상시킬 수 있습니다
- **SSD flush 효율**을 높이기 위해 마지막 부분에서 큰 버퍼를 사용할 수 있습니다
- **작업 부하나 시스템 상태에 따라** 버퍼 크기를 동적으로 조정할 수 있습니다

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
