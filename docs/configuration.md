# Configuration

This document covers configuration precedence, recommended GTrace settings,
environment variables, and `resourceAttributes` conventions.

## Config Precedence

The hook resolves config in this order, with later sources overriding earlier
ones:

1. Claude plugin `CLAUDE_PLUGIN_OPTION_*` values
2. Global `~/.claude/gtrace.json`
3. Project `.claude/gtrace.json`
4. Ordinary environment variables

For day-to-day maintenance, prefer `~/.claude/gtrace.json`. Plugin userConfig is
kept as a fallback for first-time install and for sensitive values stored by
Claude Code.

## Recommended Dataway/GTrace Config

```json
{
  "enabled": true,
  "endpoint": "https://llm-openway.guance.com",
  "tracePath": "v1/write/otel-llm",
  "metricsPath": "v1/write/otel-metrics",
  "headers": {
    "X-Token": "<token>",
    "To-Headless": "true"
  },
  "resourceAttributes": {
    "env": "prod",
    "agent_id": "claude-monitor",
    "agent_name": "Claude OTEL"
  },
  "debug": true
}
```

Do not commit real tokens in repository files, test fixtures, or documentation
examples.

When `tracePath` is `v1/write/otel-llm` and no metrics path is explicitly set,
the hook infers `v1/write/otel-metrics`.

## Generic OTLP Config

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
    "env": "dev",
    "agent_id": "claude-local",
    "agent_name": "Claude OTEL"
  },
  "timeout_ms": 10000,
  "debug": true,
  "max_chars": 20000
}
```

## Environment Variables

Standard OTLP-style environment variables are also supported:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics
export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Bearer token'
export OTEL_RESOURCE_ATTRIBUTES='service.name=claude,deployment.environment=dev'
```

If `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` or
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` is set, it overrides `endpoint + tracePath`
or `endpoint + metricsPath`.

## Resource Attributes

Global filtering tags should be placed in OTLP `resource.attributes`. Traces and
metrics share the same `resourceAttributes`. Recommended fields:

- `env`
- `agent_id`
- `agent_name`

Notes:

- `host` and `host.name` default to the current hostname.
- Do not put `run_id`, user input, or high-cardinality one-off fields in
  `resourceAttributes`.
- `resourceAttributes` are applied to trace resources and metric attributes.

## Switches and Debugging

Common fields:

| Field | Description |
| --- | --- |
| `enabled` | Enable or disable export |
| `debug` | Write verbose hook logs |
| `timeout_ms` | OTLP HTTP request timeout |
| `max_chars` | Maximum captured characters for input, output, tool args, and tool results |

Log locations are documented in [development.md](development.md).
