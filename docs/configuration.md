# 配置说明

本文档说明 `claude-otel-plugin` 的配置读取顺序、推荐配置、环境变量和
`resourceAttributes` 约定。

## 配置读取顺序

Hook 按以下顺序解析配置，后面的配置会覆盖前面的配置：

1. Claude plugin `CLAUDE_PLUGIN_OPTION_*` values
2. 全局 `~/.claude/gtrace.json`
3. 当前项目 `.claude/gtrace.json`
4. 普通环境变量

日常维护推荐使用 `~/.claude/gtrace.json`。Plugin userConfig 更适合作为首次
安装时的 fallback，或用于 Claude Code 存储敏感配置。

## 推荐 Dataway/GTrace 配置

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
    "deployment.environment": "prod",
    "app_id": "claude-monitor",
    "app_name": "Claude OTEL",
    "agent_type": "assistant",
    "agent_source": "claude-code"
  },
  "debug": true
}
```

不要把真实 token 写入仓库文件、测试 fixture 或文档示例。

当 `tracePath` 是 `v1/write/otel-llm` 且没有显式设置 metrics path 时，hook 会
推断 metrics path 为 `v1/write/otel-metrics`。

## 通用 OTLP 配置

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

## 环境变量

也可以使用标准 OTLP 风格环境变量：

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics
export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Bearer token'
export OTEL_RESOURCE_ATTRIBUTES='service.name=claude-code,deployment.environment=dev'
```

如果设置了 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` 或
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`，它会覆盖 `endpoint + tracePath` 或
`endpoint + metricsPath`。

## Resource Attributes

全局筛选类 tag 应放在 OTLP `resource.attributes`，trace 和 metrics 会共享同一
批 `resourceAttributes`。推荐字段：

- `service.name`
- `host`
- `host.name`
- `deployment.environment`
- `app_id`
- `app_name`
- `agent_type`
- `agent_source`

说明：

- `host` 和 `host.name` 默认会自动采集当前宿主机 hostname。
- 不要把 `run_id`、真实用户输入或高基数一次性字段放进 `resourceAttributes`。
- `resourceAttributes` 应用于 trace resource 和 metric attributes。

## 采集开关与调试

常用字段：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用上报 |
| `debug` | 是否写详细 hook 日志 |
| `timeout_ms` | OTLP HTTP 请求超时时间 |
| `max_chars` | input/output/tool 参数和结果的最大采集字符数 |

日志位置见 [development.md](development.md)。
