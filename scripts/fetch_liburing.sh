#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/third_party/liburing"

mkdir -p "${ROOT}/third_party"

if [[ -d "${DEST}/.git" ]]; then
  echo "liburing already present: ${DEST}"
  exit 0
fi

echo "Cloning liburing into: ${DEST}"
git clone --depth 1 https://github.com/axboe/liburing.git "${DEST}"


