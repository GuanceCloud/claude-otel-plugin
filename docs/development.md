# 开发与调试

本文档说明 `claude-otel-plugin` 的本地验证、日志、状态文件和排查方式。

## 常用命令

```bash
python3 -m unittest discover -s test
python3 -m py_compile hooks/claude_otel_hook.py
claude plugin validate .
```

当前测试覆盖 hook 解析、OTLP trace/metrics 生成、去重和错误处理等核心行为。

## 项目结构

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
hooks/hooks.json
hooks/claude_otel_hook.py
test/test_claude_otel_hook.py
docs/
```

## Hook 日志和状态

默认文件：

```text
~/.claude/state/claude_otel_hook.log
~/.claude/state/claude_otel_state.json
~/.claude/state/claude_otel_state.lock
```

`claude_otel_state.json` 记录 transcript byte offsets，让重复 hook 调用只处理
新增 JSONL 行。

## 排查命令

查看 hook 日志：

```bash
tail -n 100 ~/.claude/state/claude_otel_hook.log
```

查看状态文件：

```bash
cat ~/.claude/state/claude_otel_state.json
ls -l ~/.claude/state/claude_otel_state.lock
```

检查配置：

```bash
cat ~/.claude/gtrace.json
```

检查插件 marketplace：

```bash
claude plugin validate .
```

## 常见问题

如果没有上报数据，优先检查：

- 插件已安装且启用。
- Claude Code 已重启或执行过 `/reload-plugins`。
- `~/.claude/gtrace.json` 存在且 `enabled` 为 `true`。
- `endpoint`、`tracePath`、`metricsPath` 和认证 header 正确。
- 使用 `uv` 时，`uv` 在非交互 shell 的 `PATH` 中。
- 不使用 `uv` 时，`python3` 环境已安装 OpenTelemetry 依赖。
- `~/.claude/state/claude_otel_hook.log` 中是否有 HTTP 状态码、解析错误或依赖错误。

如果看到重复数据，检查状态文件是否能正常写入，以及
`~/.claude/state/claude_otel_state.lock` 是否长期残留。
