# 벤치마크 가이드

## 동기 vs 비동기 I/O 벤치마크

### 기본 사용법

```bash
# 기본 설정 (100개 파일, 각 10MB)
python3 examples/bench_async_vs_sync.py

# 커스텀 설정
python3 examples/bench_async_vs_sync.py --num-files 50 --file-size-mb 20 --qd 64

# 반복 측정 (평균 계산)
python3 examples/bench_async_vs_sync.py --num-files 100 --file-size-mb 10 --qd 32 --repeats 3
```

### 주요 옵션

- `--num-files N`: 파일 개수 (기본: 100)

- `--file-size-mb N`: 파일 크기 MB (기본: 10)

- `--qd N`: Queue depth (기본: 32)

- `--repeats N`: 반복 횟수 (기본: 1)

- `--odirect`: O_DIRECT 사용 (페이지 캐시 우회, 실제 디스크 I/O)

- `--clear-cache`: 테스트 전 페이지 캐시 비우기 (sudo 필요)

- `--keep-files`: 테스트 파일 유지

### 시스템 콜 측정

```bash
# 동기 모드 시스템 콜 측정
strace -c -f python3 examples/bench_syscalls.py --mode sync --num-files 100 --file-size-mb 10

# 비동기 모드 시스템 콜 측정
strace -c -f python3 examples/bench_syscalls.py --mode async --num-files 100 --file-size-mb 10 --qd 32

# 쉘 스크립트로 자동 비교
./examples/compare_syscalls.sh 100 10 32
```

### 예상 결과

일반적으로 비동기 I/O는:

- **쓰기**: 1.5-2x 빠름 (시스템 콜 배치 처리 효과)
- **읽기**: 페이지 캐시 히트 시 차이 작음
- **시스템 콜**: 약 30배 감소 (32,000 → 1,000)

### 참고

- 실제 디스크 성능을 측정하려면 `--odirect` 옵션을 사용하세요
- 더 정확한 측정을 위해 `--repeats` 옵션으로 여러 번 반복 측정하세요
