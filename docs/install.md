# Installation and Upgrade

This document covers runtime requirements, installation, upgrade, and uninstall
for `claude-otel-plugin`.

## Requirements

- Claude Code with plugin support
- `uv`, or `python3` with `venv`

Claude Code invokes the runtime launcher with:

```bash
sh hooks/run_hook.sh
```

`hooks/claude_otel_hook.py` uses PEP 723 inline dependencies. The launcher runs
it with `uv` when `uv` is on `PATH`.

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

No manual `pip install` is required. The Hook prefers `uv`; when `uv` is not
available, `hooks/run_hook.sh` falls back to `python3 -m venv` and installs the
required OpenTelemetry packages into a plugin-local runtime directory.

## Remote Install

Recommended customer install:

```bash
curl -fsSL https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.sh \
  | bash -s -- latest \
      --endpoint https://llm-openway.guance.com \
      --x-token <token> \
      --tag env=prod \
      --tag agent_id=claude-monitor \
      --tag agent_name=Claude
```

Install a specific released version:

```bash
curl -fsSL https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.sh \
  | bash -s -- 0.1.17 --endpoint https://llm-openway.guance.com --x-token <token>
```

The release installer downloads a GitHub Release package, verifies the SHA-256
checksum when a checksum tool is available, expands the package locally, copies
it to `~/.claude/marketplaces/claude-otel-plugin-release`, then installs or
updates `claude-otel-plugin` from that persistent marketplace source. Installer
parameters are forwarded to `scripts/install.sh`, so install-time configuration
is applied both to Claude plugin `userConfig` and to `~/.claude/gtrace.json`
unless `--no-config` is used.

When `scripts/install.sh` or `scripts/install.ps1` is pointed at a temporary
local package directory, the installer stages that directory into the same
persistent `~/.claude/marketplaces/claude-otel-plugin-release` location before
registering the marketplace with Claude Code.

Native Windows PowerShell:

```powershell
& ([scriptblock]::Create((Invoke-RestMethod https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.ps1))) latest `
    --endpoint https://llm-openway.guance.com `
    --x-token <token> `
    --tag env=prod `
    --tag agent_id=claude-monitor
```

Install a specific release by replacing `latest` with a version such as
`0.1.17`. The PowerShell installer verifies the same SHA-256 asset and installs
the persistent marketplace under `%USERPROFILE%\.claude\marketplaces`.

You can also run the same flow manually from inside Claude Code:

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
```

If the repository is private, the machine running Claude Code must have GitHub
access to `GuanceCloud/claude-otel-plugin`.

For a local checkout, you can also run:

```bash
bash scripts/install.sh . --endpoint https://llm-openway.guance.com --x-token <token>
```

## Installer Options

All installers forward the same options to `scripts/install.sh` on Unix/WSL or
`scripts/install.ps1` on native Windows:

```text
--scope user|project|local
--type gtrace|otlp
--endpoint URL
--x-token TOKEN
--trace-path PATH
--metrics-path PATH
--header KEY=VALUE
--tag KEY=VALUE
--timeout-ms N
--user-id VALUE
--max-chars N
--debug | --no-debug
--enabled BOOL
--config-file PATH
--no-config
```

Notes:

- `--tag` writes `resourceAttributes`.
- `--header` appends extra OTLP HTTP headers.
- `--x-token` is mapped to `headers.X-Token`.
- `--enabled false` writes `enabled: false` even when it is the only option.
- When `--enabled` is omitted, a new config defaults to enabled and an existing
  config keeps its current value.
- `gtrace` mode defaults to:
  - `tracePath = v1/write/otel-llm`
  - `metricsPath = v1/write/otel-metrics`
- `otlp` mode defaults to:
  - `tracePath = v1/traces`
  - `metricsPath = v1/metrics`

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

`resourceAttributes` are exported as shared resource tags on traces and metrics.

After configuration, restart Claude Code.

The hook starts processing transcripts after Claude Code emits `Stop` or
`SessionEnd` events.

## Local Install

For development or local testing, add a local checkout:

```text
/plugin marketplace add /path/to/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
```

You can validate the marketplace first:

```bash
claude plugin validate .
```

The helper script wraps the same flow:

```bash
bash scripts/install.sh /path/to/claude-otel-plugin --endpoint https://llm-openway.guance.com --x-token <token>
```

On native Windows:

```powershell
.\scripts\install.ps1 C:\path\to\claude-otel-plugin `
    --endpoint https://llm-openway.guance.com `
    --x-token <token>
```

For release engineering, build the package locally with:

```bash
sh scripts/package-release.sh
```

## Minimal Check

After installation, check:

```text
/plugin list
/plugin details claude-otel-plugin@claude-otel-plugin
```

If no data is exported, check:

- The plugin is installed and enabled.
- `uv` is available to non-interactive shells, or `python3` with `venv` is available on `PATH`.
- `~/.claude/gtrace.json` has `"enabled": true`.
- `endpoint`, `tracePath`, `metricsPath`, and authentication headers are correct.
- Claude Code was restarted after install or upgrade.

## Upgrade

Refresh the marketplace, update the installed plugin, then restart Claude Code:

```text
/plugin marketplace update claude-otel-plugin
/plugin update claude-otel-plugin@claude-otel-plugin
```

For a local-path install, update the local checkout first, then run the same
plugin update commands and restart Claude Code:

```text
/plugin marketplace update claude-otel-plugin
/plugin update claude-otel-plugin@claude-otel-plugin
```

After upgrading, verify the installed version:

```text
/plugin list
/plugin details claude-otel-plugin@claude-otel-plugin
```

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
