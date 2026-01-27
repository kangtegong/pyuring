# 설치 가이드 (Installation Guide)

이 문서는 adaptive_buffering 프로젝트를 설치하고 빌드하는 방법을 단계별로 설명합니다.

## 목차

1. [시작하기](#시작하기)
2. [의존성 설치](#의존성-설치)
3. [빌드](#빌드)
4. [빌드 확인](#빌드-확인)
5. [간단한 테스트](#간단한-테스트)
6. [문제 해결](#문제-해결)

## 시작하기

### 1. 저장소 클론

SSH를 사용하는 경우:

```bash
git clone git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

HTTPS를 사용하는 경우:

```bash
git clone https://github.com/kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

### 2. Submodule 초기화 (필수)

이 저장소는 `third_party/liburing`을 Git submodule로 관리합니다. 클론 후 submodule을 초기화해야 합니다:

```bash
# Submodule 초기화 및 다운로드
git submodule update --init --recursive
```

또는 클론할 때 한 번에:

```bash
git clone --recursive git@github.com:kangtegong/adaptive_buffering.git
cd adaptive_buffering
```

**참고**: `third_party/liburing`은 Git submodule로 관리됩니다. 
클론 후 `git submodule update --init --recursive`로 초기화하거나, 
`make fetch-liburing`으로 직접 다운로드할 수도 있습니다.

## 의존성 설치

### 시스템 요구사항

- Linux 커널 5.15 이상 (io_uring 지원)
- Python 3.6 이상
- GCC 컴파일러
- Make
- Git (submodule 사용)

### 옵션 A: 시스템에 liburing-dev 설치 (권장)

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y liburing-dev
```

Fedora/RHEL:

```bash
sudo dnf install liburing-devel
```

Arch Linux:

```bash
sudo pacman -S liburing
```

### 옵션 B: vendored liburing 사용 (sudo 권한 없을 때)

시스템에 `liburing-dev`를 설치할 수 없는 경우, 프로젝트에 포함된 liburing을 사용할 수 있습니다:

```bash
# Submodule이 이미 초기화되어 있다면 바로 빌드 가능
make
```

만약 submodule이 없다면:

```bash
# liburing 자동 다운로드 및 빌드
make fetch-liburing
make
```

## 빌드

### 기본 빌드

```bash
make
```

빌드가 성공하면 `build/liburingwrap.so` 파일이 생성됩니다.

### 빌드 옵션

Makefile에서 다음 변수를 수정할 수 있습니다:

```bash
# 컴파일러 변경
CC=gcc make

# 최적화 레벨 변경
CFLAGS="-O3 -g" make

# 디버그 빌드
CFLAGS="-O0 -g -DDEBUG" make
```

## 빌드 확인

빌드가 성공했는지 확인:

```bash
ls -lh build/liburingwrap.so
```

예상 출력:
```
-rwxr-xr-x 1 user user 123K Jan 23 20:00 build/liburingwrap.so
```

## 간단한 테스트

빌드가 완료되면 다음 명령어로 테스트할 수 있습니다:

### 파일 읽기 데모

```bash
python3 python/demo_read.py /etc/hosts 256
```

### 동적 버퍼 크기로 파일 쓰기 데모

```bash
python3 python/demo_dynamic_buffer.py /tmp/test.dat 10 4096
```

### 파일 복사 데모

```bash
# 소스 파일 생성 (테스트용)
dd if=/dev/urandom of=/tmp/source.dat bs=1M count=10

# 파일 복사
python3 python/demo_copy.py /tmp/source.dat /tmp/dest.dat
```

## 문제 해결

### 빌드 오류

**문제**: `liburing.h: No such file or directory`

**해결**:
- 시스템에 `liburing-dev`가 설치되어 있는지 확인: `dpkg -l | grep liburing-dev`
- 또는 `make fetch-liburing`으로 vendored liburing 사용

**문제**: `gcc: command not found`

**해결**:
```bash
# Ubuntu/Debian
sudo apt-get install build-essential

# Fedora/RHEL
sudo dnf groupinstall "Development Tools"
```

**문제**: `make: command not found`

**해결**:
```bash
# Ubuntu/Debian
sudo apt-get install make

# Fedora/RHEL
sudo dnf install make
```

### Submodule 관련 문제

**문제**: `third_party/liburing`이 비어있음

**해결**:
```bash
git submodule update --init --recursive
```

**문제**: Submodule 업데이트 후 빌드 실패

**해결**:
```bash
# Submodule 재초기화
git submodule deinit -f third_party/liburing
git submodule update --init --recursive

# liburing 재빌드
cd third_party/liburing
make clean
make
cd ../..
```

### Python 관련 문제

**문제**: `ModuleNotFoundError: No module named 'uringwrap'`

**해결**:
- `build/liburingwrap.so`가 존재하는지 확인
- Python 경로에 `python/` 디렉토리가 포함되어 있는지 확인
- 또는 `PYTHONPATH` 환경 변수 설정:
  ```bash
  export PYTHONPATH=$PWD/python:$PYTHONPATH
  ```

**문제**: `OSError: liburing.so.2: cannot open shared object file`

**해결**:
- 시스템에 `liburing` 라이브러리가 설치되어 있는지 확인
- 또는 vendored liburing을 사용하도록 빌드

### 런타임 오류

**문제**: `io_uring_setup failed: Operation not permitted`

**해결**:
- 커널 버전 확인: `uname -r` (5.15 이상 필요)
- io_uring 지원 확인: `ls /sys/fs/io_uring/`

**문제**: `uring_create failed (NULL)`

**해결**:
- 커널이 io_uring을 지원하는지 확인
- 권한 문제일 수 있음 (일부 시스템에서는 특정 권한 필요)

## 추가 정보

### 빌드 산출물

- `build/liburingwrap.so`: Python에서 사용할 수 있는 공유 라이브러리
- `third_party/liburing/src/liburing.a`: 정적 라이브러리 (vendored 빌드 시)

### 환경 변수

빌드 시 다음 환경 변수를 사용할 수 있습니다:

- `CC`: 컴파일러 지정 (기본값: `gcc`)
- `CFLAGS`: 컴파일 플래그 (기본값: `-O2 -g -Wall -Wextra -fPIC`)
- `LDFLAGS`: 링커 플래그

예시:
```bash
CC=clang CFLAGS="-O3 -march=native" make
```

### 정리

빌드 산출물을 정리하려면:

```bash
make clean
```

이 명령어는 `build/` 디렉토리를 삭제합니다. `third_party/liburing`은 유지됩니다.

