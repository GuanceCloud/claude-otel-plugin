# claude-otel-plugin

Claude Code OpenTelemetry plugin. It reads Claude Code transcript JSONL from
`Stop` and `SessionEnd` hooks, converts turns, assistant generations, tool
calls, tool results, and token usage into OTLP traces and metrics, then exports
them over OTLP HTTP/protobuf.

The hook is fail-open: missing dependencies, missing config, parse errors, and
upload failures are logged but do not block Claude Code.

## Layout

```text
.claude-plugin/plugin.json
hooks/hooks.json
hooks/claude_otel_hook.py
test/test_claude_otel_hook.py
```

## Requirements

- Claude Code with plugin support
- Python 3.10+
- `uv` recommended

`hooks/claude_otel_hook.py` uses PEP 723 inline dependencies. With `uv` on
PATH, Claude Code runs:

```bash
uv run --quiet --script hooks/claude_otel_hook.py
```

Without `uv`, the hook falls back to `python3`, and the environment must already
have:

```bash
pip install "opentelemetry-api>=1.25,<2" \
  "opentelemetry-sdk>=1.25,<2" \
  "opentelemetry-exporter-otlp-proto-http>=1.25,<2"
```

## Configuration

The hook resolves config in this order, later items overriding earlier ones:

1. Claude plugin `CLAUDE_PLUGIN_OPTION_*` values
2. global `~/.claude/gtrace.json`
3. project `.claude/gtrace.json`
4. ordinary environment variables

For day-to-day maintenance, prefer `~/.claude/gtrace.json`. Plugin userConfig is
kept as a fallback for first-time install and for sensitive values stored by
Claude Code.

Supported `gtrace.json`:

```json
{
  "enabled": true,
  "endpoint": "http://localhost:4318",
  "tracePath": "v1/traces",
  "metricsPath": "v1/metrics",
  "headers": {
    "Authorization": "Bearer token"
  },
  "resourceAttributes": {
    "service.name": "claude-code",
    "deployment.environment": "dev"
  },
  "timeout_ms": 10000,
  "debug": true,
  "max_chars": 20000
}
```

You can also use standard OTLP-style env vars:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics
export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Bearer token'
export OTEL_RESOURCE_ATTRIBUTES='service.name=claude-code,deployment.environment=dev'
```

If `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` or
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` is set, it overrides `endpoint +
tracePath` or `endpoint + metricsPath`.

For Guance/GTrace, this is the expected shape:

```json
{
  "enabled": true,
  "endpoint": "https://llm-openway.guance.com",
  "tracePath": "v1/write/otel-llm",
  "metricsPath": "v1/write/otel-metrics",
  "headers": {
    "X-Token": "<token>",
    "To-Headless": "true"
  }
}
```

When `tracePath` is `v1/write/otel-llm` and no metrics path is explicitly set,
the hook infers `v1/write/otel-metrics`.

## Trace Shape

Each completed Claude Code turn keeps the existing span tree shape, while span
attributes follow OpenTelemetry GenAI semantic conventions. API error turns are
marked as `status=error`, and when Claude records `turn_duration` or
`toolUseResult.durationSeconds`, those values are preferred over delayed
transcript timestamps:

```text
invoke_agent
  llm
    assistant
    tool:<name>
  llm
```

Important attributes:

- `gen_ai.conversation.id`
- `session_id` for compatibility with existing dashboards
- `gen_ai.agent.name=claude-code`
- `gen_ai.agent.version`
- `gen_ai.operation.name=invoke_agent|chat|execute_tool`
- `gen_ai.provider.name=anthropic`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_creation.input_tokens`
- `gen_ai.tool.name`
- `gen_ai.tool.call.id`
- `gen_ai.tool.call.arguments`
- `gen_ai.tool.call.result`
- `run_id`, `run_ids`, `request_type`, `is_internal_request`
- `input_preview`, `input_length`, `output_preview`, `output_length`
- `tool_count`, `tool_command`, `tool_result_status`
- `host`, `host.name` on resource and metric attributes

`gen_ai.usage.input_tokens` uses the OpenTelemetry GenAI meaning: full input
tokens, including cache read and cache creation tokens when Claude reports them.

## Metrics Shape

Metrics are emitted from the same parsed turn data and use OpenTelemetry GenAI
metric names:

| Metric | Type | Unit |
| --- | --- | --- |
| `gen_ai.workflow.duration` | Histogram | `s` |
| `gen_ai.client.operation.duration` | Histogram | `s` |
| `gen_ai.client.token.usage` | Histogram | `{token}` |

Common metric tags include `session_id`, `gen_ai.conversation.id`,
`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
`gen_ai.response.model`, `host`, and `host.name`. Tool operation metrics also
carry `gen_ai.tool.name` and `tool_result_status`; token metrics carry
`gen_ai.token.type=input|output`.

## Field Mapping

Trace field changes:

| Previous field | New field / behavior |
| --- | --- |
| `session_id` | Kept and also copied to `gen_ai.conversation.id` |
| `session_agent` | `gen_ai.agent.name` |
| `agent_version` | `gen_ai.agent.version` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`, `gen_ai.response.model` |
| `usage_input_tokens` | `gen_ai.usage.input_tokens` |
| `usage_output_tokens` | `gen_ai.usage.output_tokens` |
| `usage_total_tokens` | Removed; derive from input + output if needed |
| `usage_cache_read_input_tokens` | `gen_ai.usage.cache_read.input_tokens` |
| `usage_cache_creation_input_tokens` | `gen_ai.usage.cache_creation.input_tokens` |
| `usage_cache_total_tokens` | Removed; same source as cache read |
| `usage_context_input_tokens` | Removed; full input is `gen_ai.usage.input_tokens` |
| `usage_context_total_tokens` | Removed |
| `tool_name` | `gen_ai.tool.name` |
| `tool_call_id` | `gen_ai.tool.call.id` |
| `tool_args_preview` | `gen_ai.tool.call.arguments` |
| `tool_result_preview` | `gen_ai.tool.call.result` |

Metric changes:

| Previous metric / tag | New metric / tag |
| --- | --- |
| `gen_ai.agent.request.count` | Removed |
| `gen_ai.agent.request.duration` | `gen_ai.workflow.duration` |
| `gen_ai.agent.operation.count` | Removed |
| `gen_ai.agent.operation.duration` | `gen_ai.client.operation.duration` |
| `gen_ai.agent.token.usage` | `gen_ai.client.token.usage` |
| duration unit `ms` | duration unit `s` |
| `session_id` | Kept and also copied to `gen_ai.conversation.id` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`, `gen_ai.response.model` |
| `operation_name` | `gen_ai.operation.name` |
| `tool_name` | `gen_ai.tool.name` |
| `token_type` | `gen_ai.token.type` |
| `token_type=total/cache_read/cache_total/reasoning` | Removed |

## Local Test

```bash
cd /home/liurui/code/claude-otel-plugin
python3 -m unittest discover -s test
python3 -m py_compile hooks/claude_otel_hook.py
```

For an end-to-end check, point `endpoint` at any OTLP HTTP collector and restart
Claude Code after enabling the plugin.

## Logs and State

```text
~/.claude/state/claude_otel_hook.log
~/.claude/state/claude_otel_state.json
~/.claude/state/claude_otel_state.lock
```

State tracks transcript byte offsets so repeated hook invocations only process
new JSONL lines.
