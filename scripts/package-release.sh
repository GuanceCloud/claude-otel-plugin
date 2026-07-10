#!/usr/bin/env sh

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
DIST_DIR="${ROOT_DIR}/dist"
STAGE_DIR=$(mktemp -d)
PACKAGE_ROOT="${STAGE_DIR}/claude-otel-plugin"

cleanup() {
  rm -rf "${STAGE_DIR}"
}

trap cleanup EXIT INT TERM

VERSION=$(python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path(".claude-plugin/plugin.json").read_text())
print(manifest["version"])
PY
)

mkdir -p "${DIST_DIR}" "${PACKAGE_ROOT}"

cp -R "${ROOT_DIR}/.claude-plugin" "${PACKAGE_ROOT}/.claude-plugin"
cp -R "${ROOT_DIR}/hooks" "${PACKAGE_ROOT}/hooks"
cp -R "${ROOT_DIR}/docs" "${PACKAGE_ROOT}/docs"
cp -R "${ROOT_DIR}/scripts" "${PACKAGE_ROOT}/scripts"
cp "${ROOT_DIR}/README.md" "${PACKAGE_ROOT}/README.md"

find "${PACKAGE_ROOT}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${PACKAGE_ROOT}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

ARCHIVE_NAME="claude-otel-plugin.tar.gz"
ARCHIVE_PATH="${DIST_DIR}/${ARCHIVE_NAME}"
VERSIONED_ARCHIVE_PATH="${DIST_DIR}/claude-otel-plugin-${VERSION}.tar.gz"
CHECKSUM_PATH="${DIST_DIR}/${ARCHIVE_NAME}.sha256"

tar -C "${STAGE_DIR}" -czf "${ARCHIVE_PATH}" "claude-otel-plugin"
cp "${ARCHIVE_PATH}" "${VERSIONED_ARCHIVE_PATH}"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${ARCHIVE_PATH}" | awk '{print $1}' > "${CHECKSUM_PATH}"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "${ARCHIVE_PATH}" | awk '{print $1}' > "${CHECKSUM_PATH}"
else
  echo "warning: no sha256 tool found; checksum not written" >&2
fi

printf '%s\n' "${ARCHIVE_PATH}"
