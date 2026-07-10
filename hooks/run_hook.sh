#!/usr/bin/env sh

set -eu

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
HOOK_PY="${PLUGIN_ROOT}/hooks/claude_otel_hook.py"
STATE_DIR="${HOME}/.claude/state"
LOG_FILE="${STATE_DIR}/claude_otel_hook.log"
RUNTIME_DIR="${STATE_DIR}/claude-otel-plugin-runtime"
VENV_DIR="${RUNTIME_DIR}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python3"
LOCK_DIR="${RUNTIME_DIR}/bootstrap.lock"

mkdir -p "${STATE_DIR}" "${RUNTIME_DIR}"

log() {
  timestamp="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true)"
  printf '%s [INFO] %s\n' "${timestamp}" "$1" >>"${LOG_FILE}" 2>/dev/null || true
}

deps_ready() {
  "$1" - <<'PY' >/dev/null 2>&1
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
PY
}

bootstrap_with_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    log "hook skipped: neither uv nor python3 found"
    return 1
  fi

  if [ -x "${PYTHON_BIN}" ] && deps_ready "${PYTHON_BIN}"; then
    exec "${PYTHON_BIN}" "${HOOK_PY}"
  fi

  while ! mkdir "${LOCK_DIR}" 2>/dev/null; do
    sleep 0.1
  done
  trap 'rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true' EXIT INT TERM

  if [ ! -x "${PYTHON_BIN}" ]; then
    log "bootstrapping plugin venv at ${VENV_DIR}"
    if ! python3 -m venv "${VENV_DIR}" >/dev/null 2>&1; then
      log "hook bootstrap failed: python3 -m venv ${VENV_DIR}"
      return 1
    fi
  fi

  if ! deps_ready "${PYTHON_BIN}"; then
    log "installing plugin python dependencies into ${VENV_DIR}"
    if ! "${PYTHON_BIN}" -m pip install \
      --disable-pip-version-check \
      --quiet \
      "opentelemetry-api>=1.25,<2" \
      "opentelemetry-sdk>=1.25,<2" \
      "opentelemetry-exporter-otlp-proto-http>=1.25,<2" \
      >/dev/null 2>&1; then
      log "hook bootstrap failed: pip install OpenTelemetry dependencies"
      return 1
    fi
  fi

  exec "${PYTHON_BIN}" "${HOOK_PY}"
}

if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --script "${HOOK_PY}"
fi

bootstrap_with_python || exit 0
