# claude-otel-plugin

`claude-otel-plugin` 是一个 Claude Code OpenTelemetry 采集插件。它通过
Claude Code `Stop` 和 `SessionEnd` hooks 读取 transcript JSONL，将 turn、
模型生成、工具调用、工具结果和 token usage 转换为 OTLP Trace 与 Metrics，并
通过 HTTP/protobuf 上报。

Hook 是 fail-open 设计：依赖缺失、配置缺失、解析失败或上报失败会写日志，但
不会阻塞 Claude Code。

## 能力概览

- 采集 Claude Code turn、assistant generation、tool call、tool result 和 token usage。
- 生成 `invoke_agent`、`llm`、`assistant`、`tool:<name>` 四类 span。
- 使用 OTLP Trace 与 Metrics HTTP/protobuf 上报。
- Metrics 从同批 turn 数据派生，触发时机与 traces 相同。
- 支持 Dataway/GTrace 风格的 `endpoint + tracePath + metricsPath + headers` 配置。
- 支持 `~/.claude/gtrace.json`、项目 `.claude/gtrace.json` 和 OTLP 环境变量。

## 工作流程

```text
Claude Code Stop / SessionEnd hook
    |
    v
hooks/claude_otel_hook.py 读取 transcript JSONL
    |
    v
解析 turn、模型调用、工具调用和 usage
    |
    v
生成 OTLP traces 与 metrics
    |
    v
POST <endpoint>/<tracePath>
POST <endpoint>/<metricsPath>
```

## 快速开始

要求：

- Claude Code with plugin support
- Python 3.10+
- 推荐安装 `uv`

在 Claude Code 中添加 marketplace 并安装插件：

```text
/plugin marketplace add GuanceCloud/claude-otel-plugin
/plugin install claude-otel-plugin@claude-otel-plugin
/reload-plugins
```

写入上报配置：

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

安装完成后重启 Claude Code，或执行 `/reload-plugins`。

更多安装、升级、卸载和依赖说明见 [docs/install.md](docs/install.md)。

## 文档导航

| 文档 | 说明 |
| --- | --- |
| [docs/install.md](docs/install.md) | 安装、升级、卸载、依赖和本地安装 |
| [docs/configuration.md](docs/configuration.md) | 配置读取顺序、GTrace 配置、环境变量和 resource attributes |
| [docs/traces.md](docs/traces.md) | Trace/span 结构、字段命名、token 口径和字段迁移 |
| [docs/metrics.md](docs/metrics.md) | Metrics 指标体系、tag 和旧指标迁移 |
| [docs/development.md](docs/development.md) | 本地验证、日志、状态文件和排查方式 |

## 数据模型

Trace 字段、span name、tool call/result、token 口径和旧字段迁移关系见
[docs/traces.md](docs/traces.md)。

Metrics 指标体系、tag 设计和旧指标迁移关系见
[docs/metrics.md](docs/metrics.md)。

当前 Metrics 只从当前 turn 数据派生以下 OpenTelemetry GenAI 指标：

- `gen_ai.workflow.duration`
- `gen_ai.client.operation.duration`
- `gen_ai.client.token.usage`

## 开发

常用命令：

```bash
python3 -m unittest discover -s test
python3 -m py_compile hooks/claude_otel_hook.py
claude plugin validate .
```

更多本地验证和排查说明见 [docs/development.md](docs/development.md)。
