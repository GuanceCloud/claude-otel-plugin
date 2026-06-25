# 安装与升级

本文档说明 `claude-otel-plugin` 的运行要求、安装方式、升级和卸载。

## 运行要求

- Claude Code with plugin support
- Python 3.10+
- 推荐安装 `uv`

`hooks/claude_otel_hook.py` 使用 PEP 723 inline dependencies。`uv` 在
`PATH` 中时，Claude Code 会通过以下命令运行 hook：

```bash
uv run --quiet --script hooks/claude_otel_hook.py
```

安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

如果不使用 `uv`，hook 会回退到 `python3`，且对应 Python 环境必须已经安装：

```bash
pip install "opentelemetry-api>=1.25,<2" \
  "opentelemetry-sdk>=1.25,<2" \
  "opentelemetry-exporter-otlp-proto-http>=1.25,<2"
```

## 远程安装

在 Claude Code 中添加这个 GitHub 仓库作为 plugin marketplace，然后安装插件：

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

仓库是私有仓库时，运行 Claude Code 的机器需要有
`GuanceCloud/claude-otel-plugin` 的 GitHub 访问权限。

## 写入配置

推荐把上报配置写到 `~/.claude/gtrace.json`：

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

配置完成后重启 Claude Code，或执行：

```text
/reload-plugins
```

Hook 会在 Claude Code 触发 `Stop` 或 `SessionEnd` 事件后开始处理 transcript。

## 本地安装

开发或测试本地工作树时，可以直接添加本地目录：

```text
/plugin marketplace add /path/to/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

也可以先验证 marketplace：

```bash
claude plugin validate .
```

## 最小自检

安装后建议检查：

```text
/plugin list
/plugin details claude-otel-plugin@claude-otel-plugin
```

如果 hook 没有上报数据，优先确认：

- 插件已安装且启用。
- `uv` 或包含 OpenTelemetry 依赖的 `python3` 可被非交互 shell 找到。
- `~/.claude/gtrace.json` 中 `enabled` 为 `true`。
- `endpoint`、`tracePath`、`metricsPath` 和认证 header 正确。
- Claude Code 已重启或执行过 `/reload-plugins`。

## 升级

刷新 marketplace 并重新加载插件：

```text
/plugin marketplace update claude-otel-plugin
/reload-plugins
```

如果从本地目录安装，先更新本地源码，再执行同样的 update 和 reload。

## 卸载

卸载插件：

```text
/plugin uninstall claude-otel-plugin@claude-otel-plugin
```

如果不再使用这个 marketplace，也可以移除：

```text
/plugin marketplace remove claude-otel-plugin
```

如需清理上报配置和 hook 状态：

```bash
rm -f ~/.claude/gtrace.json
rm -f ~/.claude/state/claude_otel_hook.log
rm -f ~/.claude/state/claude_otel_state.json
rm -f ~/.claude/state/claude_otel_state.lock
```
