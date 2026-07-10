#!/usr/bin/env bash

set -euo pipefail

REPO="${CLAUDE_OTEL_REPO:-GuanceCloud/claude-otel-plugin}"
REF="${CLAUDE_OTEL_REF:-main}"
RAW_BASE_URL="${CLAUDE_OTEL_RAW_BASE_URL:-https://raw.githubusercontent.com/${REPO}/${REF}}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}

trap cleanup EXIT INT TERM

case "${1:-}" in
  -h|--help)
    cat <<EOF
Usage:
  install-remote.sh [install options]

Examples:
  curl -fsSL https://raw.githubusercontent.com/GuanceCloud/claude-otel-plugin/main/scripts/install-remote.sh \\
    | bash -s -- --endpoint https://llm-openway.guance.com --x-token <token>

Install options are passed to scripts/install.sh.
EOF
    exit 0
    ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found in PATH" >&2
  exit 1
fi

INSTALL_URL="${RAW_BASE_URL}/scripts/install.sh"
INSTALL_SCRIPT="${TMP_DIR}/install.sh"
curl -fsSL "${INSTALL_URL}" -o "${INSTALL_SCRIPT}"
chmod +x "${INSTALL_SCRIPT}"

bash "${INSTALL_SCRIPT}" "${REPO}" "$@"
