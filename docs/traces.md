# Traces

This document covers the trace/span shape, key attributes, token semantics, and
field migration for `claude-otel-plugin`.

## Span Shape

Each completed Claude Code turn keeps the existing span tree shape, while span
attributes follow OpenTelemetry GenAI semantic conventions. API error turns are
marked as `status=error`.

When Claude records `turn_duration` or `toolUseResult.durationSeconds`, those
values are preferred over delayed transcript timestamps.

When the user explicitly invokes a slash skill such as `/review`, the hook also
emits a sibling `skill:<name>` span under `invoke_agent` and copies unified
skill tags onto both `skill:<name>` and related `tool:<name>` spans.

When Claude invokes the built-in `Skill` tool with input such as
`{"skill":"dashboard","args":"..."}`, the hook emits a nested
`tool:Skill -> skill:<name>` span pair for that tool call.

```text
invoke_agent
  skill:<name>
  llm
    assistant
    tool:<name>
      skill:<name>
  llm
```

## Key Attributes

- `gen_ai.conversation.id`
- `session_id`, kept for compatibility with existing dashboards
- `gen_ai.agent.name=claude`
- `gen_ai.agent.version`
- `gen_ai.operation.name=invoke_agent|chat|execute_tool`
- `gen_ai.provider.name=anthropic`
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

`invoke_agent` intentionally omits `gen_ai.request.model`,
`gen_ai.response.model`, and `gen_ai.usage.*` attributes. Those fields are kept
on `llm` spans instead.

## Skill Attributes

`skill` is not an official OpenTelemetry GenAI semantic namespace as of
2026-06-25. This plugin keeps compatibility fields and also emits
`gen_ai.skill.*` project extension fields.

Unified skill tags are added to `skill:<name>` and related `tool:<name>` spans
when the turn begins with an explicit `/<skill>` invocation and the skill can be
matched against the session `skill_listing`.

| Field | Meaning |
| --- | --- |
| `skill.name` | Skill name, from the resolved `SKILL.md` directory name |
| `skill.description` | Prefer `SKILL.md` frontmatter `description`, then the first body paragraph, then the session skill listing description |
| `skill.path` | Absolute path to the resolved `SKILL.md` |
| `skill_call_id` | Synthetic call ID used to correlate `skill:*` and related `tool:*` spans |
| `skill.source.type` | `workspace`, `user`, or `system` |
| `skill.result_status` | `completed` or `error` |
| `gen_ai.skill.name` | Skill name project extension |
| `gen_ai.skill.path` | Skill path project extension |
| `gen_ai.skill.source.type` | Skill source type project extension |
| `gen_ai.skill.result_status` | Skill result status project extension |
| `gen_ai.skill.description` | Skill description project extension |
| `gen_ai.skill.version` | Prefer `SKILL.md` frontmatter `version`, else nearest `package.json.version` |

Current limitation: skill tags are only emitted for explicit slash-skill
invocations that can be matched against the session `skill_listing`. Passive
skill availability alone does not create skill spans.

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
