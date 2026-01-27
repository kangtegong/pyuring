# Python에서 io_uring 써보기 (kernel 5.15)

Python이 io_uring을 “직접” 지원하진 않아서, 보통은 **liburing(C)** 를 얇게 감싼 `.so`를 만들고 Python에서 `ctypes`로 호출하는 방식이 가장 간단합니다.

이 레포는 다음을 제공합니다:

- `csrc/uring_wrap.c`: liburing 기반 io_uring read/write(sync) 래퍼
- `python/uringwrap.py`: Python `ctypes` 바인딩
- `python/demo_read.py`: 파일 일부를 io_uring으로 읽기
- `python/demo_write_tmp.py`: 임시파일에 io_uring으로 쓰기

## 1) 의존성 설치 (Ubuntu)

`liburing` 개발 헤더가 필요합니다.

```bash
sudo apt-get update
sudo apt-get install -y liburing-dev
```

만약 `sudo` 권한이 없으면(예: 일반 유저/컨테이너), 이 레포에서 **liburing을 로컬로 vendoring** 해서 빌드할 수도 있습니다:

```bash
make fetch-liburing
make
```

**참고**: `third_party/liburing`은 Git 저장소에 포함되지 않습니다 (`.gitignore`에 추가됨). 
저장소를 클론한 후 위 명령어로 자동으로 다운로드됩니다.

## 2) 빌드

```bash
make
```

성공하면 `build/liburingwrap.so`가 생깁니다.

## 3) 실행

파일 읽기:

```bash
python3 -m python.demo_read /etc/hosts 256
```

또는 스크립트로 실행:

```bash
python3 python/demo_read.py /etc/hosts 256
```

파일 쓰기(임시 디렉토리):

```bash
python3 -m python.demo_write_tmp
```

또는 스크립트로 실행:

```bash
python3 python/demo_write_tmp.py
```

파일 복사(읽기+쓰기) - io_uring 파이프라인(C)로 Python 루프 오버헤드를 제거해서 더 빠르게 만들기:

```bash
python3 -m python.demo_copy /tmp/iouring_copy_src.dat /tmp/iouring_copy_dst.dat --qd 32 --block-size 1048576
```

## 4) 속도 비교(벤치마크)

`sudo` 없이도 동작 가능한 형태로, **Python `os.pread` 루프(블록 단위) vs io_uring 배치 제출(C 래퍼)** 를 비교합니다.

```bash
make fetch-liburing
make
python3 -m python.bench_read --size-mb 256 --block-size 4096 --blocks 4096 --iters 20
```

주의: 권한상 drop_caches를 못 하기 때문에 보통 “페이지캐시 히트” 상태가 되어, 디스크 성능이 아니라 **Python 루프/시스템콜 오버헤드** 차이가 크게 반영됩니다.

또 한 가지 중요한 점: 이 레포의 io_uring 래퍼는 “Python에서 io_uring을 호출해보기”에 초점을 둔 **간단한 구현**이라,
페이지캐시 히트(메모리에서 읽힘) 같은 상황에선 오히려 `os.pread` 루프가 더 빠르게 나올 수 있습니다.

io_uring이 유의미하게 이득을 보는 케이스는 보통:

- **실제 디스크 I/O 지연이 있는 상황**(캐시 미스)에서
- **여러 요청을 동시에(in-flight) 걸어** latency를 겹치거나
- SQPOLL / 고정 버퍼/FD 등록 등으로 syscall/오버헤드를 더 줄였을 때

랜덤 읽기(큐뎁스 효과)도 같이 볼 수 있습니다:

```bash
python3 -m python.bench_rand_read --size-mb 1024 --block-size 4096 --reads 256 --iters 30
```

복사(읽기+쓰기) 벤치마크(naive Python vs shutil.copyfile vs io_uring):

```bash
python3 -m python.bench_copy --size-mb 512 --qd 32 --uring-block-size 1048576 --block-size 65536
```

새 파일에 작은 write가 "왕창" 많을 때(시스템콜 개수 자체를 줄이는 게 핵심) `writev`로 batching 해서 빨라지는지 확인:

```bash
python3 -m python.bench_writev_newfile --total-mb 512 --block-size 4096 --vec 64 --repeats 7
```

## 5) 동적 버퍼 크기 조정 (런타임)

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
python3 python/demo_dynamic_buffer.py /tmp/test.dat 100 4096
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
python3 python/demo_copy_dynamic.py /tmp/source.dat /tmp/dest.dat adaptive
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

## 참고

- 이 샘플은 “io_uring을 Python에서 호출해보는” 데 집중하려고 **sync helper(제출 후 완료 대기)** 형태로 만들었습니다.
- 다음 단계로는 여러 SQE를 한 번에 enqueue하고 CQE를 batch로 처리하는 형태(진짜 async 스타일)로 확장하면 됩니다.
