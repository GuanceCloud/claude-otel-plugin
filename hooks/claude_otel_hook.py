#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "opentelemetry-api>=1.25,<2",
#   "opentelemetry-sdk>=1.25,<2",
#   "opentelemetry-exporter-otlp-proto-http>=1.25,<2",
# ]
# ///
"""
Claude Code transcript -> OpenTelemetry traces hook.

The hook is intentionally fail-open: collection failures must not affect Claude
Code execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import sys
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATE_DIR = Path.home() / ".claude" / "state"
LOG_FILE = STATE_DIR / "claude_otel_hook.log"
STATE_FILE = STATE_DIR / "claude_otel_state.json"
LOCK_FILE = STATE_DIR / "claude_otel_state.lock"
DEFAULT_TRACE_PATH = "v1/traces"
DEFAULT_METRICS_PATH = "v1/metrics"
DEFAULT_MAX_CHARS = 20_000
DEFAULT_TIMEOUT_MS = 10_000
AGENT_RUNTIME = "claude"
SKILL_NAME_PATTERN = re.compile(r"^/([A-Za-z0-9:_-]+)\b")


def _plugin_opt(env: Dict[str, str], name: str) -> Optional[str]:
    value = env.get(f"CLAUDE_PLUGIN_OPTION_{name}")
    return value if value not in (None, "") else None


def _env_opt(env: Dict[str, str], *names: str) -> Optional[str]:
    for name in names:
        value = env.get(name)
        if value not in (None, ""):
            return value
    return None


def parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def parse_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip())
    except Exception:
        return default


def read_json_if_exists(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass
    return {}


def parse_key_value_string(value: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for entry in value.split(","):
        item = entry.strip()
        if not item or "=" not in item:
            continue
        key, raw = item.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if key and raw:
            out[key] = raw
    return out


def parse_headers(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        return {
            str(k): str(v)
            for k, v in value.items()
            if k and v is not None and str(v).strip()
        }
    if not isinstance(value, str) or not value.strip():
        return {}
    trimmed = value.strip()
    if trimmed.startswith("{"):
        try:
            parsed = json.loads(trimmed)
            return parse_headers(parsed)
        except Exception:
            return {}
    return parse_key_value_string(trimmed)


def parse_resource_attributes(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
            items = parsed.items() if isinstance(parsed, dict) else []
        except Exception:
            items = []
    elif isinstance(value, str):
        items = parse_key_value_string(value).items()
    else:
        items = []

    out: Dict[str, Any] = {}
    for key, item in items:
        if not key or item in (None, ""):
            continue
        if isinstance(item, (str, bool, int, float)):
            out[str(key)] = item
        else:
            out[str(key)] = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return out


def normalize_endpoint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    trimmed = value.strip()
    return trimmed.rstrip("/") if trimmed else None


def normalize_path(value: Any, default: str = DEFAULT_TRACE_PATH) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip().strip("/")


def join_endpoint_path(endpoint: str, path: str) -> str:
    normalized_endpoint = endpoint.rstrip("/")
    normalized_path = path.strip("/")
    if not normalized_path:
        return normalized_endpoint
    endpoint_no_query = normalized_endpoint.split("?", 1)[0].split("#", 1)[0]
    if endpoint_no_query.rstrip("/").endswith(f"/{normalized_path}"):
        return normalized_endpoint
    return f"{normalized_endpoint}/{normalized_path}"


@dataclass
class HookConfig:
    enabled: bool
    endpoint: Optional[str]
    traces_endpoint: Optional[str]
    metrics_endpoint: Optional[str]
    trace_path: str
    metrics_path: str
    headers: Dict[str, str]
    resource_attributes: Dict[str, Any]
    debug: bool
    max_chars: int
    timeout_ms: int
    user_id: Optional[str]
    log_file: Path

    @property
    def trace_url(self) -> Optional[str]:
        if self.traces_endpoint:
            return self.traces_endpoint
        if not self.endpoint:
            return None
        return join_endpoint_path(self.endpoint, self.trace_path)

    @property
    def metrics_url(self) -> Optional[str]:
        if self.metrics_endpoint:
            return self.metrics_endpoint
        if not self.endpoint:
            return None
        return join_endpoint_path(self.endpoint, self.metrics_path)


@dataclass
class RuntimeMetadata:
    agent_version: Optional[str]
    host: Optional[str]


@dataclass
class SkillDefinition:
    name: str
    description: Optional[str] = None
    path: Optional[str] = None
    source_type: Optional[str] = None
    version: Optional[str] = None


@dataclass
class SkillInvocation:
    name: str
    call_id: str
    description: Optional[str] = None
    path: Optional[str] = None
    source_type: Optional[str] = None
    version: Optional[str] = None
    result_status: str = "completed"


@dataclass
class TraceExportTracker:
    export_calls: int = 0
    had_failure: bool = False
    last_result: Optional[str] = None
    last_error: Optional[str] = None

    def export_ok(self, emitted: int) -> bool:
        if emitted <= 0:
            return True
        return self.export_calls > 0 and not self.had_failure


class TrackingSpanExporter:
    def __init__(self, exporter: Any, tracker: TraceExportTracker):
        self._exporter = exporter
        self._tracker = tracker

    def export(self, spans: Any) -> Any:
        self._tracker.export_calls += 1
        try:
            result = self._exporter.export(spans)
        except Exception as exc:
            self._tracker.had_failure = True
            self._tracker.last_error = f"{type(exc).__name__}: {exc}"
            raise
        self._tracker.last_result = getattr(result, "name", str(result))
        if self._tracker.last_result != "SUCCESS":
            self._tracker.had_failure = True
        return result

    def force_flush(self, timeout_millis: int = 30_000) -> Any:
        if hasattr(self._exporter, "force_flush"):
            return self._exporter.force_flush(timeout_millis=timeout_millis)
        return True

    def shutdown(self) -> Any:
        return self._exporter.shutdown()


def resolve_config(
    *,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> HookConfig:
    env = env or dict(os.environ)
    home = home or Path.home()
    cwd = cwd or Path.cwd()

    defaults: Dict[str, Any] = {
        "tracePath": DEFAULT_TRACE_PATH,
        "metricsPath": DEFAULT_METRICS_PATH,
        "max_chars": DEFAULT_MAX_CHARS,
        "timeout_ms": DEFAULT_TIMEOUT_MS,
        "debug": False,
        "headers": {},
        "resourceAttributes": {
            "service.name": "gtrace-claude-code",
            "telemetry.sdk.name": "gtrace",
            "telemetry.sdk.version": "0.1.6",
            "agent_runtime": AGENT_RUNTIME,
            "agent_source": AGENT_RUNTIME,
            "agent_type": "assistant",
        },
    }

    ordinary_env = {
        "enabled": parse_bool(_env_opt(env, "CLAUDE_OTEL_ENABLED", "TRACE_TO_GTRACE")),
        "endpoint": _env_opt(env, "OTEL_EXPORTER_OTLP_ENDPOINT", "CLAUDE_OTEL_ENDPOINT", "GTRACE_ENDPOINT"),
        "otel_traces_url": _env_opt(env, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "CLAUDE_OTEL_TRACES_ENDPOINT"),
        "otel_metrics_url": _env_opt(env, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "CLAUDE_OTEL_METRICS_ENDPOINT"),
        "tracePath": _env_opt(env, "CLAUDE_OTEL_TRACE_PATH", "GTRACE_TRACE_PATH"),
        "metricsPath": _env_opt(env, "CLAUDE_OTEL_METRICS_PATH", "GTRACE_METRICS_PATH"),
        "headers": parse_headers(_env_opt(env, "OTEL_EXPORTER_OTLP_HEADERS", "CLAUDE_OTEL_HEADERS")),
        "resourceAttributes": parse_resource_attributes(
            _env_opt(env, "OTEL_RESOURCE_ATTRIBUTES", "CLAUDE_OTEL_RESOURCE_ATTRIBUTES")
        ),
        "debug": parse_bool(_env_opt(env, "CLAUDE_OTEL_DEBUG", "GTRACE_DEBUG")),
        "max_chars": _env_opt(env, "CLAUDE_OTEL_MAX_CHARS", "GTRACE_MAX_CHARS"),
        "timeout_ms": _env_opt(env, "CLAUDE_OTEL_TIMEOUT_MS", "GTRACE_TIMEOUT_MS"),
        "user_id": _env_opt(env, "CLAUDE_OTEL_USER_ID", "GTRACE_USER_ID"),
    }
    ordinary_env = {k: v for k, v in ordinary_env.items() if v not in (None, {}, "")}

    local_config = read_json_if_exists(cwd / ".claude" / "gtrace.json")
    global_config = read_json_if_exists(home / ".claude" / "gtrace.json")

    plugin_env = {
        "enabled": parse_bool(_plugin_opt(env, "CLAUDE_OTEL_ENABLED")),
        "endpoint": _plugin_opt(env, "OTEL_EXPORTER_OTLP_ENDPOINT"),
        "otel_traces_url": _plugin_opt(env, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
        "otel_metrics_url": _plugin_opt(env, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
        "tracePath": _plugin_opt(env, "CLAUDE_OTEL_TRACE_PATH"),
        "metricsPath": _plugin_opt(env, "CLAUDE_OTEL_METRICS_PATH"),
        "headers": parse_headers(_plugin_opt(env, "OTEL_EXPORTER_OTLP_HEADERS") or ""),
        "resourceAttributes": parse_resource_attributes(_plugin_opt(env, "CLAUDE_OTEL_RESOURCE_ATTRIBUTES") or ""),
        "debug": parse_bool(_plugin_opt(env, "CLAUDE_OTEL_DEBUG")),
        "max_chars": _plugin_opt(env, "CLAUDE_OTEL_MAX_CHARS"),
        "timeout_ms": _plugin_opt(env, "CLAUDE_OTEL_TIMEOUT_MS"),
        "user_id": _plugin_opt(env, "CLAUDE_OTEL_USER_ID"),
    }
    plugin_env = {k: v for k, v in plugin_env.items() if v not in (None, {}, "")}

    merged: Dict[str, Any] = {}
    for source in (defaults, plugin_env, global_config, local_config, ordinary_env):
        for key, value in source.items():
            if key in {"headers", "resourceAttributes"}:
                merged[key] = {**parse_headers(merged.get(key, {})), **parse_headers(value)} if key == "headers" else {
                    **parse_resource_attributes(merged.get(key, {})),
                    **parse_resource_attributes(value),
                }
            elif value not in (None, ""):
                merged[key] = value

    endpoint = normalize_endpoint(merged.get("endpoint") or merged.get("base_url"))
    traces_endpoint = normalize_endpoint(
        merged.get("otel_traces_url")
        or merged.get("tracesEndpoint")
        or merged.get("traceEndpoint")
    )
    metrics_endpoint = normalize_endpoint(
        merged.get("otel_metrics_url")
        or merged.get("metricsEndpoint")
        or merged.get("metricEndpoint")
    )
    enabled = parse_bool(merged.get("enabled"))
    if enabled is None:
        enabled = bool(endpoint or traces_endpoint or metrics_endpoint)

    trace_path = normalize_path(merged.get("tracePath"), DEFAULT_TRACE_PATH)
    metrics_path = normalize_path(merged.get("metricsPath"), DEFAULT_METRICS_PATH)
    if metrics_path == DEFAULT_METRICS_PATH and trace_path == "v1/write/otel-llm":
        metrics_path = "v1/write/otel-metrics"

    log_file = Path(str(merged.get("hook_log_file") or home / ".claude" / "state" / "claude_otel_hook.log"))

    return HookConfig(
        enabled=bool(enabled),
        endpoint=endpoint,
        traces_endpoint=traces_endpoint,
        metrics_endpoint=metrics_endpoint,
        trace_path=trace_path,
        metrics_path=metrics_path,
        headers=parse_headers(merged.get("headers", {})),
        resource_attributes=parse_resource_attributes(merged.get("resourceAttributes", {})),
        debug=bool(parse_bool(merged.get("debug"))),
        max_chars=parse_int(merged.get("max_chars"), DEFAULT_MAX_CHARS),
        timeout_ms=parse_int(merged.get("timeout_ms"), DEFAULT_TIMEOUT_MS),
        user_id=str(merged.get("user_id")) if merged.get("user_id") else None,
        log_file=log_file,
    )


_LOGGER: Optional[logging.Logger] = None


def get_logger(config: Optional[HookConfig] = None) -> Optional[logging.Logger]:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    try:
        log_file = config.log_file if config else LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("claude_otel_hook")
        logger.setLevel(logging.DEBUG if config and config.debug else logging.INFO)
        if not logger.handlers:
            handler = RotatingFileHandler(str(log_file), maxBytes=5_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
        _LOGGER = logger
        return _LOGGER
    except Exception:
        return None


def log(config: Optional[HookConfig], level: int, message: str, **extra: Any) -> None:
    logger = get_logger(config)
    if not logger:
        return
    try:
        if extra:
            logger.log(level, "%s %s", message, json.dumps(extra, ensure_ascii=False, sort_keys=True))
        else:
            logger.log(level, message)
    except Exception:
        pass


class FileLock:
    def __init__(self, path: Path, timeout_s: float = 2.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fh: Any = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+", encoding="utf-8")
        try:
            import fcntl
        except ImportError:
            return self
        deadline = time.time() + self.timeout_s
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > deadline:
                    raise TimeoutError(f"could not acquire lock {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass


def load_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            parsed = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        for key in list(state.keys()):
            entry = state.get(key)
            if not isinstance(entry, dict):
                continue
            updated = entry.get("updated")
            if not isinstance(updated, str):
                continue
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                del state[key]
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def state_key(session_id: str, transcript_path: str) -> str:
    raw = f"{session_id}::{transcript_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class SessionState:
    offset: int = 0
    buffer: str = ""
    turn_count: int = 0
    pending_messages: List[Dict[str, Any]] = None
    skill_catalog: Dict[str, Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.pending_messages is None:
            self.pending_messages = []
        if self.skill_catalog is None:
            self.skill_catalog = {}


def load_session_state(global_state: Dict[str, Any], key: str) -> SessionState:
    raw = global_state.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    pending_messages = raw.get("pending_messages")
    if not isinstance(pending_messages, list):
        pending_messages = []
    skill_catalog = raw.get("skill_catalog")
    if not isinstance(skill_catalog, dict):
        skill_catalog = {}
    return SessionState(
        offset=parse_int(raw.get("offset"), 0),
        buffer=str(raw.get("buffer") or ""),
        turn_count=parse_int(raw.get("turn_count"), 0),
        pending_messages=[item for item in pending_messages if isinstance(item, dict)],
        skill_catalog={
            str(name): value
            for name, value in skill_catalog.items()
            if isinstance(name, str) and isinstance(value, dict)
        },
    )


def write_session_state(global_state: Dict[str, Any], key: str, state: SessionState) -> None:
    global_state[key] = {
        "offset": state.offset,
        "buffer": state.buffer,
        "turn_count": state.turn_count,
        "pending_messages": state.pending_messages,
        "skill_catalog": state.skill_catalog,
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def read_hook_payload(stdin_text: Optional[str] = None) -> Dict[str, Any]:
    try:
        data = sys.stdin.read() if stdin_text is None else stdin_text
        if not data.strip():
            return {}
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def extract_session_and_transcript(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[Path]]:
    session_id = (
        payload.get("session_id")
        or payload.get("sessionId")
        or (payload.get("session") or {}).get("id")
    )
    transcript = (
        payload.get("transcript_path")
        or payload.get("transcriptPath")
        or (payload.get("transcript") or {}).get("path")
    )
    if not isinstance(session_id, str) or not session_id:
        session_id = None
    if not isinstance(transcript, str) or not transcript:
        return session_id, None
    try:
        return session_id, Path(transcript).expanduser().resolve()
    except Exception:
        return session_id, None


def get_content(msg: Dict[str, Any]) -> Any:
    nested = msg.get("message")
    if isinstance(nested, dict):
        return nested.get("content")
    return msg.get("content")


def get_role(msg: Dict[str, Any]) -> Optional[str]:
    direct = msg.get("type")
    if direct in {"user", "assistant"}:
        return str(direct)
    nested = msg.get("message")
    if isinstance(nested, dict) and nested.get("role") in {"user", "assistant"}:
        return str(nested.get("role"))
    return None


def iter_blocks(content: Any, block_type: str) -> Iterable[Dict[str, Any]]:
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == block_type:
                yield item


def iter_tool_uses(content: Any) -> List[Dict[str, Any]]:
    return list(iter_blocks(content, "tool_use"))


def iter_tool_results(content: Any) -> List[Dict[str, Any]]:
    return list(iter_blocks(content, "tool_result"))


def is_tool_result_message(msg: Dict[str, Any]) -> bool:
    return get_role(msg) == "user" and any(True for _ in iter_tool_results(get_content(msg)))


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return ""


def truncate_text(value: Any, max_chars: int) -> Tuple[str, Dict[str, Any]]:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    original_len = len(text)
    if original_len <= max_chars:
        return text, {"truncated": False, "orig_len": original_len}
    clipped = text[:max_chars]
    return clipped, {
        "truncated": True,
        "orig_len": original_len,
        "kept_len": len(clipped),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def message_value(value: Any, max_chars: int) -> Optional[str]:
    text, _ = truncate_text(value, max_chars)
    return text if text else None


def text_part(value: Any, max_chars: int) -> Optional[Dict[str, Any]]:
    content = message_value(value, max_chars)
    return {"type": "text", "content": content} if content else None


def tool_call_part(tool: Dict[str, Any], max_chars: int) -> Optional[Dict[str, Any]]:
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return None
    part: Dict[str, Any] = {"type": "tool_call", "name": name}
    tool_id = tool.get("id")
    if tool_id:
        part["id"] = str(tool_id)
    arguments = message_value(tool.get("input"), max_chars)
    if arguments:
        part["arguments"] = arguments
    return part


def tool_call_response_part(tool_result: Dict[str, Any], max_chars: int) -> Optional[Dict[str, Any]]:
    response = message_value(tool_result.get("output"), max_chars)
    error = message_value(tool_result.get("error"), max_chars)
    if response is None and error is None:
        return None
    part: Dict[str, Any] = {"type": "tool_call_response"}
    tool_id = tool_result.get("id")
    if tool_id:
        part["id"] = str(tool_id)
    if error is None:
        part["response"] = response
    else:
        payload: Dict[str, Any] = {}
        if response is not None:
            payload["output"] = response
        payload["error"] = error
        part["response"] = payload
    return part


def build_input_messages(user_text: str, tool_results: List[Dict[str, Any]], max_chars: int) -> Optional[List[Dict[str, Any]]]:
    messages: List[Dict[str, Any]] = []
    user_part = text_part(user_text, max_chars)
    if user_part:
        messages.append({"role": "user", "parts": [user_part]})

    for tool_result in tool_results:
        part = tool_call_response_part(tool_result, max_chars)
        if not part:
            continue
        message: Dict[str, Any] = {"role": "tool", "parts": [part]}
        name = tool_result.get("name")
        if name:
            message["name"] = name
        messages.append(message)
    return messages or None


def build_output_messages(assistant_text: str, tool_uses: List[Dict[str, Any]], max_chars: int, finish_reason: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    parts: List[Dict[str, Any]] = []
    text_message_part = text_part(assistant_text, max_chars)
    if text_message_part:
        parts.append(text_message_part)
    for tool in tool_uses:
        part = tool_call_part(tool, max_chars)
        if part:
            parts.append(part)
    if not parts:
        return None
    message: Dict[str, Any] = {"role": "assistant", "parts": parts}
    if finish_reason:
        message["finish_reason"] = finish_reason
    return [message]


def _content_block_key(block: Any) -> Tuple[str, str]:
    if isinstance(block, str):
        return ("str", block)
    if not isinstance(block, dict):
        return ("json", json.dumps(block, ensure_ascii=False, sort_keys=True))
    block_type = str(block.get("type") or "")
    if block_type == "tool_use":
        return (block_type, str(block.get("id") or ""))
    if block_type in {"text", "input_text", "output_text"}:
        return (block_type, str(block.get("text") or ""))
    return (block_type, json.dumps(block, ensure_ascii=False, sort_keys=True))


def merge_content(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, list) and isinstance(incoming, list):
        merged: List[Any] = []
        seen = set()
        for block in existing + incoming:
            key = _content_block_key(block)
            if key in seen:
                continue
            seen.add(key)
            merged.append(block)
        return merged
    if incoming not in (None, "", []):
        return incoming
    return existing


def merge_assistant_message(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)

    existing_ts = parse_ts(existing)
    incoming_ts = parse_ts(incoming)
    if existing_ts is None and incoming_ts is not None:
        merged["timestamp"] = incoming["timestamp"]
    elif existing_ts is not None and incoming_ts is not None and incoming_ts < existing_ts:
        merged["timestamp"] = incoming["timestamp"]

    for key, value in incoming.items():
        if key == "message" and isinstance(value, dict):
            current_msg = dict(merged.get("message") or {})
            incoming_msg = value
            for nested_key, nested_value in incoming_msg.items():
                if nested_key == "content":
                    current_msg["content"] = merge_content(current_msg.get("content"), nested_value)
                elif nested_value not in (None, ""):
                    current_msg[nested_key] = nested_value
            merged["message"] = current_msg
        elif value not in (None, "") and key != "timestamp":
            merged[key] = value
    return merged


def parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, dict):
        value = value.get("timestamp")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_simple_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    header = text[4:end]
    body = text[end + 5:]
    meta: Dict[str, str] = {}
    for raw_line in header.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip("'").strip('"')
        if key and value:
            meta[key] = value
    return meta, body


def extract_body_description(text: str) -> Optional[str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return None


def parse_skill_markdown(path: Path) -> Tuple[Dict[str, str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, None
    meta, body = parse_simple_frontmatter(text)
    description = meta.get("description") or extract_body_description(body)
    return meta, description


def parse_package_version(path: Path) -> Optional[str]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = parsed.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return None


def skill_search_roots(cwd: Path, home: Optional[Path] = None) -> List[Tuple[str, Path]]:
    home = home or Path.home()
    roots: List[Tuple[str, Path]] = [
        ("workspace", cwd / ".claude" / "skills"),
        ("user", home / ".claude" / "skills"),
        ("system", home / ".claude" / "skills" / ".system"),
        ("system", home / ".codex" / "skills" / ".system"),
    ]
    seen = set()
    unique: List[Tuple[str, Path]] = []
    for source_type, root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append((source_type, root))
    return unique


def resolve_skill_definition(
    skill_name: str,
    cwd: Path,
    *,
    home: Optional[Path] = None,
    fallback_description: Optional[str] = None,
) -> SkillDefinition:
    fallback = SkillDefinition(
        name=skill_name,
        description=fallback_description,
        source_type="system",
    )
    normalized_names = [skill_name]
    if ":" in skill_name:
        normalized_names.append(skill_name.split(":")[-1])
    if "/" in skill_name:
        normalized_names.append(skill_name.rsplit("/", 1)[-1])

    for source_type, root in skill_search_roots(cwd, home):
        if not root.exists():
            continue
        for candidate_name in normalized_names:
            direct = root / candidate_name / "SKILL.md"
            if direct.exists():
                meta, description = parse_skill_markdown(direct)
                version = meta.get("version")
                if not version:
                    current = direct.parent
                    while True:
                        package_version = parse_package_version(current / "package.json")
                        if package_version:
                            version = package_version
                            break
                        if current == root or current.parent == current:
                            break
                        current = current.parent
                return SkillDefinition(
                    name=direct.parent.name,
                    description=description or fallback_description,
                    path=str(direct.resolve()),
                    source_type=source_type,
                    version=version,
                )
        try:
            for skill_file in root.rglob("SKILL.md"):
                if skill_file.parent.name not in normalized_names:
                    continue
                meta, description = parse_skill_markdown(skill_file)
                version = meta.get("version")
                if not version:
                    current = skill_file.parent
                    while True:
                        package_version = parse_package_version(current / "package.json")
                        if package_version:
                            version = package_version
                            break
                        if current == root or current.parent == current:
                            break
                        current = current.parent
                return SkillDefinition(
                    name=skill_file.parent.name,
                    description=description or fallback_description,
                    path=str(skill_file.resolve()),
                    source_type=source_type,
                    version=version,
                )
        except Exception:
            continue
    return fallback


def extract_skill_listing_map(msg: Dict[str, Any], cwd: Path, *, home: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    attachment = msg.get("attachment")
    if not isinstance(attachment, dict) or attachment.get("type") != "skill_listing":
        return {}
    names = attachment.get("names")
    if not isinstance(names, list):
        return {}
    descriptions: Dict[str, str] = {}
    content = attachment.get("content")
    if isinstance(content, str):
        for raw_line in content.splitlines():
            line = raw_line.strip()
            match = re.match(r"^-\s*([A-Za-z0-9:_-]+):\s*(.+)$", line)
            if match:
                descriptions[match.group(1)] = match.group(2).strip()
    out: Dict[str, Dict[str, Any]] = {}
    for raw_name in names:
        if not isinstance(raw_name, str) or not raw_name:
            continue
        skill = resolve_skill_definition(raw_name, cwd, home=home, fallback_description=descriptions.get(raw_name))
        out[skill.name] = {
            "name": skill.name,
            "description": skill.description,
            "path": skill.path,
            "source_type": skill.source_type,
            "version": skill.version,
        }
    return out


def merge_skill_catalog(existing: Dict[str, Dict[str, Any]], messages: List[Dict[str, Any]], cwd: Path, *, home: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {
        str(name): dict(value)
        for name, value in existing.items()
        if isinstance(name, str) and isinstance(value, dict)
    }
    for msg in messages:
        catalog.update(extract_skill_listing_map(msg, cwd, home=home))
    return catalog


def detect_active_skill(turn: Turn, skill_catalog: Dict[str, Dict[str, Any]], session_id: str, turn_num: int) -> Optional[SkillInvocation]:
    user_text = extract_text(get_content(turn.user_msg)).strip()
    match = SKILL_NAME_PATTERN.match(user_text)
    if not match:
        return None
    requested_name = match.group(1)
    skill = skill_catalog.get(requested_name)
    if not skill:
        return None
    result_status = "completed"
    if any(bool(result.get("is_error")) for result in turn.tool_results_by_id.values()):
        result_status = "error"
    call_id = f"skillu_{hashlib.sha256(f'{session_id}:{turn_num}:{requested_name}'.encode('utf-8')).hexdigest()[:16]}"
    return SkillInvocation(
        name=str(skill.get("name") or requested_name),
        call_id=call_id,
        description=str(skill.get("description")) if skill.get("description") else None,
        path=str(skill.get("path")) if skill.get("path") else None,
        source_type=str(skill.get("source_type")) if skill.get("source_type") else None,
        version=str(skill.get("version")) if skill.get("version") else None,
        result_status=result_status,
    )


def to_ns(ts: Optional[datetime]) -> Optional[int]:
    if ts is None:
        return None
    return int(ts.timestamp() * 1_000_000_000)


def get_message_id(msg: Dict[str, Any]) -> Optional[str]:
    nested = msg.get("message")
    if isinstance(nested, dict) and isinstance(nested.get("id"), str):
        return nested["id"]
    if isinstance(msg.get("uuid"), str):
        return msg["uuid"]
    return None


def get_model(msg: Dict[str, Any]) -> str:
    nested = msg.get("message")
    if isinstance(nested, dict) and isinstance(nested.get("model"), str):
        return nested["model"]
    if isinstance(msg.get("model"), str):
        return msg["model"]
    return "claude"


def get_stop_reason(msg: Dict[str, Any]) -> Optional[str]:
    nested = msg.get("message")
    if isinstance(nested, dict) and isinstance(nested.get("stop_reason"), str):
        return nested["stop_reason"]
    if isinstance(msg.get("stop_reason"), str):
        return msg["stop_reason"]
    return None


def get_usage(msg: Dict[str, Any]) -> Dict[str, int]:
    nested = msg.get("message")
    usage = nested.get("usage") if isinstance(nested, dict) else msg.get("usage")
    if not isinstance(usage, dict):
        return {}
    mapping = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
    }
    out: Dict[str, int] = {}
    for src, dst in mapping.items():
        value = usage.get(src)
        if isinstance(value, int) and value >= 0:
            out[dst] = value
    if out and "total_tokens" not in out:
        out["total_tokens"] = out.get("input_tokens", 0) + out.get("output_tokens", 0)
    return out


def usage_details(raw_usage: Dict[str, int]) -> Dict[str, int]:
    if not raw_usage:
        return {}
    input_tokens = raw_usage.get("input_tokens")
    output = raw_usage.get("output_tokens")
    cache_read = raw_usage.get("cache_read_input_tokens", 0)
    cache_creation = raw_usage.get("cache_creation_input_tokens", 0)
    full_input = None
    if isinstance(input_tokens, int):
        full_input = input_tokens
        if isinstance(cache_read, int):
            full_input += cache_read
        if isinstance(cache_creation, int):
            full_input += cache_creation
    details: Dict[str, int] = {}
    if isinstance(full_input, int):
        details["input"] = full_input
    if isinstance(output, int):
        details["output"] = output
    if isinstance(cache_read, int) and cache_read > 0:
        details["cache_read_input_tokens"] = cache_read
    if isinstance(cache_creation, int) and cache_creation > 0:
        details["cache_creation_input_tokens"] = cache_creation
    return details


def merge_usage(total: Dict[str, int], usage: Dict[str, int]) -> Dict[str, int]:
    for key in (
        "input",
        "output",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        if isinstance(usage.get(key), int):
            total[key] = total.get(key, 0) + usage[key]
    return total


def read_new_jsonl(transcript_path: Path, state: SessionState) -> Tuple[List[Dict[str, Any]], SessionState]:
    if not transcript_path.exists():
        return [], state
    try:
        file_size = transcript_path.stat().st_size
        if file_size < state.offset:
            state.offset = 0
            state.buffer = ""
        with transcript_path.open("rb") as handle:
            handle.seek(state.offset)
            chunk = handle.read()
            state.offset = handle.tell()
    except Exception:
        return [], state
    if not chunk:
        return [], state
    text = chunk.decode("utf-8", errors="replace")
    combined = state.buffer + text
    lines = combined.split("\n")
    state.buffer = lines[-1]
    messages: List[Dict[str, Any]] = []
    for raw in lines[:-1]:
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                messages.append(parsed)
        except Exception:
            continue
    return messages, state


@dataclass
class Turn:
    user_msg: Dict[str, Any]
    assistant_msgs: List[Dict[str, Any]]
    tool_results_by_id: Dict[str, Dict[str, Any]]
    injected_by_tool_id: Dict[str, str]
    turn_duration_ms: Optional[float] = None


def _build_turns(messages: List[Dict[str, Any]], *, keep_incomplete_tail: bool) -> Tuple[List[Turn], List[Dict[str, Any]]]:
    turns: List[Turn] = []
    current_user: Optional[Dict[str, Any]] = None
    current_turn_messages: List[Dict[str, Any]] = []
    assistant_order: List[str] = []
    assistant_latest: Dict[str, Dict[str, Any]] = {}
    tool_results_by_id: Dict[str, Dict[str, Any]] = {}
    injected_by_tool_id: Dict[str, str] = {}
    turn_duration_ms: Optional[float] = None

    def flush() -> None:
        nonlocal current_user
        if current_user is None or not assistant_latest:
            return
        turns.append(
            Turn(
                user_msg=current_user,
                assistant_msgs=[assistant_latest[mid] for mid in assistant_order if mid in assistant_latest],
                tool_results_by_id=dict(tool_results_by_id),
                injected_by_tool_id=dict(injected_by_tool_id),
                turn_duration_ms=turn_duration_ms,
            )
        )

    for msg in messages:
        if current_user is not None and (
            msg.get("isMeta")
            or is_tool_result_message(msg)
            or (msg.get("type") == "system" and msg.get("subtype") == "turn_duration")
            or get_role(msg) == "assistant"
        ):
            current_turn_messages.append(msg)

        if msg.get("isMeta"):
            source_tool_id = msg.get("sourceToolUseID")
            text = extract_text(get_content(msg))
            if source_tool_id and text:
                injected_by_tool_id[str(source_tool_id)] = text
            continue

        if is_tool_result_message(msg):
            row_ts = msg.get("timestamp")
            tool_use_result = msg.get("toolUseResult")
            duration_seconds = None
            if isinstance(tool_use_result, dict):
                raw_duration = tool_use_result.get("durationSeconds")
                if isinstance(raw_duration, (int, float)) and raw_duration >= 0:
                    duration_seconds = float(raw_duration)
                elif isinstance(tool_use_result.get("durationMs"), (int, float)) and tool_use_result.get("durationMs") >= 0:
                    duration_seconds = float(tool_use_result.get("durationMs")) / 1000.0
            for result in iter_tool_results(get_content(msg)):
                tool_id = result.get("tool_use_id")
                if tool_id:
                    tool_results_by_id[str(tool_id)] = {
                        "content": result.get("content"),
                        "is_error": result.get("is_error"),
                        "timestamp": row_ts,
                        "duration_seconds": duration_seconds,
                    }
            continue

        if msg.get("type") == "system" and msg.get("subtype") == "turn_duration" and current_user is not None:
            raw_duration_ms = msg.get("durationMs")
            if isinstance(raw_duration_ms, (int, float)) and raw_duration_ms >= 0:
                turn_duration_ms = float(raw_duration_ms)
            continue

        role = get_role(msg)
        if role == "user":
            flush()
            current_user = msg
            current_turn_messages = [msg]
            assistant_order = []
            assistant_latest = {}
            tool_results_by_id = {}
            injected_by_tool_id = {}
            turn_duration_ms = None
            continue

        if role == "assistant" and current_user is not None:
            msg_id = get_message_id(msg) or f"noid:{len(assistant_order)}"
            if msg_id not in assistant_latest:
                assistant_order.append(msg_id)
                assistant_latest[msg_id] = msg
            else:
                assistant_latest[msg_id] = merge_assistant_message(assistant_latest[msg_id], msg)

    pending_messages: List[Dict[str, Any]] = []
    if current_user is not None:
        if keep_incomplete_tail and turn_duration_ms is None:
            pending_messages = list(current_turn_messages)
        else:
            flush()
    return turns, pending_messages


def build_turns_with_pending(messages: List[Dict[str, Any]]) -> Tuple[List[Turn], List[Dict[str, Any]]]:
    return _build_turns(messages, keep_incomplete_tail=True)


def build_turns(messages: List[Dict[str, Any]]) -> List[Turn]:
    turns, _ = _build_turns(messages, keep_incomplete_tail=False)
    return turns


def hook_event_name(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("hook_event_name", "hookEventName", "event", "event_name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def has_user_and_assistant(messages: List[Dict[str, Any]]) -> bool:
    saw_user = False
    saw_assistant = False
    for msg in messages:
        role = get_role(msg)
        if role == "user" and not is_tool_result_message(msg):
            saw_user = True
        elif role == "assistant":
            saw_assistant = True
    return saw_user and saw_assistant


def last_assistant_message(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for msg in reversed(messages):
        if get_role(msg) == "assistant":
            return msg
    return None


def unresolved_tool_use_ids(messages: List[Dict[str, Any]]) -> List[str]:
    tool_use_ids: List[str] = []
    resolved_ids = set()
    for msg in messages:
        if get_role(msg) == "assistant":
            for tool in iter_tool_uses(get_content(msg)):
                tool_id = tool.get("id")
                if isinstance(tool_id, str) and tool_id:
                    tool_use_ids.append(tool_id)
        elif is_tool_result_message(msg):
            for result in iter_tool_results(get_content(msg)):
                tool_id = result.get("tool_use_id")
                if isinstance(tool_id, str) and tool_id:
                    resolved_ids.add(tool_id)
    return [tool_id for tool_id in tool_use_ids if tool_id not in resolved_ids]


def pending_turn_is_complete(messages: List[Dict[str, Any]]) -> bool:
    if not has_user_and_assistant(messages):
        return False
    if unresolved_tool_use_ids(messages):
        return False
    last_assistant = last_assistant_message(messages)
    if not last_assistant:
        return False
    stop_reason = get_stop_reason(last_assistant)
    if stop_reason == "tool_use":
        return False
    if stop_reason in {"end_turn", "stop_sequence", "max_tokens"}:
        return True
    if is_api_error_message(last_assistant):
        return False
    return bool(extract_text(get_content(last_assistant)).strip()) and not iter_tool_uses(get_content(last_assistant))


def should_flush_pending_without_duration(
    payload: Dict[str, Any],
    new_messages: List[Dict[str, Any]],
    pending_messages: List[Dict[str, Any]],
) -> bool:
    if not pending_turn_is_complete(pending_messages):
        return False
    event_name = hook_event_name(payload)
    if event_name in {"Stop", "SessionEnd"}:
        return True
    return not new_messages


def attr_set(attrs: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (str, bool, int, float)):
        attrs[key] = value
    elif isinstance(value, (list, tuple)) and all(isinstance(x, (str, bool, int, float)) for x in value):
        attrs[key] = list(value)
    else:
        attrs[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)


def clean_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in attrs.items():
        if value is None or value == "":
            continue
        if isinstance(value, (str, bool, int, float)):
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(x, (str, bool, int, float)) for x in value):
            out[key] = list(value)
        else:
            out[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return out


def add_truncation_attrs(attrs: Dict[str, Any], prefix: str, meta: Dict[str, Any]) -> None:
    attr_set(attrs, f"{prefix}.truncated", bool(meta.get("truncated")))
    attr_set(attrs, f"{prefix}.original_length", meta.get("orig_len"))
    attr_set(attrs, f"{prefix}.kept_length", meta.get("kept_len"))
    attr_set(attrs, f"{prefix}.sha256", meta.get("sha256"))


def add_usage_attrs(attrs: Dict[str, Any], usage: Dict[str, int]) -> None:
    mapping = {
        "input": "gen_ai.usage.input_tokens",
        "output": "gen_ai.usage.output_tokens",
        "cache_read_input_tokens": "gen_ai.usage.cache_read.input_tokens",
        "cache_creation_input_tokens": "gen_ai.usage.cache_creation.input_tokens",
    }
    for src, dst in mapping.items():
        if src in usage:
            attr_set(attrs, dst, usage[src])


def turn_end_time(turn: Turn) -> Optional[datetime]:
    candidates = [parse_ts(msg) for msg in turn.assistant_msgs]
    for result in turn.tool_results_by_id.values():
        candidates.append(parse_ts(result))
    valid = [item for item in candidates if item is not None]
    return max(valid) if valid else None


def latest_non_error_assistant_time(turn: Turn) -> Optional[datetime]:
    candidates = [
        parse_ts(msg)
        for msg in turn.assistant_msgs
        if not is_api_error_message(msg)
    ]
    valid = [item for item in candidates if item is not None]
    return max(valid) if valid else None


def extract_runtime_metadata(messages: List[Dict[str, Any]], payload: Dict[str, Any]) -> RuntimeMetadata:
    version: Optional[str] = None
    for message in messages:
        candidate = message.get("version")
        if isinstance(candidate, str) and candidate:
            version = candidate
            break
    payload_version = payload.get("version")
    if not version and isinstance(payload_version, str) and payload_version:
        version = payload_version

    host = None
    try:
        host = socket.gethostname()
    except Exception:
        pass
    return RuntimeMetadata(agent_version=version, host=host)


def runtime_resource_attributes(config: HookConfig, runtime: RuntimeMetadata) -> Dict[str, Any]:
    attrs = dict(config.resource_attributes)
    attrs.setdefault("agent_runtime", AGENT_RUNTIME)
    if runtime.agent_version:
        attrs["gen_ai.agent.version"] = runtime.agent_version
    if runtime.host:
        attrs["host"] = runtime.host
        attrs.setdefault("host.name", runtime.host)
    return attrs


def import_otel() -> Any:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    return (
        trace,
        OTLPSpanExporter,
        OTLPMetricExporter,
        Resource,
        TracerProvider,
        BatchSpanProcessor,
        MeterProvider,
        PeriodicExportingMetricReader,
        ExplicitBucketHistogramAggregation,
        View,
    )


def create_tracer_provider(config: HookConfig, runtime: RuntimeMetadata) -> Any:
    trace, OTLPSpanExporter, _, Resource, TracerProvider, BatchSpanProcessor, _, _, _, _ = import_otel()
    tracker = TraceExportTracker()
    exporter = TrackingSpanExporter(
        OTLPSpanExporter(
            endpoint=config.trace_url,
            headers=config.headers,
            timeout=max(1, config.timeout_ms / 1000),
        ),
        tracker,
    )
    resource = Resource.create(runtime_resource_attributes(config, runtime))
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            schedule_delay_millis=200,
            max_export_batch_size=512,
            export_timeout_millis=config.timeout_ms,
        )
    )
    return trace, provider, provider.get_tracer("claude-otel-plugin", "0.1.6"), tracker


@dataclass
class MetricEmitters:
    provider: Any
    workflow_duration: Any
    operation_duration: Any
    token_usage: Any


def create_metrics_provider(config: HookConfig, runtime: RuntimeMetadata) -> Optional[MetricEmitters]:
    if not config.metrics_url:
        return None
    _, _, OTLPMetricExporter, Resource, _, _, MeterProvider, PeriodicExportingMetricReader, ExplicitBucketHistogramAggregation, View = import_otel()
    exporter = OTLPMetricExporter(
        endpoint=config.metrics_url,
        headers=config.headers,
        timeout=max(1, config.timeout_ms / 1000),
    )
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=60_000,
        export_timeout_millis=config.timeout_ms,
    )
    provider = MeterProvider(
        metric_readers=[reader],
        resource=Resource.create(runtime_resource_attributes(config, runtime)),
        views=[
            View(
                instrument_name="gen_ai.workflow.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200]
                ),
            ),
            View(
                instrument_name="gen_ai.client.operation.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]
                ),
            ),
            View(
                instrument_name="gen_ai.client.token.usage",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]
                ),
            ),
        ],
    )
    meter = provider.get_meter("claude-otel-plugin", "0.1.6")
    return MetricEmitters(
        provider=provider,
        workflow_duration=meter.create_histogram(
            "gen_ai.workflow.duration",
            unit="s",
            description="GenAI workflow duration.",
        ),
        operation_duration=meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="GenAI client operation duration.",
        ),
        token_usage=meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="GenAI client token usage.",
        ),
    )


def compact_text(value: Any, max_chars: int) -> str:
    text, _ = truncate_text(value, max_chars)
    return " ".join(text.split())


def duration_ms(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds() * 1000


def duration_s(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def add_duration(start: Optional[datetime], seconds: Optional[float] = None, milliseconds: Optional[float] = None) -> Optional[datetime]:
    if start is None:
        return None
    delta = timedelta()
    if isinstance(seconds, (int, float)):
        delta += timedelta(seconds=float(seconds))
    if isinstance(milliseconds, (int, float)):
        delta += timedelta(milliseconds=float(milliseconds))
    return start + delta


def max_ts(*values: Optional[datetime]) -> Optional[datetime]:
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None


def clamp_ts(value: Optional[datetime], end: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if end is not None and value > end:
        return end
    return value


API_ERROR_PATTERN = re.compile(r"API Error:\s*(\d+)\s+([a-zA-Z0-9_]+):")


def extract_api_error_info(msg: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    raw_text = extract_text(get_content(msg))
    error_type = None
    status_code = None
    match = API_ERROR_PATTERN.search(raw_text)
    if match:
        try:
            status_code = int(match.group(1))
        except Exception:
            status_code = None
        error_type = match.group(2)
    raw_status = msg.get("apiErrorStatus")
    if status_code is None and isinstance(raw_status, int):
        status_code = raw_status
    if not error_type and msg.get("isApiErrorMessage"):
        error_type = "api_error"
    return status_code, error_type, raw_text or None


def is_api_error_message(msg: Dict[str, Any]) -> bool:
    status_code, error_type, _ = extract_api_error_info(msg)
    return bool(msg.get("isApiErrorMessage") or status_code is not None or error_type)


def tool_command(tool_input: Any, max_chars: int) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("cmd") or tool_input.get("command")
    if isinstance(command, list):
        return compact_text(" ".join(str(part) for part in command), max_chars)
    if isinstance(command, str):
        return compact_text(command, max_chars)
    return None


def common_attrs(
    config: HookConfig,
    session_id: str,
    run_id: str,
    model: Optional[str],
    *,
    include_model: bool = True,
) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {
        "session_id": session_id,
        "gen_ai.conversation.id": session_id,
        "gen_ai.agent.name": AGENT_RUNTIME,
        "gen_ai.provider.name": "anthropic",
        "request_type": "user_request",
        "is_internal_request": False,
        "run_id": run_id,
        "run_ids": run_id,
        "status": "ok",
    }
    if include_model:
        attr_set(attrs, "gen_ai.request.model", model)
        attr_set(attrs, "gen_ai.response.model", model)
    attr_set(attrs, "user_id", config.user_id)
    return attrs


def metric_base_attrs(span_attrs: Dict[str, Any]) -> Dict[str, Any]:
    host = None
    try:
        host = socket.gethostname()
    except Exception:
        pass
    attrs: Dict[str, Any] = {
        "agent_runtime": AGENT_RUNTIME,
        "session_id": span_attrs.get("session_id") or span_attrs.get("gen_ai.conversation.id"),
        "gen_ai.conversation.id": span_attrs.get("gen_ai.conversation.id"),
        "gen_ai.provider.name": span_attrs.get("gen_ai.provider.name"),
        "gen_ai.request.model": span_attrs.get("gen_ai.request.model"),
        "gen_ai.response.model": span_attrs.get("gen_ai.response.model"),
        "host": host,
        "host.name": host,
    }
    return {k: v for k, v in attrs.items() if v not in (None, "")}


def metric_request_outcome(attrs: Dict[str, Any]) -> str:
    final_status = attrs.get("final_status")
    if final_status in {"completed", "cancelled", "unset"}:
        return str(final_status)
    return "error" if attrs.get("status") == "error" else "completed"


def metric_operation_outcome(attrs: Dict[str, Any]) -> str:
    if attrs.get("tool_result_status") == "error" or attrs.get("status") == "error":
        return "error"
    return "completed"


def record_request_metrics(metrics: Optional[MetricEmitters], attrs: Dict[str, Any], duration: Optional[float]) -> None:
    if not metrics:
        return
    metric_attrs = {**metric_base_attrs(attrs), "final_status": metric_request_outcome(attrs)}
    attr_set(metric_attrs, "final_status", attrs.get("final_status"))
    if duration is not None:
        metrics.workflow_duration.record(duration, metric_attrs)


def record_operation_metrics(metrics: Optional[MetricEmitters], attrs: Dict[str, Any], duration: Optional[float], operation_name: str) -> None:
    if not metrics:
        return
    metric_attrs = {
        **metric_base_attrs(attrs),
        "gen_ai.operation.name": attrs.get("gen_ai.operation.name") or operation_name,
    }
    attr_set(metric_attrs, "error.type", attrs.get("error.type"))
    if metric_attrs.get("gen_ai.operation.name") == "execute_tool":
        attr_set(metric_attrs, "gen_ai.tool.name", attrs.get("gen_ai.tool.name"))
        attr_set(metric_attrs, "tool_result_status", attrs.get("tool_result_status"))
    if duration is not None:
        metrics.operation_duration.record(duration, metric_attrs)


def record_token_metrics(metrics: Optional[MetricEmitters], attrs: Dict[str, Any]) -> None:
    if not metrics:
        return
    for attr_name, token_type in (
        ("gen_ai.usage.input_tokens", "input"),
        ("gen_ai.usage.output_tokens", "output"),
    ):
        value = attrs.get(attr_name)
        if isinstance(value, (int, float)) and value > 0:
            metrics.token_usage.record(
                value,
                {
                    **metric_base_attrs(attrs),
                    "gen_ai.operation.name": attrs.get("gen_ai.operation.name"),
                    "gen_ai.token.type": token_type,
                },
            )


def apply_skill_attrs(attrs: Dict[str, Any], skill: Optional[SkillInvocation]) -> None:
    if not skill:
        return
    attr_set(attrs, "skill.name", skill.name)
    attr_set(attrs, "skill.description", skill.description)
    attr_set(attrs, "skill.path", skill.path)
    attr_set(attrs, "skill_call_id", skill.call_id)
    attr_set(attrs, "skill.source.type", skill.source_type)
    attr_set(attrs, "skill.result_status", skill.result_status)
    attr_set(attrs, "gen_ai.skill.name", skill.name)
    attr_set(attrs, "gen_ai.skill.path", skill.path)
    attr_set(attrs, "gen_ai.skill.source.type", skill.source_type)
    attr_set(attrs, "gen_ai.skill.result_status", skill.result_status)
    attr_set(attrs, "gen_ai.skill.description", skill.description)
    attr_set(attrs, "gen_ai.skill.version", skill.version)


def emit_turn(trace_api: Any, tracer: Any, metrics: Optional[MetricEmitters], config: HookConfig, session_id: str, turn_num: int, turn: Turn, transcript_path: Path, skill_catalog: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    user_text, user_meta = truncate_text(extract_text(get_content(turn.user_msg)), config.max_chars)
    user_ts = parse_ts(turn.user_msg)
    recorded_turn_end_ts = add_duration(user_ts, milliseconds=turn.turn_duration_ms)
    observed_end_ts = turn_end_time(turn)
    latest_assistant_ts = latest_non_error_assistant_time(turn)
    if recorded_turn_end_ts or latest_assistant_ts:
        end_candidates = [ts for ts in (recorded_turn_end_ts, latest_assistant_ts, user_ts) if ts is not None]
    else:
        end_candidates = [ts for ts in (observed_end_ts, user_ts) if ts is not None]
    end_ts = max(end_candidates) if end_candidates else None
    cwd = turn.user_msg.get("cwd")
    git_branch = turn.user_msg.get("gitBranch")
    run_id = f"{session_id}:turn:{turn_num}"
    final_model = get_model(turn.assistant_msgs[-1]) if turn.assistant_msgs else "claude"
    total_usage: Dict[str, int] = {}
    tool_count = 0
    final_text = ""
    final_tool_uses: List[Dict[str, Any]] = []
    root_status = "ok"
    root_final_status = "completed"
    root_error_type = None
    root_error_reason = None
    root_error_status_code = None
    active_skill = detect_active_skill(turn, skill_catalog or {}, session_id, turn_num)
    for assistant in turn.assistant_msgs:
        final_text = extract_text(get_content(assistant)) or final_text
        assistant_tool_uses = iter_tool_uses(get_content(assistant))
        final_tool_uses = assistant_tool_uses
        tool_count += len(assistant_tool_uses)
        merge_usage(total_usage, usage_details(get_usage(assistant)))
        if is_api_error_message(assistant):
            status_code, error_type, reason = extract_api_error_info(assistant)
            root_status = "error"
            root_final_status = "error"
            root_error_type = error_type or root_error_type or "api_error"
            root_error_reason = reason or root_error_reason
            root_error_status_code = status_code or root_error_status_code
    if active_skill and root_status == "error":
        active_skill.result_status = "error"

    root_attrs: Dict[str, Any] = common_attrs(config, session_id, run_id, final_model, include_model=False)
    root_attrs.update({
        "trace_name": f"Claude Code Turn {turn_num}",
        "gen_ai.operation.name": "invoke_agent",
        "input_preview": compact_text(user_text, config.max_chars),
        "input_length": len(user_text),
        "output_preview": compact_text(final_text, config.max_chars),
        "output_length": len(final_text) if final_text else None,
        "tool_count": tool_count,
        "final_status": root_final_status,
        "claude_turn_number": turn_num,
        "transcript_path": str(transcript_path),
        "status": root_status,
        "error.type": root_error_type,
        "reason": root_error_reason,
        "http.status_code": root_error_status_code,
    })
    attr_set(root_attrs, "code.cwd", cwd)
    attr_set(root_attrs, "code.git_branch", git_branch)
    attr_set(root_attrs, "gen_ai.input.messages", build_input_messages(user_text, [], config.max_chars))
    attr_set(
        root_attrs,
        "gen_ai.output.messages",
        build_output_messages(final_text, final_tool_uses, config.max_chars, get_stop_reason(turn.assistant_msgs[-1]) if turn.assistant_msgs else None),
    )
    add_truncation_attrs(root_attrs, "input", user_meta)

    root = tracer.start_span("invoke_agent", start_time=to_ns(user_ts), attributes=clean_attrs(root_attrs))
    root_context = trace_api.set_span_in_context(root)
    if active_skill:
        skill_attrs = common_attrs(config, session_id, run_id, final_model)
        skill_attrs.update({
            "status": root_status,
            "error.type": root_error_type,
            "reason": root_error_reason,
            "http.status_code": root_error_status_code,
        })
        apply_skill_attrs(skill_attrs, active_skill)
        skill_span = tracer.start_span(
            f"skill:{active_skill.name}",
            context=root_context,
            start_time=to_ns(user_ts),
            attributes=clean_attrs(skill_attrs),
        )
        skill_span.end(end_time=to_ns(end_ts or user_ts))
    prev_ts = user_ts
    prev_tool_results: List[Dict[str, Any]] = []

    for idx, assistant in enumerate(turn.assistant_msgs):
        assistant_ts = clamp_ts(parse_ts(assistant), end_ts)
        assistant_raw_text = extract_text(get_content(assistant))
        assistant_text, _ = truncate_text(assistant_raw_text, config.max_chars)
        tool_uses = iter_tool_uses(get_content(assistant))
        model = get_model(assistant)
        usage = usage_details(get_usage(assistant))
        is_api_error = is_api_error_message(assistant)
        api_status_code, api_error_type, api_error_reason = extract_api_error_info(assistant)

        output_payload: Dict[str, Any] = {}
        if assistant_text:
            output_payload["content"] = assistant_text
        if tool_uses:
            output_payload["tool_calls"] = [
                {
                    "id": tool.get("id"),
                    "name": tool.get("name"),
                    "input": tool.get("input"),
                }
                for tool in tool_uses
            ]

        input_payload: Any = {"role": "user", "content": user_text} if idx == 0 else {
            "role": "tool",
            "tool_results": prev_tool_results,
        }

        generation_attrs: Dict[str, Any] = common_attrs(config, session_id, run_id, model)
        generation_attrs.update({
            "gen_ai.operation.name": "chat",
            "input_preview": compact_text(input_payload, config.max_chars),
            "input_length": len(compact_text(input_payload, config.max_chars)),
            "output_preview": compact_text(output_payload, config.max_chars),
            "output_length": len(compact_text(output_payload, config.max_chars)),
            "output_kind": "tool_call" if tool_uses else "text",
            "step_index": idx,
            "status": "error" if is_api_error else "ok",
            "error.type": api_error_type if is_api_error else None,
            "reason": api_error_reason if is_api_error else None,
            "http.status_code": api_status_code if is_api_error else None,
        })
        attr_set(
            generation_attrs,
            "gen_ai.input.messages",
            build_input_messages(user_text if idx == 0 else "", prev_tool_results if idx > 0 else [], config.max_chars),
        )
        attr_set(
            generation_attrs,
            "gen_ai.output.messages",
            build_output_messages(assistant_text, tool_uses, config.max_chars, get_stop_reason(assistant)),
        )
        add_usage_attrs(generation_attrs, usage)

        generation = tracer.start_span(
            "llm",
            context=root_context,
            start_time=to_ns(prev_ts or assistant_ts),
            attributes=clean_attrs(generation_attrs),
        )
        generation_context = trace_api.set_span_in_context(generation)

        batch_result_times: List[datetime] = []
        batch_tool_results = []
        for tool in tool_uses:
            tool_id = str(tool.get("id") or "")
            tool_name = str(tool.get("name") or "unknown")
            tool_raw_input = tool.get("input")
            tool_input, tool_input_meta = truncate_text(tool.get("input"), config.max_chars)
            result = turn.tool_results_by_id.get(tool_id) if tool_id else None
            if result:
                tool_output, tool_output_meta = truncate_text(result.get("content"), config.max_chars)
                raw_result_ts = parse_ts(result)
                duration_seconds = result.get("duration_seconds")
                computed_result_ts = add_duration(assistant_ts, seconds=duration_seconds if isinstance(duration_seconds, (int, float)) else None)
                result_ts = clamp_ts(computed_result_ts or raw_result_ts, end_ts)
                is_error = bool(result.get("is_error"))
            else:
                tool_output, tool_output_meta, result_ts = "", {"truncated": False, "orig_len": 0}, None
                is_error = False

            if result_ts:
                batch_result_times.append(result_ts)

            tool_attrs: Dict[str, Any] = common_attrs(config, session_id, run_id, model)
            tool_attrs.update({
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": tool_name,
                "gen_ai.tool.call.id": tool_id,
                "gen_ai.tool.call.arguments": compact_text(tool_raw_input, config.max_chars),
                "gen_ai.tool.call.result": compact_text(tool_output, config.max_chars),
                "tool_command": tool_command(tool_raw_input, config.max_chars),
                "tool_result_status": "error" if is_error else "completed",
                "status": "error" if is_error else "ok",
                "error.type": "_OTHER" if is_error else None,
                "reason": compact_text(tool_output, config.max_chars) if is_error else None,
            })
            apply_skill_attrs(tool_attrs, active_skill)
            add_truncation_attrs(tool_attrs, "input", tool_input_meta)
            add_truncation_attrs(tool_attrs, "output", tool_output_meta)
            injected = turn.injected_by_tool_id.get(tool_id)
            if injected:
                injected_text, injected_meta = truncate_text(injected, config.max_chars)
                attr_set(tool_attrs, "claude.injected_context.value", injected_text)
                add_truncation_attrs(tool_attrs, "claude.injected_context", injected_meta)

            tool_span = tracer.start_span(
                f"tool:{tool_name}",
                context=generation_context,
                start_time=to_ns(assistant_ts),
                attributes=clean_attrs(tool_attrs),
            )
            tool_span.end(end_time=to_ns(result_ts or assistant_ts))
            record_operation_metrics(metrics, tool_attrs, duration_s(assistant_ts, result_ts or assistant_ts), "execute_tool")
            batch_tool_results.append(
                {
                    "id": tool_id,
                    "name": tool_name,
                    "output": tool_output,
                    **({"error": tool_output} if is_error else {}),
                }
            )

        generation_end = max(batch_result_times) if batch_result_times else assistant_ts
        if assistant_text:
            assistant_end = generation_end or assistant_ts
            if not tool_uses:
                assistant_end = max_ts(assistant_end, end_ts, recorded_turn_end_ts)
            assistant_attrs = common_attrs(config, session_id, run_id, model)
            assistant_attrs.update({
                "gen_ai.operation.name": "chat",
                "role": "assistant",
                "output_preview": compact_text(assistant_text, config.max_chars),
                "output_length": len(assistant_raw_text),
                "output_kind": "text",
                "assistant_message_start_time": assistant_ts.isoformat() if assistant_ts else None,
                "assistant_message_end_time": assistant_end.isoformat() if assistant_end else None,
                "step_index": idx,
                "message_index": 0,
                "status": "error" if is_api_error else "ok",
                "error.type": api_error_type if is_api_error else None,
                "reason": api_error_reason if is_api_error else None,
                "http.status_code": api_status_code if is_api_error else None,
            })
            assistant_span = tracer.start_span(
                "assistant",
                context=generation_context,
                start_time=to_ns(assistant_ts),
                attributes=clean_attrs(assistant_attrs),
            )
            assistant_end_ns = to_ns(assistant_end or assistant_ts)
            assistant_start_ns = to_ns(assistant_ts)
            if assistant_end_ns is not None and assistant_start_ns is not None and assistant_end_ns <= assistant_start_ns:
                assistant_end_ns = assistant_start_ns + 1
            assistant_span.end(end_time=assistant_end_ns)
        generation.end(end_time=to_ns(generation_end or assistant_ts or prev_ts))
        record_operation_metrics(metrics, generation_attrs, duration_s(prev_ts or assistant_ts, generation_end or assistant_ts or prev_ts), "chat")
        record_token_metrics(metrics, generation_attrs)
        prev_tool_results = batch_tool_results
        prev_ts = generation_end or assistant_ts or prev_ts

    root.end(end_time=to_ns(end_ts or user_ts))
    record_request_metrics(metrics, root_attrs, duration_s(user_ts, end_ts or user_ts))
    if config.debug:
        log(
            config,
            logging.DEBUG,
            "turn timing",
            session_id=session_id,
            turn_num=turn_num,
            user_ts=user_ts.isoformat() if user_ts else None,
            observed_end_ts=observed_end_ts.isoformat() if observed_end_ts else None,
            latest_assistant_ts=latest_assistant_ts.isoformat() if latest_assistant_ts else None,
            recorded_turn_duration_ms=turn.turn_duration_ms,
            recorded_turn_end_ts=recorded_turn_end_ts.isoformat() if recorded_turn_end_ts else None,
            chosen_end_ts=end_ts.isoformat() if end_ts else None,
            root_duration_ms=duration_ms(user_ts, end_ts or user_ts),
            assistant_count=len(turn.assistant_msgs),
            tool_count=tool_count,
        )


def flush_provider(provider: Any, timeout_ms: int) -> bool:
    outcome = {"force_flush": True, "shutdown": True}

    def run() -> None:
        try:
            result = provider.force_flush(timeout_millis=timeout_ms)
            if result is False:
                outcome["force_flush"] = False
        except Exception:
            outcome["force_flush"] = False
        try:
            result = provider.shutdown()
            if result is False:
                outcome["shutdown"] = False
        except Exception:
            outcome["shutdown"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(max(1.0, timeout_ms / 1000))
    if thread.is_alive():
        return False
    return outcome["force_flush"] and outcome["shutdown"]


def run(hook_input: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> int:
    payload = read_hook_payload(hook_input)
    session_id, transcript_path = extract_session_and_transcript(payload)
    payload_cwd = payload.get("cwd")
    config_cwd = Path(payload_cwd).expanduser() if isinstance(payload_cwd, str) and payload_cwd else Path.cwd()
    config = resolve_config(env=env, cwd=config_cwd)

    if not config.enabled:
        log(config, logging.INFO, "disabled")
        return 0
    if not config.trace_url:
        log(config, logging.INFO, "missing OTLP trace endpoint")
        return 0
    if not session_id or not transcript_path:
        log(config, logging.INFO, "missing session_id or transcript_path", payload_keys=sorted(payload.keys()))
        return 0
    if not transcript_path.exists():
        log(config, logging.INFO, "transcript does not exist", transcript_path=str(transcript_path))
        return 0

    trace_api = None
    provider = None
    trace_tracker = None
    tracer = None
    metrics = None
    emitted = 0
    provider_flushed = False
    try:
        with FileLock(LOCK_FILE):
            global_state = load_state()
            key = state_key(session_id, str(transcript_path))
            session_state = load_session_state(global_state, key)
            messages, session_state = read_new_jsonl(transcript_path, session_state)
            combined_messages = list(session_state.pending_messages) + messages
            if not combined_messages:
                write_session_state(global_state, key, session_state)
                save_state(global_state)
                return 0

            runtime = extract_runtime_metadata(combined_messages, payload)
            session_state.skill_catalog = merge_skill_catalog(session_state.skill_catalog, combined_messages, config_cwd, home=Path.home())
            if provider is None:
                try:
                    trace_api, provider, tracer, trace_tracker = create_tracer_provider(config, runtime)
                    metrics = create_metrics_provider(config, runtime)
                except Exception as exc:
                    log(config, logging.INFO, "opentelemetry unavailable", error=str(exc))
                    return 0

            turns, pending_messages = build_turns_with_pending(combined_messages)
            if pending_messages and should_flush_pending_without_duration(payload, messages, pending_messages):
                turns.extend(build_turns(pending_messages))
                pending_messages = []
            for turn in turns:
                emitted += 1
                emit_turn(
                    trace_api,
                    tracer,
                    metrics,
                    config,
                    session_id,
                    session_state.turn_count + emitted,
                    turn,
                    transcript_path,
                    session_state.skill_catalog,
                )

            if provider is not None:
                provider_flushed = True
                trace_flush_ok = flush_provider(provider, config.timeout_ms)
                trace_export_ok = trace_tracker.export_ok(emitted) if trace_tracker else trace_flush_ok
                if not trace_flush_ok or not trace_export_ok:
                    log(
                        config,
                        logging.INFO,
                        "trace export failed",
                        emitted=emitted,
                        transcript_path=str(transcript_path),
                        trace_url=config.trace_url,
                        export_calls=trace_tracker.export_calls if trace_tracker else None,
                        export_result=trace_tracker.last_result if trace_tracker else None,
                        export_error=trace_tracker.last_error if trace_tracker else None,
                        flush_ok=trace_flush_ok,
                    )
                    return 0

            session_state.turn_count += emitted
            session_state.pending_messages = pending_messages
            write_session_state(global_state, key, session_state)
            save_state(global_state)
    except TimeoutError as exc:
        log(config, logging.INFO, "lock timeout", error=str(exc))
        return 0
    except Exception as exc:
        log(config, logging.INFO, "collection failed", error=f"{type(exc).__name__}: {exc}")
        return 0
    finally:
        if provider is not None and not provider_flushed:
            flush_provider(provider, config.timeout_ms)
        if metrics:
            flush_provider(metrics.provider, config.timeout_ms)

    log(
        config,
        logging.INFO,
        "processed turns",
        emitted=emitted,
        transcript_path=str(transcript_path),
        trace_url=config.trace_url,
        metrics_url=config.metrics_url,
    )
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
