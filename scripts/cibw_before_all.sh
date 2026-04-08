#!/usr/bin/env bash
# Run inside cibuildwheel Linux containers before building pyuring.
# Clones and builds vendored liburing so the top-level Makefile links
# liburingwrap.so against third_party/liburing/src/liburing.a (no runtime
# dependency on liburing.so — only libc).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

need_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  if command -v apk >/dev/null 2>&1; then
    apk add --no-cache git
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y git
  elif command -v yum >/dev/null 2>&1; then
    yum install -y git
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq git
  fi
}

if [[ ! -f "${ROOT}/third_party/liburing/src/include/liburing.h" ]]; then
  need_git
  mkdir -p "${ROOT}/third_party"
  git clone --depth 1 https://github.com/axboe/liburing.git "${ROOT}/third_party/liburing"
fi

make -C "${ROOT}/third_party/liburing" -j"$(nproc)"
