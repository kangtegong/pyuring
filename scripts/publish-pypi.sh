#!/usr/bin/env bash
# Upload pyuring to PyPI. Never use "twine upload dist/*" — stray directories
# under dist/ (e.g. manylinux-out) break Twine with:
#   InvalidDistribution: Unknown distribution format: 'manylinux-out'
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Clean dist so we never upload mixed versions or stray dirs (e.g. manylinux-out/)
rm -rf dist
mkdir -p dist

python3 -m build

shopt -s nullglob
artifacts=(dist/pyuring-*.whl dist/pyuring-*.tar.gz)
shopt -u nullglob

if [[ ${#artifacts[@]} -eq 0 ]]; then
  echo "error: no dist/pyuring-*.whl or dist/pyuring-*.tar.gz after build" >&2
  exit 1
fi

python3 -m twine check "${artifacts[@]}"
exec python3 -m twine upload "${artifacts[@]}" "$@"
