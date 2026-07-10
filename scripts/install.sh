#!/usr/bin/env sh

set -eu

PLUGIN_ID="claude-otel-plugin@claude-otel-plugin"
MARKETPLACE_NAME="claude-otel-plugin"
MARKETPLACE_SOURCE="${1:-$(pwd)}"

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found in PATH" >&2
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

if [ -f ".claude-plugin/marketplace.json" ]; then
  claude plugin validate .
fi

claude plugin marketplace add "${MARKETPLACE_SOURCE}" >/dev/null 2>&1 || true
claude plugin marketplace update "${MARKETPLACE_NAME}" >/dev/null 2>&1 || true

if claude plugin list --json | grep -q "\"id\": \"${PLUGIN_ID}\""; then
  claude plugin update "${PLUGIN_ID}"
else
  claude plugin install "${PLUGIN_ID}"
fi

cat <<'EOF'
Plugin installed.

Next step:
- Restart Claude Code to apply the updated plugin.
EOF
