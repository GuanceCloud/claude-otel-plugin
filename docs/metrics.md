# Metrics 说明

本文档说明 `claude-otel-plugin` 的 Metrics 指标体系、常用 tag、token 映射和旧指标迁移。

## 指标体系

Metrics 从同一批解析后的 turn 数据派生，并使用 OpenTelemetry GenAI metric
names：

| Metric | Type | Unit |
| --- | --- | --- |
| `gen_ai.workflow.duration` | Histogram | `s` |
| `gen_ai.client.operation.duration` | Histogram | `s` |
| `gen_ai.client.token.usage` | Histogram | `{token}` |

## 常用 Tags

通用 metric tags：

- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.operation.name`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `host`
- `host.name`

Tool operation metrics 还会包含：

- `gen_ai.tool.name`
- `tool_result_status`

Token metrics 还会包含：

- `gen_ai.token.type=input`
- `gen_ai.token.type=output`

## Token 指标

`gen_ai.client.token.usage` 当前只输出 input 和 output 两类 token usage。

缓存 token 仍在 trace attributes 中保留，但不会作为独立的 `token_type` metric
输出，避免 total/cache/context 口径重复。

## 旧指标迁移

| 旧指标 / tag | 新指标 / tag |
| --- | --- |
| `gen_ai.agent.request.count` | 移除 |
| `gen_ai.agent.request.duration` | `gen_ai.workflow.duration` |
| `gen_ai.agent.operation.count` | 移除 |
| `gen_ai.agent.operation.duration` | `gen_ai.client.operation.duration` |
| `gen_ai.agent.token.usage` | `gen_ai.client.token.usage` |
| duration unit `ms` | duration unit `s` |
| `session_id` | 保留，并复制到 `gen_ai.conversation.id` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`、`gen_ai.response.model` |
| `operation_name` | `gen_ai.operation.name` |
| `tool_name` | `gen_ai.tool.name` |
| `token_type` | `gen_ai.token.type` |
| `token_type=total/cache_read/cache_total/reasoning` | 移除 |

## Resource Attributes

全局筛选类 tag 建议通过 `resourceAttributes` 放在 OTLP
`resource.attributes` 中，并由 trace 和 metrics 共用。配置方式见
[configuration.md](configuration.md)。
