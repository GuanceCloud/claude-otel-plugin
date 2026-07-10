# Metrics

本文档说明 `claude-otel-plugin` 当前实际输出的指标、标签口径，以及旧指标到新指标的迁移关系。

指标与 trace 使用同一份 turn 解析结果，但五类指标的标签并不完全相同。阅读和建图时，建议按指标类型分别理解。

## 指标列表

插件当前输出 5 个 OpenTelemetry GenAI 指标：

| Metric | Type | Unit | 来源 |
| --- | --- | --- | --- |
| `gen_ai.workflow.duration` | Histogram | `s` | 整个 turn，对应根 span `invoke_agent` |
| `gen_ai.agent.operation.count` | Counter | 空 | 单次操作计数，对齐 Codex agent operation 口径 |
| `gen_ai.agent.operation.duration` | Histogram | `ms` | 单次操作耗时，对齐 Codex agent operation 口径 |
| `gen_ai.client.operation.duration` | Histogram | `s` | 单次操作，对应 `chat` / `execute_tool` / `skill` |
| `gen_ai.client.token.usage` | Histogram | `{token}` | 仅 LLM token 用量 |

## 指标口径

### 1. `gen_ai.workflow.duration`

表示一次 Claude turn 的总耗时。

这个指标来自根级 `invoke_agent`，当前只保留工作流维度标签，不带模型标签，也不带 `gen_ai.operation.name`。

标签：

- `agent_runtime`
- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.provider.name`
- `host`
- `host.name`
- `final_status`

说明：

- `final_status` 取值通常为 `completed` / `error` / `cancelled` / `unset`
- 该指标刻意不携带 `gen_ai.request.model` 和 `gen_ai.response.model`

### 2. `gen_ai.agent.operation.count`

表示 agent 侧子操作计数。该指标参考 Codex 插件的 `gen_ai.agent.operation.count` 设计，并同时输出 AM 看板使用的扁平标签别名。

基础标签：

- `agent_runtime`
- `session_id`
- `gen_ai.conversation.id`
- `host`
- `host.name`
- `gen_ai.operation.name`
- `outcome`

AM 兼容别名：

- `operation_name`
- `provider_name`
- `request_model`
- `response_model`
- `model_name`

按类型追加的标签：

- 当 `gen_ai.operation.name=chat` 时：
  - `gen_ai.provider.name`
  - `gen_ai.request.model`
  - `gen_ai.response.model`
- 当 `gen_ai.operation.name=execute_tool` 时：
  - `gen_ai.tool.name`
  - `tool_name`
- 当 `gen_ai.operation.name=skill` 时：
  - `gen_ai.skill.name`
  - `skill_name`
  - `skill_source`
  - `skill_source_type`
  - `skill_result_status`

错误相关标签：

- 当 `outcome=error` 时，上报 `error.type`
- 如果没有明确错误类型，`error.type` 使用 `_OTHER`

### 3. `gen_ai.agent.operation.duration`

表示 agent 侧子操作耗时。该指标参考 Codex 插件的 `gen_ai.agent.operation.duration` 设计，单位为毫秒，并同时输出 AM 看板使用的扁平标签别名。

基础标签：

- `agent_runtime`
- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `host`
- `host.name`
- `gen_ai.operation.name`
- `outcome`

AM 兼容别名：

- `operation_name`
- `provider_name`
- `request_model`
- `response_model`
- `model_name`

按类型追加的标签：

- 当 `gen_ai.operation.name=execute_tool` 时：
  - `gen_ai.tool.name`
  - `tool_name`
  - `tool_result_status`
- 当 `gen_ai.operation.name=skill` 时：
  - `gen_ai.skill.name`
  - `skill_name`
  - `skill_source`
  - `skill_source_type`
  - `skill_result_status`

错误相关标签：

- 当 `outcome=error` 时，上报 `error.type`
- 如果没有明确错误类型，`error.type` 使用 `_OTHER`

### 4. `gen_ai.client.operation.duration`

表示一次子操作耗时。当前操作类型分为：

- `chat`
- `execute_tool`
- `skill`

基础标签：

- `agent_runtime`
- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `host`
- `host.name`
- `gen_ai.operation.name`

按类型追加的标签：

- 当 `gen_ai.operation.name=execute_tool` 时：
  - `gen_ai.tool.name`
  - `tool_result_status`
- 当 `gen_ai.operation.name=skill` 时：
  - `gen_ai.skill.name`

错误相关标签：

- `error.type` 仅在存在错误时上报

说明：

- `skill` 被当作一类特殊操作，不再混在普通 `tool` 指标里理解
- 对 skill 调用，trace 结构是 `llm -> tool:Skill -> skill:<name>`；指标里会单独生成一条 `operation.name=skill`

### 5. `gen_ai.client.token.usage`

表示 LLM token 用量。

当前只上报两类 token：

- `gen_ai.token.type=input`
- `gen_ai.token.type=output`

标签：

- `agent_runtime`
- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `host`
- `host.name`
- `gen_ai.operation.name`
- `gen_ai.token.type`

说明：

- 当前 token 指标只从 LLM 侧生成，因此 `gen_ai.operation.name` 实际上是 `chat`
- `cache_read`、`cache_creation`、`reasoning` 等 token 不再拆成独立指标
- 这些 token 信息如果存在，仍可能保留在 trace attributes 中，但不会作为独立 metric time series 输出

## 标签设计说明

### `agent_runtime`

指标统一保留 `agent_runtime`，当前值为：

- `claude`

这是指标侧用于区分运行时的固定标签。它不同于旧 trace 中出现过的 `agent_source`、`agent_type`，后两者已移除，不再作为指标或 trace 的通用维度。

### `session_id` 与 `gen_ai.conversation.id`

两者当前都会保留，值相同：

- `session_id`：兼容已有查询和历史图表
- `gen_ai.conversation.id`：对齐 OpenTelemetry GenAI 语义约定

### 模型标签

模型标签只存在于：

- `gen_ai.agent.operation.count` 的 `gen_ai.operation.name=chat` 序列
- `gen_ai.agent.operation.duration`
- `gen_ai.client.operation.duration`
- `gen_ai.client.token.usage`

不会存在于：

- `gen_ai.workflow.duration`

这是有意设计。根工作流指标用于观察请求总耗时，不希望因模型维度放大 time series。

## 与 trace 的对应关系

常见 span / metric 对应关系：

| Trace Span | 指标 |
| --- | --- |
| `invoke_agent` | `gen_ai.workflow.duration` |
| `llm` | `gen_ai.agent.operation.*` with `gen_ai.operation.name=chat`; `gen_ai.client.operation.duration` with `gen_ai.operation.name=chat` |
| `tool:<name>` | `gen_ai.agent.operation.*` with `gen_ai.operation.name=execute_tool`; `gen_ai.client.operation.duration` with `gen_ai.operation.name=execute_tool` |
| `skill:<name>` | `gen_ai.agent.operation.*` with `gen_ai.operation.name=skill`; `gen_ai.client.operation.duration` with `gen_ai.operation.name=skill` |

补充说明：

- `assistant` span 目前只用于 trace 展示，不单独生成指标
- token 指标只来自 `llm` 相关属性，不来自 `tool`、`skill` 或根 span

## 迁移说明

| 旧指标 / 旧标签 | 新指标 / 新标签 |
| --- | --- |
| `gen_ai.agent.request.count` | Removed |
| `gen_ai.agent.request.duration` | `gen_ai.workflow.duration` |
| `gen_ai.agent.operation.count` | 已恢复，用于兼容 Codex agent operation 指标 |
| `gen_ai.agent.operation.duration` | 已恢复，用于兼容 Codex agent operation 指标；同时继续输出 `gen_ai.client.operation.duration` |
| `gen_ai.agent.token.usage` | `gen_ai.client.token.usage` |
| duration unit `ms` | 保留在 `gen_ai.agent.operation.duration`；`gen_ai.client.operation.duration` 使用 `s` |
| `provider_name` | 在 `gen_ai.agent.operation.*` 中作为 AM 别名保留；语义源为 `gen_ai.provider.name` |
| `model_name` | 在 `gen_ai.agent.operation.*` 中作为 AM 别名保留；语义源为 `gen_ai.response.model` 或 `gen_ai.request.model` |
| `operation_name` | 在 `gen_ai.agent.operation.*` 中作为 AM 别名保留；语义源为 `gen_ai.operation.name` |
| `tool_name` | 在 `gen_ai.agent.operation.*` 中作为 AM 别名保留；语义源为 `gen_ai.tool.name` |
| `skill_name` | 在 `gen_ai.agent.operation.*` 中作为 AM 别名保留；语义源为 `gen_ai.skill.name` |
| `token_type` | `gen_ai.token.type` |
| `token_type=total/cache_read/cache_total/reasoning` | Removed |
| `agent_source` | Removed |
| `agent_type` | Removed |

## Resource Attributes

跨 trace / metric 共享的全局筛选维度，建议通过 OTLP `resource.attributes` 或插件配置里的 `resourceAttributes` 注入，而不是继续扩张单条指标标签。

见 [configuration.md](configuration.md)。
