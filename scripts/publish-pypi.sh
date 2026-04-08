#!/usr/bin/env bash
# Upload pyuring to PyPI. Never use "twine upload dist/*" — stray directories
# under dist/ (e.g. manylinux-out) break Twine with:
#   InvalidDistribution: Unknown distribution format: 'manylinux-out'
#
# PyPI rejects bare "linux_x86_64" binary wheels (400 unsupported platform tag).
# Only manylinux*/musllinux wheels are accepted for Linux binaries. This script
# uploads the source distribution (.tar.gz) so `pip install` builds from source.
# To publish wheels later, build with auditwheel/cibuildwheel and upload separately.
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
wheels=(dist/pyuring-*.whl)
shopt -u nullglob

if [[ ${#sdists[@]} -eq 0 ]]; then
  echo "error: no dist/pyuring-*.tar.gz after build" >&2
  exit 1
fi

# Validate everything we built (wheel + sdist)
python3 -m twine check dist/pyuring-*.whl dist/pyuring-*.tar.gz

# PyPI: sdist only (see header comment)
exec python3 -m twine upload "${sdists[@]}" "$@"
