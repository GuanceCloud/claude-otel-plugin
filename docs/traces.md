# Trace 说明

本文档说明 `claude-otel-plugin` 的 trace/span 结构、关键字段、token 口径和旧字段迁移。

## Span 结构

每个完成的 Claude Code turn 会保留现有 span tree 形态，并使用
OpenTelemetry GenAI semantic conventions 命名 span attributes。API error turn
会标记为 `status=error`。

当 Claude transcript 中存在 `turn_duration` 或
`toolUseResult.durationSeconds` 时，hook 优先使用这些值，而不是延迟写入的
transcript timestamp。

```text
invoke_agent
  llm
    assistant
    tool:<name>
  llm
```

## 关键字段

- `gen_ai.conversation.id`
- `session_id`，用于兼容现有 dashboard
- `gen_ai.agent.name=claude-code`
- `gen_ai.agent.version`
- `gen_ai.operation.name=invoke_agent|chat|execute_tool`
- `gen_ai.provider.name=anthropic`
- `gen_ai.request.model`
- `gen_ai.response.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_creation.input_tokens`
- `gen_ai.tool.name`
- `gen_ai.tool.call.id`
- `gen_ai.tool.call.arguments`
- `gen_ai.tool.call.result`
- `run_id`
- `run_ids`
- `request_type`
- `is_internal_request`
- `input_preview`
- `input_length`
- `output_preview`
- `output_length`
- `tool_count`
- `tool_command`
- `tool_result_status`
- `host`
- `host.name`

`host` 和 `host.name` 同时写入 resource 和 metric attributes。

## Token 口径

`gen_ai.usage.input_tokens` 使用 OpenTelemetry GenAI 语义：表示完整输入 token。
当 Claude 上报 cache read 和 cache creation token 时，这些 token 会包含在完整
input tokens 中。

缓存相关字段单独保留：

- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_creation.input_tokens`

不再单独输出 total/cache total/context total 这类可派生字段。

## Tool 字段

Tool call span 使用：

- `gen_ai.operation.name=execute_tool`
- `gen_ai.tool.name`
- `gen_ai.tool.call.id`
- `gen_ai.tool.call.arguments`
- `gen_ai.tool.call.result`

为了避免采集内容过长，arguments 和 result 会受 `max_chars` 限制。

## 字段迁移

| 旧字段 | 新字段 / 行为 |
| --- | --- |
| `session_id` | 保留，并复制到 `gen_ai.conversation.id` |
| `session_agent` | `gen_ai.agent.name` |
| `agent_version` | `gen_ai.agent.version` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`、`gen_ai.response.model` |
| `usage_input_tokens` | `gen_ai.usage.input_tokens` |
| `usage_output_tokens` | `gen_ai.usage.output_tokens` |
| `usage_total_tokens` | 移除；需要时由 input + output 派生 |
| `usage_cache_read_input_tokens` | `gen_ai.usage.cache_read.input_tokens` |
| `usage_cache_creation_input_tokens` | `gen_ai.usage.cache_creation.input_tokens` |
| `usage_cache_total_tokens` | 移除；来源与 cache read 重复 |
| `usage_context_input_tokens` | 移除；完整 input 使用 `gen_ai.usage.input_tokens` |
| `usage_context_total_tokens` | 移除 |
| `tool_name` | `gen_ai.tool.name` |
| `tool_call_id` | `gen_ai.tool.call.id` |
| `tool_args_preview` | `gen_ai.tool.call.arguments` |
| `tool_result_preview` | `gen_ai.tool.call.result` |
