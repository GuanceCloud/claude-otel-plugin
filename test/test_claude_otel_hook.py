import contextlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "claude_otel_hook.py"
SPEC = importlib.util.spec_from_file_location("claude_otel_hook", HOOK)
hook = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hook
SPEC.loader.exec_module(hook)


def json_attr(attrs, key):
    return json.loads(attrs[key])


class ClaudeOtelHookTest(unittest.TestCase):
    def test_extract_session_and_transcript_supports_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            payload = {
                "session": {"id": "session-1"},
                "transcript": {"path": str(transcript)},
            }

            session_id, path = hook.extract_session_and_transcript(payload)

            self.assertEqual(session_id, "session-1")
            self.assertEqual(path, transcript.resolve())

    def test_config_prefers_files_over_plugin_env_and_shell_env_over_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            cwd = Path(tmp) / "work"
            (home / ".claude").mkdir(parents=True)
            (cwd / ".claude").mkdir(parents=True)
            (home / ".claude" / "gtrace.json").write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "endpoint": "http://global.example",
                        "headers": {"X-Global": "1"},
                        "resourceAttributes": {"from": "global"},
                    }
                ),
                encoding="utf-8",
            )
            (cwd / ".claude" / "gtrace.json").write_text(
                json.dumps(
                    {
                        "endpoint": "http://local.example",
                        "headers": {"X-Local": "1"},
                        "resourceAttributes": {"from": "local", "local": "yes"},
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "CLAUDE_PLUGIN_OPTION_OTEL_EXPORTER_OTLP_ENDPOINT": "http://plugin.example",
                "CLAUDE_PLUGIN_OPTION_OTEL_EXPORTER_OTLP_HEADERS": "X-Plugin=1",
                "CLAUDE_PLUGIN_OPTION_CLAUDE_OTEL_RESOURCE_ATTRIBUTES": '{"from":"plugin"}',
            }

            config = hook.resolve_config(env=env, home=home, cwd=cwd)

            self.assertTrue(config.enabled)
            self.assertEqual(config.endpoint, "http://local.example")
            self.assertEqual(config.headers["X-Global"], "1")
            self.assertEqual(config.headers["X-Local"], "1")
            self.assertEqual(config.headers["X-Plugin"], "1")
            self.assertEqual(config.resource_attributes["from"], "local")
            self.assertEqual(config.resource_attributes["local"], "yes")

            env["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://env.example"
            config = hook.resolve_config(env=env, home=home, cwd=cwd)

            self.assertEqual(config.endpoint, "http://env.example")

    def test_config_infers_gtrace_metrics_path_from_trace_path(self):
        config = hook.resolve_config(
            env={
                "CLAUDE_OTEL_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://llm-openway.guance.com",
                "CLAUDE_OTEL_TRACE_PATH": "v1/write/otel-llm",
            }
        )

        self.assertEqual(config.trace_url, "https://llm-openway.guance.com/v1/write/otel-llm")
        self.assertEqual(config.metrics_url, "https://llm-openway.guance.com/v1/write/otel-metrics")

    def test_read_new_jsonl_keeps_partial_line_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            first = {"type": "user", "message": {"content": "hello"}}
            second = {"type": "assistant", "message": {"content": "world"}}
            partial = json.dumps(second)
            transcript.write_text(json.dumps(first) + "\n" + partial[:8], encoding="utf-8")
            state = hook.SessionState()

            messages, state = hook.read_new_jsonl(transcript, state)

            self.assertEqual(messages, [first])
            self.assertEqual(state.buffer, partial[:8])

            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(partial[8:] + "\n")

            messages, state = hook.read_new_jsonl(transcript, state)

            self.assertEqual(messages, [second])
            self.assertEqual(state.buffer, "")

    def test_build_turns_groups_assistant_and_tool_results(self):
        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:00Z",
                "message": {"content": "list files"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:00:01Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "ls"}},
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 3},
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:02Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "README.md"},
                    ]
                },
            },
            {
                "isMeta": True,
                "sourceToolUseID": "tool-1",
                "message": {"content": [{"type": "text", "text": "injected"}]},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:00:03Z",
                "message": {
                    "id": "msg-2",
                    "model": "claude-test",
                    "content": [{"type": "text", "text": "found README.md"}],
                },
            },
        ]

        turns = hook.build_turns(messages)

        self.assertEqual(len(turns), 1)
        self.assertEqual(len(turns[0].assistant_msgs), 2)
        self.assertEqual(turns[0].tool_results_by_id["tool-1"]["content"], "README.md")
        self.assertEqual(turns[0].injected_by_tool_id["tool-1"], "injected")
        self.assertEqual(hook.get_usage(turns[0].assistant_msgs[0])["input_tokens"], 10)

    def test_build_turns_captures_turn_duration_and_tool_duration(self):
        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:00Z",
                "message": {"content": "weather"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:00:02Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebSearch", "input": {"query": "sz"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-16T01:10:00Z",
                "toolUseResult": {"durationSeconds": 15.4},
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "rain"},
                    ]
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:10:01Z",
                "isApiErrorMessage": True,
                "apiErrorStatus": 400,
                "message": {
                    "id": "msg-2",
                    "model": "<synthetic>",
                    "content": [{"type": "text", "text": "API Error: 400 context_management: Extra inputs are not permitted"}],
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 21840,
            },
        ]

        turns = hook.build_turns(messages)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].turn_duration_ms, 21840)
        self.assertEqual(turns[0].tool_results_by_id["tool-1"]["duration_seconds"], 15.4)

    def test_build_turns_reads_tool_duration_ms_when_seconds_missing(self):
        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-25T07:54:15.018Z",
                "message": {"content": "today weather"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T07:58:50.792Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebFetch", "input": {"url": "https://example.com"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-25T07:59:39.935Z",
                "toolUseResult": {"durationMs": 3926},
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"},
                    ]
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T07:59:44.713Z",
                "message": {
                    "id": "msg-2",
                    "model": "claude-test",
                    "content": [{"type": "text", "text": "summary"}],
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 144338,
            },
        ]

        turns = hook.build_turns(messages)

        self.assertEqual(len(turns), 1)
        self.assertAlmostEqual(turns[0].tool_results_by_id["tool-1"]["duration_seconds"], 3.926)

    def test_extract_skill_listing_map_prefers_skill_file_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            skill_dir = cwd / ".claude" / "skills" / "review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: review\ndescription: Review skill from frontmatter.\nversion: 2.4.6\n---\n\n# Review\n",
                encoding="utf-8",
            )
            msg = {
                "attachment": {
                    "type": "skill_listing",
                    "names": ["review"],
                    "content": "- review: fallback description from listing",
                }
            }

            catalog = hook.extract_skill_listing_map(msg, cwd)

            self.assertEqual(catalog["review"]["name"], "review")
            self.assertEqual(catalog["review"]["description"], "Review skill from frontmatter.")
            self.assertEqual(catalog["review"]["source_type"], "workspace")
            self.assertTrue(catalog["review"]["path"].endswith("/review/SKILL.md"))
            self.assertEqual(catalog["review"]["version"], "2.4.6")

    def test_build_turns_with_pending_defers_trailing_incomplete_turn(self):
        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-25T09:18:25.498Z",
                "message": {"content": "today weather"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T09:18:26.978Z",
                "isApiErrorMessage": True,
                "apiErrorStatus": 403,
                "message": {
                    "id": "msg-1",
                    "model": "<synthetic>",
                    "content": [{"type": "text", "text": "API Error: 403 insufficient balance"}],
                },
            },
        ]

        turns, pending_messages = hook.build_turns_with_pending(messages)

        self.assertEqual(turns, [])
        self.assertEqual(pending_messages, messages)

        turns, pending_messages = hook.build_turns_with_pending(
            messages + [{"type": "system", "subtype": "turn_duration", "durationMs": 1447}]
        )

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].turn_duration_ms, 1447)
        self.assertEqual(pending_messages, [])

    def test_build_turns_merges_repeated_assistant_snapshots_by_message_id(self):
        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-25T06:41:36.000Z",
                "message": {"role": "user", "content": "today ai headlines"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.195Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I'll search for today's top AI news."}],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.205Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebSearch", "input": {"query": "AI news June 25 2026"}},
                    ],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.227Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tool-2", "name": "WebSearch", "input": {"query": "artificial intelligence headlines today"}},
                    ],
                },
            },
        ]

        turns = hook.build_turns(messages)

        self.assertEqual(len(turns), 1)
        self.assertEqual(len(turns[0].assistant_msgs), 1)
        merged = turns[0].assistant_msgs[0]
        self.assertEqual(hook.extract_text(hook.get_content(merged)), "I'll search for today's top AI news.")
        self.assertEqual(
            [block["id"] for block in hook.iter_tool_uses(hook.get_content(merged))],
            ["tool-1", "tool-2"],
        )
        self.assertEqual(merged["timestamp"], "2026-06-25T06:41:42.195Z")

    def test_usage_details_matches_genai_token_accounting(self):
        details = hook.usage_details(
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 5,
            }
        )

        self.assertEqual(details["input"], 135)
        self.assertEqual(details["output"], 20)
        self.assertEqual(details["cache_read_input_tokens"], 30)
        self.assertEqual(details["cache_creation_input_tokens"], 5)

    def test_runtime_metadata_contains_agent_version_and_host(self):
        runtime = hook.extract_runtime_metadata(
            [{"version": "2.1.178"}, {"type": "assistant"}],
            {},
        )

        self.assertEqual(runtime.agent_version, "2.1.178")
        self.assertTrue(isinstance(runtime.host, str) and len(runtime.host) > 0)

    def test_runtime_resource_attributes_include_agent_version_and_host(self):
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        attrs = hook.runtime_resource_attributes(
            config,
            hook.RuntimeMetadata(agent_version="2.1.178", host="liurui"),
        )

        self.assertEqual(attrs["agent_runtime"], "claude-code")
        self.assertEqual(attrs["gen_ai.agent.version"], "2.1.178")
        self.assertEqual(attrs["host"], "liurui")
        self.assertEqual(attrs["host.name"], "liurui")

    def test_metric_base_attrs_include_host_tags(self):
        attrs = hook.metric_base_attrs(
            {
                "gen_ai.conversation.id": "s1",
                "gen_ai.provider.name": "anthropic",
                "gen_ai.request.model": "claude-opus-4-8",
                "gen_ai.response.model": "claude-opus-4-8",
            }
        )

        self.assertEqual(attrs["gen_ai.conversation.id"], "s1")
        self.assertEqual(attrs["session_id"], "s1")
        self.assertEqual(attrs["gen_ai.provider.name"], "anthropic")
        self.assertEqual(attrs["gen_ai.request.model"], "claude-opus-4-8")
        self.assertEqual(attrs["gen_ai.response.model"], "claude-opus-4-8")
        self.assertTrue(isinstance(attrs["host"], str) and len(attrs["host"]) > 0)
        self.assertEqual(attrs["host.name"], attrs["host"])

    def test_emit_turn_uses_codex_compatible_span_names(self):
        class FakeTraceAPI:
            @staticmethod
            def set_span_in_context(span):
                return span

        class FakeSpan:
            def __init__(self, name, attributes, start_time=None):
                self.name = name
                self.attributes = attributes
                self.start_time = start_time
                self.ended = False

            def end(self, end_time=None):
                self.ended = True
                self.end_time = end_time

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeTracer:
            def __init__(self):
                self.spans = []

            def start_span(self, name, context=None, start_time=None, attributes=None):
                span = FakeSpan(name, attributes or {}, start_time=start_time)
                self.spans.append(span)
                return span

        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:00Z",
                "cwd": "/tmp/project",
                "gitBranch": "main",
                "message": {"content": "list files"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:00:01Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "text", "text": "I'll inspect."},
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "ls"}},
                    ],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "cache_read_input_tokens": 25,
                    },
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:02Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "README.md"},
                    ]
                },
            },
        ]
        turn = hook.build_turns(messages)[0]
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        tracer = FakeTracer()

        hook.emit_turn(FakeTraceAPI, tracer, None, config, "session-1", 1, turn, Path("/tmp/session.jsonl"))

        self.assertEqual([span.name for span in tracer.spans], ["invoke_agent", "llm", "tool:Bash", "assistant"])
        root = tracer.spans[0].attributes
        llm = tracer.spans[1].attributes
        tool = tracer.spans[2].attributes
        self.assertEqual(root["gen_ai.agent.name"], "claude-code")
        self.assertEqual(root["gen_ai.operation.name"], "invoke_agent")
        self.assertEqual(root["gen_ai.conversation.id"], "session-1")
        self.assertEqual(root["session_id"], "session-1")
        self.assertEqual(root["gen_ai.provider.name"], "anthropic")
        self.assertEqual(root["gen_ai.usage.input_tokens"], 125)
        self.assertEqual(root["gen_ai.usage.cache_read.input_tokens"], 25)
        self.assertEqual(
            json_attr(root, "gen_ai.input.messages"),
            [{"role": "user", "parts": [{"type": "text", "content": "list files"}]}],
        )
        self.assertEqual(
            json_attr(llm, "gen_ai.input.messages"),
            [{"role": "user", "parts": [{"type": "text", "content": "list files"}]}],
        )
        self.assertEqual(
            json_attr(llm, "gen_ai.output.messages"),
            [{
                "role": "assistant",
                "parts": [
                    {"type": "text", "content": "I'll inspect."},
                    {"type": "tool_call", "name": "Bash", "id": "tool-1", "arguments": "{\"command\": \"ls\"}"},
                ],
            }],
        )
        self.assertEqual(llm["output_kind"], "tool_call")
        self.assertEqual(llm["gen_ai.operation.name"], "chat")
        self.assertEqual(tool["gen_ai.operation.name"], "execute_tool")
        self.assertEqual(tool["gen_ai.tool.name"], "Bash")
        self.assertEqual(tool["gen_ai.tool.call.id"], "tool-1")
        self.assertEqual(tool["gen_ai.tool.call.arguments"], "{\"command\": \"ls\"}")
        self.assertEqual(tool["gen_ai.tool.call.result"], "README.md")
        self.assertEqual(tool["tool_command"], "ls")

    def test_emit_turn_marks_api_errors_and_prefers_recorded_durations(self):
        class FakeTraceAPI:
            @staticmethod
            def set_span_in_context(span):
                return span

        class FakeSpan:
            def __init__(self, name, attributes, start_time=None):
                self.name = name
                self.attributes = attributes
                self.start_time = start_time
                self.end_time = None

            def end(self, end_time=None):
                self.end_time = end_time

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeTracer:
            def __init__(self):
                self.spans = []

            def start_span(self, name, context=None, start_time=None, attributes=None):
                span = FakeSpan(name, attributes or {}, start_time=start_time)
                self.spans.append(span)
                return span

        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-16T01:00:00Z",
                "message": {"content": "weather"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:00:02Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebSearch", "input": {"query": "sz"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-16T01:10:00Z",
                "toolUseResult": {"durationSeconds": 15.0},
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "rain"},
                    ]
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-16T01:10:01Z",
                "isApiErrorMessage": True,
                "apiErrorStatus": 400,
                "message": {
                    "id": "msg-2",
                    "model": "<synthetic>",
                    "content": [{"type": "text", "text": "API Error: 400 context_management: Extra inputs are not permitted"}],
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 21000,
            },
        ]
        turn = hook.build_turns(messages)[0]
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        tracer = FakeTracer()

        hook.emit_turn(FakeTraceAPI, tracer, None, config, "session-1", 1, turn, Path("/tmp/session.jsonl"))

        root = tracer.spans[0]
        tool = tracer.spans[2]
        error_llm = tracer.spans[3]
        self.assertEqual(root.attributes["status"], "error")
        self.assertEqual(root.attributes["final_status"], "error")
        self.assertEqual(root.attributes["error.type"], "context_management")
        self.assertEqual(root.attributes["http.status_code"], 400)
        self.assertEqual((root.end_time - root.start_time) / 1_000_000_000, 21)
        self.assertEqual((tool.end_time - tool.start_time) / 1_000_000_000, 15)
        self.assertEqual(error_llm.attributes["status"], "error")
        self.assertLessEqual((error_llm.end_time - error_llm.start_time) / 1_000_000_000, 6)

    def test_emit_turn_adds_skill_tags_to_skill_and_tool_spans(self):
        class FakeTraceAPI:
            @staticmethod
            def set_span_in_context(span):
                return span

        class FakeSpan:
            def __init__(self, name, attributes, start_time=None):
                self.name = name
                self.attributes = attributes
                self.start_time = start_time
                self.end_time = None

            def end(self, end_time=None):
                self.end_time = end_time

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeTracer:
            def __init__(self):
                self.spans = []

            def start_span(self, name, context=None, start_time=None, attributes=None):
                span = FakeSpan(name, attributes or {}, start_time=start_time)
                self.spans.append(span)
                return span

        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-26T01:00:00Z",
                "message": {"content": "/review current diff"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-26T01:00:01Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "content": [
                        {"type": "text", "text": "I'll inspect the diff."},
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "git diff --stat"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-26T01:00:02Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "README.md | 2 +-"},
                    ]
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 2200,
            },
        ]
        turn = hook.build_turns(messages)[0]
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        tracer = FakeTracer()
        skill_catalog = {
            "review": {
                "name": "review",
                "description": "Review a pull request",
                "path": "/tmp/review/SKILL.md",
                "source_type": "system",
                "version": "1.7.0",
            }
        }

        hook.emit_turn(
            FakeTraceAPI,
            tracer,
            None,
            config,
            "session-1",
            1,
            turn,
            Path("/tmp/session.jsonl"),
            skill_catalog=skill_catalog,
        )

        by_name = {span.name: span for span in tracer.spans}
        skill_span = by_name["skill:review"]
        tool_span = by_name["tool:Bash"]
        self.assertEqual(skill_span.attributes["skill.name"], "review")
        self.assertEqual(skill_span.attributes["skill.description"], "Review a pull request")
        self.assertEqual(skill_span.attributes["skill.path"], "/tmp/review/SKILL.md")
        self.assertEqual(skill_span.attributes["skill.source.type"], "system")
        self.assertEqual(skill_span.attributes["skill.result_status"], "completed")
        self.assertEqual(skill_span.attributes["gen_ai.skill.name"], "review")
        self.assertEqual(skill_span.attributes["gen_ai.skill.version"], "1.7.0")
        self.assertEqual(tool_span.attributes["skill.name"], "review")
        self.assertEqual(tool_span.attributes["skill.description"], "Review a pull request")
        self.assertEqual(tool_span.attributes["skill.path"], "/tmp/review/SKILL.md")
        self.assertEqual(tool_span.attributes["skill.source.type"], "system")
        self.assertEqual(tool_span.attributes["skill.result_status"], "completed")
        self.assertEqual(tool_span.attributes["gen_ai.skill.name"], "review")
        self.assertEqual(tool_span.attributes["gen_ai.skill.version"], "1.7.0")
        self.assertEqual(tool_span.attributes["skill_call_id"], skill_span.attributes["skill_call_id"])

    def test_emit_turn_produces_positive_durations_for_realistic_tool_turn(self):
        class FakeTraceAPI:
            @staticmethod
            def set_span_in_context(span):
                return span

        class FakeSpan:
            def __init__(self, name, attributes, start_time=None):
                self.name = name
                self.attributes = attributes
                self.start_time = start_time
                self.end_time = None

            def end(self, end_time=None):
                self.end_time = end_time

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeTracer:
            def __init__(self):
                self.spans = []

            def start_span(self, name, context=None, start_time=None, attributes=None):
                span = FakeSpan(name, attributes or {}, start_time=start_time)
                self.spans.append(span)
                return span

        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-25T06:41:36.000Z",
                "cwd": "/home/liurui/.claude",
                "gitBranch": "HEAD",
                "message": {"role": "user", "content": "today ai headlines"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.195Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I'll search for today's top AI news."}],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.205Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebSearch", "input": {"query": "AI news June 25 2026"}},
                    ],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:41:42.227Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tool-2", "name": "WebSearch", "input": {"query": "artificial intelligence headlines today"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-25T06:42:10.272Z",
                "toolUseResult": {"durationSeconds": 14.614211645999996},
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-2", "content": "news result 2"},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-25T06:42:15.328Z",
                "toolUseResult": {"durationSeconds": 18.989059140000005},
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "news result 1"},
                    ],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T06:42:36.097Z",
                "message": {
                    "id": "msg-3",
                    "model": "claude-opus-4-8",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "summary"}],
                    "usage": {
                        "input_tokens": 1293,
                        "cache_creation_input_tokens": 4486,
                        "cache_read_input_tokens": 32344,
                        "output_tokens": 1356,
                    },
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 48448,
            },
        ]

        turn = hook.build_turns(messages)[0]
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        tracer = FakeTracer()

        hook.emit_turn(FakeTraceAPI, tracer, None, config, "session-1", 1, turn, Path("/tmp/session.jsonl"))

        by_name = {}
        for span in tracer.spans:
            by_name.setdefault(span.name, []).append(span)
        root = by_name["invoke_agent"][0]
        llm_first, llm_second = by_name["llm"]
        tool_first, tool_second = by_name["tool:WebSearch"]
        assistant_spans = by_name["assistant"]

        self.assertGreater(root.end_time - root.start_time, 0)
        self.assertGreater(llm_first.end_time - llm_first.start_time, 0)
        self.assertGreater(tool_first.end_time - tool_first.start_time, 0)
        self.assertGreater(llm_second.end_time - llm_second.start_time, 0)
        self.assertGreater(tool_second.end_time - tool_second.start_time, 0)
        self.assertEqual(len(assistant_spans), 2)
        self.assertGreater(assistant_spans[0].end_time - assistant_spans[0].start_time, 0)
        self.assertEqual(assistant_spans[1].end_time - assistant_spans[1].start_time, 0)
        self.assertEqual((root.end_time - root.start_time) / 1_000_000_000, 60.096999936)
        self.assertEqual(
            json_attr(root.attributes, "gen_ai.input.messages"),
            [{"role": "user", "parts": [{"type": "text", "content": "today ai headlines"}]}],
        )
        self.assertEqual(
            json_attr(llm_first.attributes, "gen_ai.output.messages"),
            [{
                "role": "assistant",
                "parts": [
                    {"type": "text", "content": "I'll search for today's top AI news."},
                    {"type": "tool_call", "name": "WebSearch", "id": "tool-1", "arguments": "{\"query\": \"AI news June 25 2026\"}"},
                    {"type": "tool_call", "name": "WebSearch", "id": "tool-2", "arguments": "{\"query\": \"artificial intelligence headlines today\"}"},
                ],
            }],
        )
        self.assertEqual(
            json_attr(llm_second.attributes, "gen_ai.input.messages"),
            [{
                "role": "tool",
                "name": "WebSearch",
                "parts": [{
                    "type": "tool_call_response",
                    "id": "tool-1",
                    "response": "news result 1",
                }],
            }, {
                "role": "tool",
                "name": "WebSearch",
                "parts": [{
                    "type": "tool_call_response",
                    "id": "tool-2",
                    "response": "news result 2",
                }],
            }],
        )
        self.assertEqual(
            json_attr(llm_second.attributes, "gen_ai.output.messages"),
            [{"role": "assistant", "parts": [{"type": "text", "content": "summary"}]}],
        )

    def test_emit_turn_keeps_final_llm_duration_when_recorded_turn_duration_is_too_short(self):
        class FakeTraceAPI:
            @staticmethod
            def set_span_in_context(span):
                return span

        class FakeSpan:
            def __init__(self, name, attributes, start_time=None):
                self.name = name
                self.attributes = attributes
                self.start_time = start_time
                self.end_time = None

            def end(self, end_time=None):
                self.end_time = end_time

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeTracer:
            def __init__(self):
                self.spans = []

            def start_span(self, name, context=None, start_time=None, attributes=None):
                span = FakeSpan(name, attributes or {}, start_time=start_time)
                self.spans.append(span)
                return span

        messages = [
            {
                "type": "user",
                "timestamp": "2026-06-25T07:54:15.018Z",
                "message": {"role": "user", "content": "today weather"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T07:58:50.792Z",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "WebFetch", "input": {"url": "https://example.com"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-25T07:59:39.935Z",
                "toolUseResult": {"durationMs": 3926},
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"},
                    ],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-25T07:59:44.713Z",
                "message": {
                    "id": "msg-2",
                    "model": "claude-test",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "summary"}],
                },
            },
            {
                "type": "system",
                "subtype": "turn_duration",
                "durationMs": 144338,
            },
        ]

        turn = hook.build_turns(messages)[0]
        config = hook.resolve_config(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
        tracer = FakeTracer()

        hook.emit_turn(FakeTraceAPI, tracer, None, config, "session-1", 1, turn, Path("/tmp/session.jsonl"))

        llm_spans = [span for span in tracer.spans if span.name == "llm"]
        tool_span = next(span for span in tracer.spans if span.name == "tool:WebFetch")
        final_llm = llm_spans[-1]
        root = tracer.spans[0]

        self.assertGreater(tool_span.end_time - tool_span.start_time, 0)
        self.assertGreater(final_llm.end_time - final_llm.start_time, 0)
        self.assertGreater(root.end_time - root.start_time, 144338000000)

    def test_metric_recorders_use_genai_semantic_tags(self):
        class FakeHistogram:
            def __init__(self):
                self.records = []

            def record(self, value, attributes):
                self.records.append((value, attributes))

        class FakeMetrics:
            def __init__(self):
                self.workflow_duration = FakeHistogram()
                self.operation_duration = FakeHistogram()
                self.token_usage = FakeHistogram()

        metrics = FakeMetrics()
        llm_attrs = {
            "gen_ai.conversation.id": "s1",
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-test",
            "gen_ai.response.model": "claude-test",
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 20,
            "gen_ai.usage.cache_read.input_tokens": 30,
        }
        tool_attrs = {
            **llm_attrs,
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "Bash",
            "tool_result_status": "completed",
        }

        hook.record_request_metrics(metrics, {**llm_attrs, "final_status": "completed"}, 1.5)
        hook.record_operation_metrics(metrics, llm_attrs, 0.25, "chat")
        hook.record_operation_metrics(metrics, tool_attrs, 0.5, "execute_tool")
        hook.record_token_metrics(metrics, llm_attrs)

        self.assertEqual(metrics.workflow_duration.records[0][0], 1.5)
        self.assertEqual(metrics.workflow_duration.records[0][1]["session_id"], "s1")
        self.assertEqual(metrics.workflow_duration.records[0][1]["gen_ai.conversation.id"], "s1")
        self.assertEqual(metrics.operation_duration.records[0][1]["gen_ai.operation.name"], "chat")
        self.assertEqual(metrics.operation_duration.records[1][1]["gen_ai.operation.name"], "execute_tool")
        self.assertEqual(metrics.operation_duration.records[1][1]["gen_ai.tool.name"], "Bash")
        self.assertEqual(
            [attrs["gen_ai.token.type"] for _, attrs in metrics.token_usage.records],
            ["input", "output"],
        )

    def test_run_is_fail_open_when_disabled_or_missing_dependency(self):
        payload = json.dumps({"session_id": "s1", "transcript_path": "/tmp/missing.jsonl"})

        status = hook.run(payload, env={})

        self.assertEqual(status, 0)

    def test_run_does_not_advance_state_when_trace_flush_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text('{"type":"user"}\n', encoding="utf-8")
            payload = json.dumps({"session_id": "s1", "transcript_path": str(transcript)})
            saved_states = []

            class FakeProvider:
                pass

            with mock.patch.object(hook, "FileLock"), \
                mock.patch.object(hook, "load_state", return_value={}), \
                mock.patch.object(hook, "save_state", side_effect=lambda state: saved_states.append(state.copy())), \
                mock.patch.object(hook, "read_new_jsonl", return_value=([{"version": "2.1.191"}], hook.SessionState(offset=12))), \
                mock.patch.object(hook, "create_tracer_provider", return_value=(object(), FakeProvider(), object(), hook.TraceExportTracker(export_calls=1))), \
                mock.patch.object(hook, "create_metrics_provider", return_value=None), \
                mock.patch.object(hook, "build_turns_with_pending", return_value=([object()], [])), \
                mock.patch.object(hook, "emit_turn"), \
                mock.patch.object(hook, "flush_provider", return_value=False):
                status = hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )

        self.assertEqual(status, 0)
        self.assertEqual(saved_states, [])

    def test_run_buffers_incomplete_turn_until_duration_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "timestamp": "2026-06-25T09:18:25.498Z",
                                "message": {"content": "today weather"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "timestamp": "2026-06-25T09:18:26.978Z",
                                "isApiErrorMessage": True,
                                "apiErrorStatus": 403,
                                "message": {
                                    "id": "msg-1",
                                    "model": "<synthetic>",
                                    "content": [{"type": "text", "text": "API Error: 403 insufficient balance"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            payload = json.dumps({"session_id": "s1", "transcript_path": str(transcript)})
            persisted_state = {}

            class FakeProvider:
                pass

            emitted_turns = []

            def load_state():
                return json.loads(json.dumps(persisted_state))

            def save_state(state):
                persisted_state.clear()
                persisted_state.update(json.loads(json.dumps(state)))

            with mock.patch.object(hook, "FileLock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()), \
                mock.patch.object(hook, "load_state", side_effect=load_state), \
                mock.patch.object(hook, "save_state", side_effect=save_state), \
                mock.patch.object(hook, "create_tracer_provider", return_value=(object(), FakeProvider(), object(), hook.TraceExportTracker(export_calls=1))), \
                mock.patch.object(hook, "create_metrics_provider", return_value=None), \
                mock.patch.object(hook, "emit_turn", side_effect=lambda *args: emitted_turns.append(args[5])), \
                mock.patch.object(hook, "flush_provider", return_value=True):
                status = hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )

                self.assertEqual(status, 0)
                self.assertEqual(emitted_turns, [])

                key = hook.state_key("s1", str(transcript.resolve()))
                self.assertEqual(persisted_state[key]["turn_count"], 0)
                self.assertEqual(len(persisted_state[key]["pending_messages"]), 2)

                with transcript.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "system", "subtype": "turn_duration", "durationMs": 1447}) + "\n")

                status = hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )

        self.assertEqual(status, 0)
        self.assertEqual(emitted_turns, [1])
        self.assertEqual(persisted_state[key]["turn_count"], 1)
        self.assertEqual(persisted_state[key]["pending_messages"], [])

    def test_run_flushes_stop_turn_without_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "timestamp": "2026-06-29T08:46:49.605Z",
                                "message": {"role": "user", "content": "reply ok"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "timestamp": "2026-06-29T08:46:58.509Z",
                                "message": {
                                    "id": "msg-1",
                                    "model": "claude-test",
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "ok"}],
                                    "usage": {"input_tokens": 10, "output_tokens": 1},
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            payload = json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": "s1",
                    "transcript_path": str(transcript),
                }
            )
            persisted_state = {}

            class FakeProvider:
                pass

            emitted_turns = []

            def load_state():
                return json.loads(json.dumps(persisted_state))

            def save_state(state):
                persisted_state.clear()
                persisted_state.update(json.loads(json.dumps(state)))

            with mock.patch.object(hook, "FileLock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()), \
                mock.patch.object(hook, "load_state", side_effect=load_state), \
                mock.patch.object(hook, "save_state", side_effect=save_state), \
                mock.patch.object(hook, "create_tracer_provider", return_value=(object(), FakeProvider(), object(), hook.TraceExportTracker(export_calls=1))), \
                mock.patch.object(hook, "create_metrics_provider", return_value=None), \
                mock.patch.object(hook, "emit_turn", side_effect=lambda *args: emitted_turns.append(args[5])), \
                mock.patch.object(hook, "flush_provider", return_value=True):
                status = hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )

        key = hook.state_key("s1", str(transcript.resolve()))
        self.assertEqual(status, 0)
        self.assertEqual(emitted_turns, [1])
        self.assertEqual(persisted_state[key]["turn_count"], 1)
        self.assertEqual(persisted_state[key]["pending_messages"], [])

    def test_run_flushes_pending_turn_when_no_new_messages_arrive(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "timestamp": "2026-06-29T08:46:49.605Z",
                                "message": {"role": "user", "content": "reply ok"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "timestamp": "2026-06-29T08:46:58.509Z",
                                "message": {
                                    "id": "msg-1",
                                    "model": "claude-test",
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "ok"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            payload = json.dumps({"session_id": "s1", "transcript_path": str(transcript)})
            persisted_state = {}

            class FakeProvider:
                pass

            emitted_turns = []

            def load_state():
                return json.loads(json.dumps(persisted_state))

            def save_state(state):
                persisted_state.clear()
                persisted_state.update(json.loads(json.dumps(state)))

            with mock.patch.object(hook, "FileLock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()), \
                mock.patch.object(hook, "load_state", side_effect=load_state), \
                mock.patch.object(hook, "save_state", side_effect=save_state), \
                mock.patch.object(hook, "create_tracer_provider", return_value=(object(), FakeProvider(), object(), hook.TraceExportTracker(export_calls=1))), \
                mock.patch.object(hook, "create_metrics_provider", return_value=None), \
                mock.patch.object(hook, "emit_turn", side_effect=lambda *args: emitted_turns.append(args[5])), \
                mock.patch.object(hook, "flush_provider", return_value=True):
                hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )
                status = hook.run(
                    payload,
                    env={
                        "CLAUDE_OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                    },
                )

        key = hook.state_key("s1", str(transcript.resolve()))
        self.assertEqual(status, 0)
        self.assertEqual(emitted_turns, [1])
        self.assertEqual(persisted_state[key]["turn_count"], 1)
        self.assertEqual(persisted_state[key]["pending_messages"], [])


if __name__ == "__main__":
    unittest.main()
