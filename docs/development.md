# Development and Debugging

This document covers local validation, logs, state files, and troubleshooting
for `claude-otel-plugin`.

## Common Commands

```bash
python3 -m unittest discover -s test
python3 -m py_compile hooks/claude_otel_hook.py
claude plugin validate .
```

The current tests cover hook parsing, OTLP trace/metric generation,
deduplication, and error handling.

## Release Workflow

Build the release package locally:

```bash
sh scripts/package-release.sh
```

Create and push a release tag:

```bash
claude plugin tag .
git push origin <tag>
```

Pushing a tag in the form `claude-otel-plugin--v<version>` triggers the GitHub
Actions release workflow. The workflow checks that the tag version matches
`.claude-plugin/plugin.json`, runs the test suite, then uploads the release
assets, including `install-release.sh` and the packaged installer scripts.

## Layout

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
hooks/hooks.json
hooks/claude_otel_hook.py
test/test_claude_otel_hook.py
docs/
```

## Hook Logs and State

Default files:

```text
~/.claude/state/claude_otel_hook.log
~/.claude/state/claude_otel_state.json
~/.claude/state/claude_otel_state.lock
```

`claude_otel_state.json` tracks transcript byte offsets so repeated hook
invocations only process new JSONL lines.

## Troubleshooting Commands

View hook logs:

```bash
tail -n 100 ~/.claude/state/claude_otel_hook.log
```

Inspect state files:

```bash
cat ~/.claude/state/claude_otel_state.json
ls -l ~/.claude/state/claude_otel_state.lock
```

Check config:

```bash
cat ~/.claude/gtrace.json
```

Validate the plugin marketplace:

```bash
claude plugin validate .
```

## Common Issues

If no data is exported, check:

- The plugin is installed and enabled.
- Claude Code was restarted after the plugin changed.
- `~/.claude/gtrace.json` exists and has `"enabled": true`.
- `endpoint`, `tracePath`, `metricsPath`, and authentication headers are correct.
- When using `uv`, `uv` is available in the non-interactive shell `PATH`.
- `uv` is available to the non-interactive Hook process.
- `~/.claude/state/claude_otel_hook.log` for HTTP status codes, parse errors, or
  dependency errors.

If duplicate data appears, check whether the state file can be written and
whether `~/.claude/state/claude_otel_state.lock` is stuck.
