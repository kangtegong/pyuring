#!/usr/bin/env bash
# Upload pyuring to PyPI. Never use "twine upload dist/*" — stray directories
# under dist/ (e.g. manylinux-out) break Twine with:
#   InvalidDistribution: Unknown distribution format: 'manylinux-out'
#
# This script uploads:
#   - the source distribution (.tar.gz), always; and
#   - wheels whose names contain "manylinux" or "musllinux" (auditwheel-repaired
#     builds from cibuildwheel). Bare "linux_x86_64" wheels are skipped with a
#     warning — PyPI rejects them.
#
# Build flow: `python3 -m build` produces an sdist; copy CI wheelhouse/*.whl
# into dist/ before running this script if you publish Linux binaries.
#
# Non-interactive upload (CI or token on disk):
#   export TWINE_USERNAME=__token__
#   export TWINE_PASSWORD=pypi-...   # API token from https://pypi.org/manage/account/token/
#   ./scripts/publish-pypi.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rm -rf dist
mkdir -p dist

python3 -m build

shopt -s nullglob
sdists=(dist/pyuring-*.tar.gz)
all_wheels=(dist/pyuring-*.whl)
shopt -u nullglob

if [[ ${#sdists[@]} -eq 0 ]]; then
  echo "error: no dist/pyuring-*.tar.gz after build" >&2
  exit 1
fi

upload_wheels=()
for w in "${all_wheels[@]}"; do
  case "$w" in
    *manylinux*|*musllinux*)
      upload_wheels+=("$w")
      ;;
    *)
      echo "warning: skipping wheel (not manylinux/musllinux): $w" >&2
      ;;
  esac
done

check_paths=("${sdists[@]}")
if [[ ${#upload_wheels[@]} -gt 0 ]]; then
  check_paths+=("${upload_wheels[@]}")
fi
python3 -m twine check "${check_paths[@]}"

upload_paths=("${sdists[@]}" "${upload_wheels[@]}")
exec python3 -m twine upload "${upload_paths[@]}" "$@"
