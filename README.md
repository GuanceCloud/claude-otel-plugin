# claude-otel-plugin

`claude-otel-plugin` is an OpenTelemetry collection plugin for Claude Code. It
reads Claude Code transcript JSONL from the `Stop` and `SessionEnd` hooks,
converts turns, assistant generations, tool calls, tool results, and token usage
into OTLP traces and metrics, then exports them over OTLP HTTP/protobuf.

The hook is fail-open: missing dependencies, missing config, parse errors, and
upload failures are logged but do not block Claude Code.

## Capabilities

- Collects Claude Code turns, assistant generations, tool calls, tool results,
  token usage, and explicit slash-skill invocation metadata.
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
- `uv` (provides the same hook runtime on macOS, Linux, and Windows)

Customer install, one command:

```bash
curl -fsSL https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.sh \
  | bash -s -- latest \
      --endpoint https://llm-openway.guance.com \
      --x-token <token> \
      --tag env=prod \
      --tag agent_id=claude-monitor \
      --tag agent_name=Claude
```

Install a specific release:

```bash
curl -fsSL https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.sh \
  | bash -s -- 0.1.16 --endpoint https://llm-openway.guance.com --x-token <token>
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((Invoke-RestMethod https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.ps1))) latest `
    --endpoint https://llm-openway.guance.com `
    --x-token <token> `
    --tag env=prod
```

Or add the marketplace and install the plugin from inside Claude Code:

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
```

Or install from a local checkout:

```bash
bash scripts/install.sh . --endpoint https://llm-openway.guance.com --x-token <token>
```

```powershell
.\scripts\install.ps1 . --endpoint https://llm-openway.guance.com --x-token <token>
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
    "to_headless": "true"
  },
  "resourceAttributes": {
    "env": "prod",
    "agent_id": "claude-monitor",
    "agent_name": "Claude OTEL"
  }
}
JSON
```

Restart Claude Code to apply the plugin.

`resourceAttributes` are exported as shared resource tags on traces and metrics.

The plugin does not require manual `pip install`; `uv` resolves the inline hook
dependencies on every supported platform.

The installers also accept `--trace-path`, `--metrics-path`, `--header`,
`--tag`, `--timeout-ms`, `--user-id`, `--max-chars`, `--enabled`, and
`--no-config`. Set `--enabled false` or `"enabled": false` to disable collection
without uninstalling the plugin.

Release artifacts are built from tagged versions and published as GitHub
Release assets. The recommended customer install path uses those assets instead
of the `main` branch.

For installation, upgrade, uninstall, and runtime details, see
[docs/install.md](docs/install.md).

## Documentation

| Document | Description |
| --- | --- |
| [docs/install.md](docs/install.md) | Installation, upgrade, uninstall, runtime requirements, and local install |
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
- `gen_ai.agent.operation.count`
- `gen_ai.agent.operation.duration`
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
