#!/usr/bin/env bash

set -euo pipefail

PLUGIN_ID="claude-otel-plugin@claude-otel-plugin"
MARKETPLACE_NAME="claude-otel-plugin"
MARKETPLACE_SOURCE="${MARKETPLACE_SOURCE:-$(pwd)}"
SCOPE="${CLAUDE_OTEL_SCOPE:-user}"
WRITE_CONFIG=1
REFRESH=false
INSTALL_TYPE="${CLAUDE_OTEL_INSTALL_TYPE:-gtrace}"
CONFIG_FILE="${GTRACE_CONFIG_FILE:-$HOME/.claude/gtrace.json}"
ENDPOINT="${GTRACE_ENDPOINT:-${CLAUDE_OTEL_ENDPOINT:-}}"
TRACE_PATH="${GTRACE_TRACE_PATH:-${CLAUDE_OTEL_TRACE_PATH:-}}"
METRICS_PATH="${GTRACE_METRICS_PATH:-${CLAUDE_OTEL_METRICS_PATH:-}}"
X_TOKEN="${GTRACE_X_TOKEN:-${X_TOKEN:-}}"
TIMEOUT_MS="${GTRACE_TIMEOUT_MS:-${CLAUDE_OTEL_TIMEOUT_MS:-}}"
USER_ID="${GTRACE_USER_ID:-${CLAUDE_OTEL_USER_ID:-}}"
MAX_CHARS="${GTRACE_MAX_CHARS:-${CLAUDE_OTEL_MAX_CHARS:-}}"
DEBUG_VALUE="${GTRACE_DEBUG:-${CLAUDE_OTEL_DEBUG:-}}"
ENABLED_VALUE="${CLAUDE_OTEL_ENABLED:-}"
HEADERS=()
TAGS=()

log() {
  printf '[install] %s\n' "$1"
}

usage() {
  cat <<EOF
Usage:
  scripts/install.sh [marketplace-source] [options]

Examples:
  scripts/install.sh . --endpoint https://llm-openway.guance.com --x-token <token>
  scripts/install.sh GuanceCloud/claude-otel-plugin --type gtrace --tag env=prod --tag agent_id=claude

Options:
  --refresh               Reinstall the plugin even if it already exists.
  --scope SCOPE           Claude plugin install scope. Default: user.
  --type TYPE             Config preset. Default: gtrace. Values: gtrace, otlp.
  --endpoint URL          Receiver base URL.
  --x-token TOKEN         Dataway/GTrace X-Token.
  --trace-path PATH       Trace route override.
  --metrics-path PATH     Metrics route override.
  --header KEY=VALUE      Extra HTTP header. Can be repeated.
  --tag KEY=VALUE         resourceAttributes entry. Can be repeated.
  --timeout-ms N          OTLP HTTP timeout in milliseconds.
  --user-id VALUE         user_id field attached to exported data.
  --max-chars N           Maximum captured characters.
  --debug                 Enable hook debug logging.
  --no-debug              Disable hook debug logging.
  --enabled BOOL          Set plugin enabled flag in userConfig.
  --config-file PATH      Config file. Default: ~/.claude/gtrace.json.
  --no-config             Install plugin only; do not create or update gtrace.json.
  -h, --help              Show help.

Environment variables:
  CLAUDE_OTEL_ENABLED
  CLAUDE_OTEL_ENDPOINT / GTRACE_ENDPOINT
  CLAUDE_OTEL_TRACE_PATH / GTRACE_TRACE_PATH
  CLAUDE_OTEL_METRICS_PATH / GTRACE_METRICS_PATH
  GTRACE_X_TOKEN / X_TOKEN
  CLAUDE_OTEL_TIMEOUT_MS / GTRACE_TIMEOUT_MS
  CLAUDE_OTEL_USER_ID / GTRACE_USER_ID
  CLAUDE_OTEL_MAX_CHARS / GTRACE_MAX_CHARS
  CLAUDE_OTEL_DEBUG / GTRACE_DEBUG
  GTRACE_CONFIG_FILE
EOF
}

run_python() {
  if command -v python3 >/dev/null 2>&1; then
    python3 "$@"
    return
  fi
  uv run --quiet python "$@"
}

need_runtime() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi
  cat >&2 <<'EOF'
`uv` is required to run the hook on macOS, Linux, and Windows.

- Install uv from https://astral.sh/uv/
EOF
  exit 1
}

normalize_bool() {
  local value="${1:-}"
  case "${value,,}" in
    1|true|yes|on) printf 'true\n' ;;
    0|false|no|off) printf 'false\n' ;;
    "") printf '\n' ;;
    *)
      echo "Invalid boolean value: $value" >&2
      exit 2
      ;;
  esac
}

normalize_type() {
  case "$1" in
    gtrace) printf 'gtrace\n' ;;
    otlp|otel) printf 'otlp\n' ;;
    *)
      echo "Unsupported --type: $1. Supported values: gtrace, otlp" >&2
      exit 2
      ;;
  esac
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --refresh|--reinstall)
      REFRESH=true
      ;;
    --scope)
      shift
      [[ "$#" -gt 0 ]] || { echo "--scope requires a value" >&2; exit 2; }
      SCOPE="$1"
      ;;
    --scope=*)
      SCOPE="${1#*=}"
      ;;
    --type)
      shift
      [[ "$#" -gt 0 ]] || { echo "--type requires a value" >&2; exit 2; }
      INSTALL_TYPE="$(normalize_type "$1")"
      ;;
    --type=*)
      INSTALL_TYPE="$(normalize_type "${1#*=}")"
      ;;
    --endpoint)
      shift
      [[ "$#" -gt 0 ]] || { echo "--endpoint requires a value" >&2; exit 2; }
      ENDPOINT="$1"
      ;;
    --endpoint=*)
      ENDPOINT="${1#*=}"
      ;;
    --x-token)
      shift
      [[ "$#" -gt 0 ]] || { echo "--x-token requires a value" >&2; exit 2; }
      X_TOKEN="$1"
      ;;
    --x-token=*)
      X_TOKEN="${1#*=}"
      ;;
    --trace-path)
      shift
      [[ "$#" -gt 0 ]] || { echo "--trace-path requires a value" >&2; exit 2; }
      TRACE_PATH="$1"
      ;;
    --trace-path=*)
      TRACE_PATH="${1#*=}"
      ;;
    --metrics-path)
      shift
      [[ "$#" -gt 0 ]] || { echo "--metrics-path requires a value" >&2; exit 2; }
      METRICS_PATH="$1"
      ;;
    --metrics-path=*)
      METRICS_PATH="${1#*=}"
      ;;
    --header)
      shift
      [[ "$#" -gt 0 ]] || { echo "--header requires KEY=VALUE" >&2; exit 2; }
      HEADERS+=("$1")
      ;;
    --header=*)
      HEADERS+=("${1#*=}")
      ;;
    --tag)
      shift
      [[ "$#" -gt 0 ]] || { echo "--tag requires KEY=VALUE" >&2; exit 2; }
      TAGS+=("$1")
      ;;
    --tag=*)
      TAGS+=("${1#*=}")
      ;;
    --timeout-ms)
      shift
      [[ "$#" -gt 0 ]] || { echo "--timeout-ms requires a value" >&2; exit 2; }
      TIMEOUT_MS="$1"
      ;;
    --timeout-ms=*)
      TIMEOUT_MS="${1#*=}"
      ;;
    --user-id)
      shift
      [[ "$#" -gt 0 ]] || { echo "--user-id requires a value" >&2; exit 2; }
      USER_ID="$1"
      ;;
    --user-id=*)
      USER_ID="${1#*=}"
      ;;
    --max-chars)
      shift
      [[ "$#" -gt 0 ]] || { echo "--max-chars requires a value" >&2; exit 2; }
      MAX_CHARS="$1"
      ;;
    --max-chars=*)
      MAX_CHARS="${1#*=}"
      ;;
    --debug)
      DEBUG_VALUE="true"
      ;;
    --no-debug)
      DEBUG_VALUE="false"
      ;;
    --enabled)
      shift
      [[ "$#" -gt 0 ]] || { echo "--enabled requires a value" >&2; exit 2; }
      ENABLED_VALUE="$(normalize_bool "$1")"
      ;;
    --enabled=*)
      ENABLED_VALUE="$(normalize_bool "${1#*=}")"
      ;;
    --config-file)
      shift
      [[ "$#" -gt 0 ]] || { echo "--config-file requires a path" >&2; exit 2; }
      CONFIG_FILE="$1"
      ;;
    --config-file=*)
      CONFIG_FILE="${1#*=}"
      ;;
    --no-config)
      WRITE_CONFIG=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
    *)
      if [[ "$MARKETPLACE_SOURCE" == "$(pwd)" ]]; then
        MARKETPLACE_SOURCE="$1"
      else
        echo "Unexpected positional argument: $1" >&2
        exit 2
      fi
      ;;
  esac
  shift
done

if [[ -n "$ENABLED_VALUE" ]]; then
  ENABLED_VALUE="$(normalize_bool "$ENABLED_VALUE")"
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found in PATH" >&2
  exit 1
fi

need_runtime

if [[ -z "$TRACE_PATH" ]]; then
  if [[ "$INSTALL_TYPE" == "gtrace" ]]; then
    TRACE_PATH="v1/write/otel-llm"
  else
    TRACE_PATH="v1/traces"
  fi
fi

if [[ -z "$METRICS_PATH" ]]; then
  if [[ "$INSTALL_TYPE" == "gtrace" ]]; then
    METRICS_PATH="v1/write/otel-metrics"
  else
    METRICS_PATH="v1/metrics"
  fi
fi

if [[ -f "${MARKETPLACE_SOURCE}/.claude-plugin/marketplace.json" ]]; then
  claude plugin validate "${MARKETPLACE_SOURCE}"
fi

build_headers_string() {
  local items=()
  local entry
  if [[ "$INSTALL_TYPE" == "gtrace" ]]; then
    items+=("to_headless=true")
  fi
  if [[ -n "$X_TOKEN" ]]; then
    items+=("X-Token=$X_TOKEN")
  fi
  for entry in "${HEADERS[@]}"; do
    items+=("$entry")
  done
  local IFS=','
  printf '%s\n' "${items[*]}"
}

build_resource_attributes_json() {
  if [[ "${#TAGS[@]}" -eq 0 ]]; then
    printf '\n'
    return
  fi
  printf '%s\n' "${TAGS[@]}" | run_python - <<'PY'
import json
import sys

items = {}
for line in sys.stdin.read().splitlines():
    line = line.strip()
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key and value:
        items[key] = value
print(json.dumps(items, ensure_ascii=False, separators=(",", ":")))
PY
}

PLUGIN_CONFIG_ARGS=()

append_plugin_config() {
  local key="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    return
  fi
  PLUGIN_CONFIG_ARGS+=(--config "${key}=${value}")
}

HEADERS_STRING="$(build_headers_string)"
RESOURCE_ATTRIBUTES_JSON="$(build_resource_attributes_json)"

append_plugin_config "CLAUDE_OTEL_ENABLED" "$ENABLED_VALUE"
append_plugin_config "OTEL_EXPORTER_OTLP_ENDPOINT" "$ENDPOINT"
append_plugin_config "CLAUDE_OTEL_TRACE_PATH" "$TRACE_PATH"
append_plugin_config "CLAUDE_OTEL_METRICS_PATH" "$METRICS_PATH"
append_plugin_config "OTEL_EXPORTER_OTLP_HEADERS" "$HEADERS_STRING"
append_plugin_config "CLAUDE_OTEL_RESOURCE_ATTRIBUTES" "$RESOURCE_ATTRIBUTES_JSON"
append_plugin_config "CLAUDE_OTEL_DEBUG" "$DEBUG_VALUE"
append_plugin_config "CLAUDE_OTEL_MAX_CHARS" "$MAX_CHARS"
append_plugin_config "CLAUDE_OTEL_TIMEOUT_MS" "$TIMEOUT_MS"
append_plugin_config "CLAUDE_OTEL_USER_ID" "$USER_ID"

write_gtrace_config() {
  local headers_json tags_json
  headers_json="$(printf '%s\n' "${HEADERS[@]}" | run_python - <<'PY'
import json
import sys
print(json.dumps([line.strip() for line in sys.stdin.read().splitlines() if line.strip()], ensure_ascii=False))
PY
)"
  tags_json="$(printf '%s\n' "${TAGS[@]}" | run_python - <<'PY'
import json
import sys
print(json.dumps([line.strip() for line in sys.stdin.read().splitlines() if line.strip()], ensure_ascii=False))
PY
)"

  GTRACE_CONFIG_FILE_RUNTIME="$CONFIG_FILE" \
  GTRACE_INSTALL_TYPE_RUNTIME="$INSTALL_TYPE" \
  GTRACE_ENDPOINT_RUNTIME="$ENDPOINT" \
  GTRACE_TRACE_PATH_RUNTIME="$TRACE_PATH" \
  GTRACE_METRICS_PATH_RUNTIME="$METRICS_PATH" \
  GTRACE_X_TOKEN_RUNTIME="$X_TOKEN" \
  GTRACE_HEADERS_RUNTIME="$headers_json" \
  GTRACE_TAGS_RUNTIME="$tags_json" \
  GTRACE_TIMEOUT_MS_RUNTIME="$TIMEOUT_MS" \
  GTRACE_USER_ID_RUNTIME="$USER_ID" \
  GTRACE_MAX_CHARS_RUNTIME="$MAX_CHARS" \
  GTRACE_DEBUG_RUNTIME="$DEBUG_VALUE" \
  GTRACE_ENABLED_RUNTIME="$ENABLED_VALUE" \
  run_python - <<'PY'
import json
import os
from pathlib import Path

config_path = Path(os.environ["GTRACE_CONFIG_FILE_RUNTIME"]).expanduser()
install_type = os.environ.get("GTRACE_INSTALL_TYPE_RUNTIME", "gtrace")
endpoint = os.environ.get("GTRACE_ENDPOINT_RUNTIME", "").strip()
trace_path = os.environ.get("GTRACE_TRACE_PATH_RUNTIME", "").strip()
metrics_path = os.environ.get("GTRACE_METRICS_PATH_RUNTIME", "").strip()
x_token = os.environ.get("GTRACE_X_TOKEN_RUNTIME", "").strip()
timeout_ms = os.environ.get("GTRACE_TIMEOUT_MS_RUNTIME", "").strip()
user_id = os.environ.get("GTRACE_USER_ID_RUNTIME", "").strip()
max_chars = os.environ.get("GTRACE_MAX_CHARS_RUNTIME", "").strip()
debug = os.environ.get("GTRACE_DEBUG_RUNTIME", "").strip()
enabled = os.environ.get("GTRACE_ENABLED_RUNTIME", "").strip()
extra_headers = json.loads(os.environ.get("GTRACE_HEADERS_RUNTIME", "[]"))
extra_tags = json.loads(os.environ.get("GTRACE_TAGS_RUNTIME", "[]"))

config = {}
if config_path.exists():
    raw = config_path.read_text(encoding="utf-8").strip()
    if raw:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            config = parsed

headers = config.get("headers")
if not isinstance(headers, dict):
    headers = {}
resource_attributes = config.get("resourceAttributes")
if not isinstance(resource_attributes, dict):
    resource_attributes = {}

if enabled:
    config["enabled"] = enabled.lower() in {"1", "true", "yes", "on"}
elif "enabled" not in config:
    config["enabled"] = True
if endpoint:
    config["endpoint"] = endpoint
if trace_path:
    config["tracePath"] = trace_path
if metrics_path:
    config["metricsPath"] = metrics_path
if install_type == "gtrace":
    headers.setdefault("to_headless", "true")
if x_token:
    headers["X-Token"] = x_token
for item in extra_headers:
    if "=" not in item:
        continue
    key, value = item.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key and value:
        headers[key] = value
for item in extra_tags:
    if "=" not in item:
        continue
    key, value = item.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key and value:
        resource_attributes[key] = value
if timeout_ms:
    try:
        config["timeout_ms"] = int(timeout_ms)
    except ValueError:
        pass
if max_chars:
    try:
        config["max_chars"] = int(max_chars)
    except ValueError:
        pass
if user_id:
    config["user_id"] = user_id
if debug:
    config["debug"] = debug.lower() in {"1", "true", "yes", "on"}

if headers:
    config["headers"] = headers
else:
    config.pop("headers", None)
if resource_attributes:
    config["resourceAttributes"] = resource_attributes
else:
    config.pop("resourceAttributes", None)

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

if [[ "$WRITE_CONFIG" -eq 1 ]]; then
  if [[ -n "$ENABLED_VALUE" || -n "$ENDPOINT" || -n "$X_TOKEN" || -n "$TIMEOUT_MS" || -n "$USER_ID" || -n "$MAX_CHARS" || -n "$DEBUG_VALUE" || "${#HEADERS[@]}" -gt 0 || "${#TAGS[@]}" -gt 0 || -f "$CONFIG_FILE" ]]; then
    write_gtrace_config
    log "updated $CONFIG_FILE"
  else
    log "skipped gtrace.json because no install-time config was provided"
  fi
else
  log "skipped gtrace.json because --no-config was set"
fi

claude plugin marketplace add "${MARKETPLACE_SOURCE}" >/dev/null 2>&1 || true
claude plugin marketplace update "${MARKETPLACE_NAME}" >/dev/null 2>&1 || true

if $REFRESH || claude plugin list --json | grep -q "\"id\": \"${PLUGIN_ID}\""; then
  claude plugin uninstall "${PLUGIN_ID}" >/dev/null 2>&1 || true
fi

claude plugin install --scope "${SCOPE}" "${PLUGIN_CONFIG_ARGS[@]}" "${PLUGIN_ID}"

cat <<EOF
Plugin installed.

Source: ${MARKETPLACE_SOURCE}
Scope: ${SCOPE}

Next step:
- Restart Claude Code to apply the updated plugin.
EOF
