"""Stage 6 local trace foundation contract tests.

这些测试只定义 local-only observability 基础：显式安全路径、结构化 trace event、
脱敏 metadata、确定性 JSONL。它不读取真实 agent_log.jsonl，不读取 sessions/runs，
不接 provider/network，也不要求 runtime core 立刻重写为 tracing framework。
"""

from __future__ import annotations

import json


def test_trace_event_requires_run_trace_and_span_identity() -> None:
    """trace event 必须携带可串联的 run/trace/span 字段，而不是自由 dict。"""

    from agent.local_trace import TraceEvent

    event = TraceEvent(
        run_id="run-test",
        trace_id="trace-test",
        span_id="span-model-1",
        parent_span_id=None,
        span_type="model_call",
        name="anthropic.messages.stream",
        status="ok",
        step_id="step-1",
        metadata={"model": "test-model"},
    )

    payload = event.to_json_dict()

    assert payload["run_id"] == "run-test"
    assert payload["trace_id"] == "trace-test"
    assert payload["span_id"] == "span-model-1"
    assert payload["span_type"] == "model_call"
    assert payload["step_id"] == "step-1"
    assert payload["metadata"] == {"model": "test-model"}


def test_trace_metadata_redacts_secret_like_values_without_env_expansion() -> None:
    """trace metadata 可以帮助排查，但不能把 token/env secret 写入本地 trace。"""

    from agent.local_trace import TraceEvent

    event = TraceEvent(
        run_id="run-test",
        trace_id="trace-test",
        span_id="span-tool-1",
        parent_span_id="span-model-1",
        span_type="tool_call",
        name="read_file",
        status="failed",
        metadata={
            "api_key": "sk-test-secret",
            "nested": {"token": "abc123-secret-token", "path": "${HOME}/.mcp.json"},
            "argv": ["echo", "$ANTHROPIC_API_KEY"],
        },
    )

    encoded = json.dumps(event.to_json_dict(), ensure_ascii=False)

    assert "sk-test-secret" not in encoded
    assert "abc123-secret-token" not in encoded
    assert "$ANTHROPIC_API_KEY" in encoded
    assert "${HOME}/.mcp.json" in encoded
    assert "[REDACTED]" in encoded


def test_trace_recorder_writes_deterministic_jsonl_to_explicit_safe_path(tmp_path) -> None:
    """recorder 只能写显式 tmp_path，避免把测试 trace 误写到真实 runs/sessions。"""

    from agent.local_trace import LocalTraceRecorder, TraceEvent

    output_path = tmp_path / "trace.jsonl"
    recorder = LocalTraceRecorder(output_path)
    recorder.record(
        TraceEvent(
            run_id="run-test",
            trace_id="trace-test",
            span_id="span-state-1",
            parent_span_id=None,
            span_type="state_transition",
            name="awaiting_plan_confirmation -> running",
            status="ok",
            metadata={"from": "awaiting_plan_confirmation", "to": "running"},
        )
    )
    recorder.record(
        TraceEvent(
            run_id="run-test",
            trace_id="trace-test",
            span_id="span-checkpoint-1",
            parent_span_id="span-state-1",
            span_type="checkpoint",
            name="save_checkpoint",
            status="ok",
            metadata={"source": "tests"},
        )
    )

    recorder.write_jsonl()
    lines = output_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["span_id"] == "span-state-1"
    assert json.loads(lines[1])["parent_span_id"] == "span-state-1"
    assert lines == sorted(lines, key=lambda line: json.loads(line)["sequence"])


def test_trace_recorder_rejects_repo_runtime_artifact_paths(tmp_path) -> None:
    """local trace foundation 不得写真实 sessions/runs/agent_log 路径。"""

    import pytest

    from agent.local_trace import LocalTraceRecorder, TracePathPolicyError

    unsafe_paths = [
        "agent_log.jsonl",
        "sessions/demo/trace.jsonl",
        "runs/demo/trace.jsonl",
    ]

    for path in unsafe_paths:
        with pytest.raises(TracePathPolicyError):
            LocalTraceRecorder(path)

    # tmp_path 下的显式路径仍允许，方便后续 dogfooding / tests 写 fake trace。
    LocalTraceRecorder(tmp_path / "safe-trace.jsonl")
