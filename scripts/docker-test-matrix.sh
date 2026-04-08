#!/usr/bin/env bash
# Run the unittest suite in multiple Linux distro containers (glibc-based).
# Requires: Docker, network (apt/dnf). io_uring needs Docker seccomp relaxed — see DOCKER_OPTS.
#
# Usage:
#   ./scripts/docker-test-matrix.sh
#   BASE_IMAGES="ubuntu:22.04 debian:bookworm-slim" ./scripts/docker-test-matrix.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Default matrix: LTS / common images (pinned tags for reproducibility)
: "${BASE_IMAGES:=ubuntu:20.04 ubuntu:22.04 ubuntu:24.04 debian:bookworm-slim fedora:40}"

# io_uring setup(2) is blocked by Docker's default seccomp profile.
DOCKER_OPTS=(
  --rm
  -v "${ROOT}:/workspace:rw"
  -w /workspace
  --security-opt seccomp=unconfined
)

# Embedded script: apt-based distros (Debian / Ubuntu). Uses venv (PEP 668 on Debian 12+).
read -r -d '' APT_INNER <<'EOS' || true
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates build-essential python3 python3-venv python3-pip git make
# Prefer distro liburing; fall back to vendored clone (e.g. minimal Ubuntu mirrors without universe).
if ! apt-get install -y -qq liburing-dev 2>/dev/null; then
  echo "liburing-dev not available from apt; will build third_party/liburing"
fi
if [[ ! -f /usr/include/liburing.h ]]; then
  cd /workspace
  make fetch-liburing liburing
fi

python3 -m venv /tmp/pyuring-venv
# shellcheck source=/dev/null
. /tmp/pyuring-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python -m unittest discover -s tests -v
EOS

run_in_apt() {
  local img=$1
  docker run "${DOCKER_OPTS[@]}" "${img}" bash -c "${APT_INNER}"
}

# Fedora: venv avoids touching system site-packages.
read -r -d '' FEDORA_INNER <<'EOS' || true
set -euo pipefail
dnf install -y gcc make liburing-devel python3 python3-pip python3-devel git
python3 -m venv /tmp/pyuring-venv
# shellcheck source=/dev/null
. /tmp/pyuring-venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python -m unittest discover -s tests -v
EOS

run_in_fedora() {
  local img=$1
  docker run "${DOCKER_OPTS[@]}" "${img}" bash -c "${FEDORA_INNER}"
}

failed=0
for img in ${BASE_IMAGES}; do
  echo "========== Docker test: ${img} =========="
  if [[ "${img}" == fedora* ]]; then
    if ! run_in_fedora "${img}"; then
      echo "FAILED: ${img}" >&2
      failed=1
    fi
  else
    if ! run_in_apt "${img}"; then
      echo "FAILED: ${img}" >&2
      failed=1
    fi
  fi
done

if [[ "${failed}" -ne 0 ]]; then
  exit 1
fi
echo "All docker matrix images passed."
