# Metrics

This document covers metrics, common tags, token mapping, and metric migration
for `claude-otel-plugin`.

## Metric Set

Metrics are derived from the same parsed turn data as traces and use
OpenTelemetry GenAI metric names:

| Metric | Type | Unit |
| --- | --- | --- |
| `gen_ai.workflow.duration` | Histogram | `s` |
| `gen_ai.client.operation.duration` | Histogram | `s` |
| `gen_ai.client.token.usage` | Histogram | `{token}` |

## Common Tags

Common metric tags:

- `session_id`
- `gen_ai.conversation.id`
- `gen_ai.operation.name`
- `gen_ai.provider.name`
- `host`
- `host.name`

Workflow metrics derived from `invoke_agent` intentionally omit model tags.
Model tags are still present on operation and token metrics derived from `llm`
spans.

Tool operation metrics also include:

- `gen_ai.tool.name`
- `tool_result_status`

Token metrics also include:

- `gen_ai.token.type=input`
- `gen_ai.token.type=output`

## Token Metrics

`gen_ai.client.token.usage` currently emits only input and output token usage.

Cache tokens are still preserved in trace attributes, but they are not emitted
as separate `token_type` metrics. This avoids duplicate total/cache/context
token semantics.

## Metric Migration

| Previous metric / tag | New metric / tag |
| --- | --- |
| `gen_ai.agent.request.count` | Removed |
| `gen_ai.agent.request.duration` | `gen_ai.workflow.duration` |
| `gen_ai.agent.operation.count` | Removed |
| `gen_ai.agent.operation.duration` | `gen_ai.client.operation.duration` |
| `gen_ai.agent.token.usage` | `gen_ai.client.token.usage` |
| duration unit `ms` | duration unit `s` |
| `session_id` | Kept and also copied to `gen_ai.conversation.id` |
| `provider_name` | `gen_ai.provider.name` |
| `model_name` | `gen_ai.request.model`, `gen_ai.response.model` |
| `operation_name` | `gen_ai.operation.name` |
| `tool_name` | `gen_ai.tool.name` |
| `token_type` | `gen_ai.token.type` |
| `token_type=total/cache_read/cache_total/reasoning` | Removed |

## Resource Attributes

Global filtering tags should be placed in OTLP `resource.attributes` via
`resourceAttributes`, then shared by traces and metrics. See
[configuration.md](configuration.md).
