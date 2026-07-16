#!/usr/bin/env bash

set -euo pipefail

REPO="GuanceCloud/claude-otel-plugin"
VERSION_INPUT="${1:-latest}"
TMP_DIR=$(mktemp -d)
INSTALL_ROOT="${HOME}/.claude/marketplaces/claude-otel-plugin-release"

cleanup() {
  rm -rf "${TMP_DIR}"
}

trap cleanup EXIT INT TERM

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found in PATH" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found in PATH" >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo "tar not found in PATH" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
`uv` is required to run the hook on macOS, Linux, and Windows.

- Install uv from https://astral.sh/uv/
EOF
  exit 1
fi

case "${1:-}" in
  -h|--help)
    cat <<EOF
Usage:
  install-release.sh [latest|vX.Y.Z|X.Y.Z] [install options]

Examples:
  curl -fsSL https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.sh \\
    | bash -s -- latest --endpoint https://llm-openway.guance.com --x-token <token>

Install options are passed to scripts/install.sh.
EOF
    exit 0
    ;;
esac

normalize_tag() {
  case "$1" in
    latest)
      printf '%s\n' "latest"
      ;;
    claude-otel-plugin--v*)
      printf '%s\n' "$1"
      ;;
    v*)
      printf 'claude-otel-plugin--%s\n' "$1"
      ;;
    *)
      printf 'claude-otel-plugin--v%s\n' "$1"
      ;;
  esac
}

TAG=$(normalize_tag "${VERSION_INPUT}")

if [[ "$#" -gt 0 && "$1" != --* ]]; then
  shift
fi

if [ "${TAG}" = "latest" ]; then
  BASE_URL="https://github.com/${REPO}/releases/latest/download"
else
  BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
fi

ARCHIVE_URL="${BASE_URL}/claude-otel-plugin.tar.gz"
CHECKSUM_URL="${BASE_URL}/claude-otel-plugin.tar.gz.sha256"
ARCHIVE_PATH="${TMP_DIR}/claude-otel-plugin.tar.gz"
CHECKSUM_PATH="${TMP_DIR}/claude-otel-plugin.tar.gz.sha256"

curl -fsSL "${ARCHIVE_URL}" -o "${ARCHIVE_PATH}"

if curl -fsSL "${CHECKSUM_URL}" -o "${CHECKSUM_PATH}"; then
  EXPECTED_SUM=$(tr -d '[:space:]' < "${CHECKSUM_PATH}")
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SUM=$(sha256sum "${ARCHIVE_PATH}" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL_SUM=$(shasum -a 256 "${ARCHIVE_PATH}" | awk '{print $1}')
  else
    ACTUAL_SUM=""
  fi

  if [ -n "${ACTUAL_SUM}" ] && [ "${ACTUAL_SUM}" != "${EXPECTED_SUM}" ]; then
    echo "checksum verification failed for ${ARCHIVE_URL}" >&2
    exit 1
  fi
fi

tar -C "${TMP_DIR}" -xzf "${ARCHIVE_PATH}"
PACKAGE_DIR="${TMP_DIR}/claude-otel-plugin"

if [ ! -f "${PACKAGE_DIR}/.claude-plugin/marketplace.json" ]; then
  echo "release package is missing .claude-plugin/marketplace.json" >&2
  exit 1
fi

if [ ! -f "${PACKAGE_DIR}/scripts/install.sh" ]; then
  echo "release package is missing scripts/install.sh" >&2
  exit 1
fi

rm -rf "${INSTALL_ROOT}"
mkdir -p "$(dirname "${INSTALL_ROOT}")"
cp -R "${PACKAGE_DIR}" "${INSTALL_ROOT}"

bash "${INSTALL_ROOT}/scripts/install.sh" "${INSTALL_ROOT}" --refresh "$@"
