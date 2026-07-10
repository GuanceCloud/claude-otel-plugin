#!/usr/bin/env sh

set -eu

REPO="GuanceCloud/claude-otel-plugin"
PLUGIN_ID="claude-otel-plugin@claude-otel-plugin"
MARKETPLACE_NAME="claude-otel-plugin"
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

if ! command -v uv >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Either `uv` or `python3` is required.

- Preferred: install uv from https://astral.sh/uv/
- Fallback: ensure python3 >= 3.10 is available in PATH
EOF
  exit 1
fi

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

rm -rf "${INSTALL_ROOT}"
mkdir -p "$(dirname "${INSTALL_ROOT}")"
cp -R "${PACKAGE_DIR}" "${INSTALL_ROOT}"

claude plugin marketplace remove "${MARKETPLACE_NAME}" >/dev/null 2>&1 || true
claude plugin marketplace add "${INSTALL_ROOT}" >/dev/null 2>&1 || true
claude plugin marketplace update "${MARKETPLACE_NAME}" >/dev/null 2>&1 || true

if claude plugin list --json | grep -q "\"id\": \"${PLUGIN_ID}\""; then
  claude plugin update "${PLUGIN_ID}"
else
  claude plugin install "${PLUGIN_ID}"
fi

cat <<EOF
Plugin installed from release: ${TAG}
Source path: ${INSTALL_ROOT}

Next step:
- Restart Claude Code to apply the updated plugin.
EOF
