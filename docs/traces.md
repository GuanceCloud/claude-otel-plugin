# Traces

This document covers the trace/span shape, key attributes, token semantics, and
field migration for `claude-otel-plugin`.

## Span Shape

Each completed Claude Code turn keeps the existing span tree shape, while span
attributes follow OpenTelemetry GenAI semantic conventions. API error turns are
marked as `status=error`.

When Claude records `turn_duration` or `toolUseResult.durationSeconds`, those
values are preferred over delayed transcript timestamps.

```text
invoke_agent
  llm
    assistant
    tool:<name>
  llm
```

## Key Attributes

- `gen_ai.conversation.id`
- `session_id`, kept for compatibility with existing dashboards
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

`host` and `host.name` are written to resource and metric attributes.

## Token Semantics

`gen_ai.usage.input_tokens` uses the OpenTelemetry GenAI meaning: full input
tokens. When Claude reports cache read and cache creation tokens, those tokens
are included in the full input token count.

Cache-specific fields are still preserved:

- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_creation.input_tokens`

Total, cache total, and context total fields are not emitted because they can be
derived or duplicate another source.

## Tool Attributes

Tool call spans use:

- `gen_ai.operation.name=execute_tool`
- `gen_ai.tool.name`
- `gen_ai.tool.call.id`
- `gen_ai.tool.call.arguments`
- `gen_ai.tool.call.result`

Arguments and results are truncated by `max_chars`.

## Field Migration

| Previous field | New field / behavior |
| --- | --- |
| `session_id` | Kept and also copied to `gen_ai.conversation.id` |
| `session_agent` | `gen_ai.agent.name` |
| `agent_version` | `gen_ai.agent.version` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`, `gen_ai.response.model` |
| `usage_input_tokens` | `gen_ai.usage.input_tokens` |
| `usage_output_tokens` | `gen_ai.usage.output_tokens` |
| `usage_total_tokens` | Removed; derive from input + output if needed |
| `usage_cache_read_input_tokens` | `gen_ai.usage.cache_read.input_tokens` |
| `usage_cache_creation_input_tokens` | `gen_ai.usage.cache_creation.input_tokens` |
| `usage_cache_total_tokens` | Removed; same source as cache read |
| `usage_context_input_tokens` | Removed; full input is `gen_ai.usage.input_tokens` |
| `usage_context_total_tokens` | Removed |
| `tool_name` | `gen_ai.tool.name` |
| `tool_call_id` | `gen_ai.tool.call.id` |
| `tool_args_preview` | `gen_ai.tool.call.arguments` |
| `tool_result_preview` | `gen_ai.tool.call.result` |
