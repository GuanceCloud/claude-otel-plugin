# claude-otel-plugin

`claude-otel-plugin` is an OpenTelemetry collection plugin for Claude Code. It
reads Claude Code transcript JSONL from the `Stop` and `SessionEnd` hooks,
converts turns, assistant generations, tool calls, tool results, and token usage
into OTLP traces and metrics, then exports them over OTLP HTTP/protobuf.

The hook is fail-open: missing dependencies, missing config, parse errors, and
upload failures are logged but do not block Claude Code.

## Capabilities

- Collects Claude Code turns, assistant generations, tool calls, tool results,
  and token usage.
- Generates `invoke_agent`, `llm`, `assistant`, and `tool:<name>` spans.
- Exports OTLP traces and metrics over HTTP/protobuf.
- Derives metrics from the same turn data as traces.
- Supports Dataway/GTrace-style `endpoint + tracePath + metricsPath + headers`
  configuration.
- Supports `~/.claude/gtrace.json`, project `.claude/gtrace.json`, and OTLP
  environment variables.

## Flow

```text
Claude Code Stop / SessionEnd hook
    |
    v
hooks/claude_otel_hook.py reads transcript JSONL
    |
    v
parse turns, model calls, tool calls, and usage
    |
    v
build OTLP traces and metrics
    |
    v
POST <endpoint>/<tracePath>
POST <endpoint>/<metricsPath>
```

## Quick Start

Requirements:

- Claude Code with plugin support
- Python 3.10+
- `uv` recommended

Add the marketplace and install the plugin from inside Claude Code:

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

Write the export config:

```bash
mkdir -p ~/.claude
cat > ~/.claude/gtrace.json <<'JSON'
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
JSON
```

Restart Claude Code, or run `/reload-plugins`.

For installation, upgrade, uninstall, and dependency details, see
[docs/install.md](docs/install.md).

## Documentation

| Document | Description |
| --- | --- |
| [docs/install.md](docs/install.md) | Installation, upgrade, uninstall, dependencies, and local install |
| [docs/configuration.md](docs/configuration.md) | Config precedence, GTrace config, environment variables, and resource attributes |
| [docs/traces.md](docs/traces.md) | Trace/span shape, field names, token semantics, and field migration |
| [docs/metrics.md](docs/metrics.md) | Metrics, tags, and metric migration |
| [docs/development.md](docs/development.md) | Local validation, logs, state files, and troubleshooting |

## Data Model

Trace fields, span names, tool call/result attributes, token semantics, and
field migration details are documented in [docs/traces.md](docs/traces.md).

Metrics, tag design, and metric migration details are documented in
[docs/metrics.md](docs/metrics.md).

Current metrics are derived from the current turn data and use these
OpenTelemetry GenAI metric names:

- `gen_ai.workflow.duration`
- `gen_ai.client.operation.duration`
- `gen_ai.client.token.usage`

## Development

Common commands:

```bash
python3 -m unittest discover -s test
python3 -m py_compile hooks/claude_otel_hook.py
claude plugin validate .
```

For local validation and troubleshooting, see [docs/development.md](docs/development.md).
