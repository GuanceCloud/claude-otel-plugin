# Installation and Upgrade

This document covers runtime requirements, installation, upgrade, and uninstall
for `claude-otel-plugin`.

## Requirements

- Claude Code with plugin support
- Python 3.10+
- `uv` recommended

`hooks/claude_otel_hook.py` uses PEP 723 inline dependencies. When `uv` is on
`PATH`, Claude Code runs the hook with:

```bash
uv run --quiet --script hooks/claude_otel_hook.py
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Without `uv`, the hook falls back to `python3`, and that Python environment must
already have:

```bash
pip install "opentelemetry-api>=1.25,<2" \
  "opentelemetry-sdk>=1.25,<2" \
  "opentelemetry-exporter-otlp-proto-http>=1.25,<2"
```

## Remote Install

From inside Claude Code, add this GitHub repository as a plugin marketplace and
install the plugin:

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

If the repository is private, the machine running Claude Code must have GitHub
access to `GuanceCloud/claude-otel-plugin`.

## Configure Export

The recommended config location is `~/.claude/gtrace.json`:

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

After configuration, restart Claude Code or run:

```text
/reload-plugins
```

The hook starts processing transcripts after Claude Code emits `Stop` or
`SessionEnd` events.

## Local Install

For development or local testing, add a local checkout:

```text
/plugin marketplace add /path/to/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

You can validate the marketplace first:

```bash
claude plugin validate .
```

## Minimal Check

After installation, check:

```text
/plugin list
/plugin details claude-otel-plugin@claude-otel-plugin
```

If no data is exported, check:

- The plugin is installed and enabled.
- `uv`, or a `python3` environment with OpenTelemetry dependencies, is available
  to non-interactive shells.
- `~/.claude/gtrace.json` has `"enabled": true`.
- `endpoint`, `tracePath`, `metricsPath`, and authentication headers are correct.
- Claude Code was restarted or `/reload-plugins` was run.

## Upgrade

Refresh the marketplace and reload plugins:

```text
/plugin marketplace update claude-otel-plugin
/reload-plugins
```

For a local-path install, update the local checkout first, then run the same
update and reload commands.

## Uninstall

Uninstall the plugin:

```text
/plugin uninstall claude-otel-plugin@claude-otel-plugin
```

If you no longer need the marketplace, remove it:

```text
/plugin marketplace remove claude-otel-plugin
```

To also remove export config and hook state:

```bash
rm -f ~/.claude/gtrace.json
rm -f ~/.claude/state/claude_otel_hook.log
rm -f ~/.claude/state/claude_otel_state.json
rm -f ~/.claude/state/claude_otel_state.lock
```
