"""MCP Boundary Hardening Phase 1 — MCP audit evidence 针对性测试。

测试覆盖：
A. MCP audit events 通过 record_evidence(subsystem="mcp") 写入 per-session events.jsonl
B. fake / real 区分：dry_run / transport 字段在 evidence metadata 中可见
C. safe_summary 不包含 raw config/descriptor/secret
D. ToolRuntimeMediator MCP tool execution 不回归（仍走普通 tool evidence）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _setup_session_context():
    """注入最小 session 上下文，使 record_evidence 正常工作。"""
    from agent.evidence_recorder import set_session_context

    set_session_context(
        session_id="test-mcp-audit-sid",
        entry="plain",
        provider_type="fake",
        provider_model="fake-model",
    )


def _captured_evidence(envelopes: list[dict[str, Any]], operation: str) -> dict[str, Any] | None:
    """从 captured envelopes 中查找指定 operation 的 evidence。"""
    for env in envelopes:
        if env.get("operation") == operation:
            return env
    return None


# ═══════════════════════════════════════════════════════════════════
# A: MCP audit events use record_evidence
# ═══════════════════════════════════════════════════════════════════


class TestMCPAuditEvidenceRecorded:
    """A: 验证 MCP audit events 通过 record_evidence 写入。"""

    def test_a1_server_discovered_uses_record_evidence(self, monkeypatch):
        """A1: emit_mcp_server_discovered 调用 record_evidence(subsystem="mcp")。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered

        emit_mcp_server_discovered("demo_srv", dry_run=True, transport="fake")

        assert len(captured) >= 1
        call = captured[0]
        assert call["subsystem"] == "mcp"
        assert call["operation"] == "server_discovered"
        assert call["status"] == "allowed"
        assert "demo_srv" in str(call["safe_summary"])
        assert "dry_run" in str(call["safe_summary"]).lower() or \
            "dry_run" in str(call.get("metadata", {}))

    def test_a2_server_blocked_uses_record_evidence(self, monkeypatch):
        """A2: emit_mcp_server_blocked 调用 record_evidence(subsystem="mcp")。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_blocked

        emit_mcp_server_blocked(
            "bad_srv", reason="not in allowlist", dry_run=False, transport="stdio"
        )

        assert len(captured) >= 1
        call = captured[0]
        assert call["subsystem"] == "mcp"
        assert call["operation"] == "server_blocked"
        assert call["status"] == "blocked"
        assert "bad_srv" in str(call["safe_summary"])
        assert call.get("reason_code") == "not in allowlist"

    def test_a3_tools_listed_uses_record_evidence(self, monkeypatch):
        """A3: emit_mcp_tools_listed 调用 record_evidence(subsystem="mcp")。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tools_listed

        emit_mcp_tools_listed("demo_srv", tool_count=5, dry_run=True, transport="fake")

        assert len(captured) >= 1
        call = captured[0]
        assert call["subsystem"] == "mcp"
        assert call["operation"] == "tools_listed"
        assert call["status"] == "listed"
        metadata = call.get("metadata", {})
        assert metadata.get("tool_count") == 5

    def test_a4_tool_registered_uses_record_evidence(self, monkeypatch):
        """A4: emit_mcp_tool_registered 调用 record_evidence(subsystem="mcp")。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tool_registered

        emit_mcp_tool_registered("demo_srv", "hello", dry_run=False, transport="stdio")

        assert len(captured) >= 1
        call = captured[0]
        assert call["subsystem"] == "mcp"
        assert call["operation"] == "tool_registered"
        assert call["status"] == "registered"
        metadata = call.get("metadata", {})
        assert metadata.get("tool_name") == "hello"

    def test_a5_tool_blocked_uses_record_evidence(self, monkeypatch):
        """A5: emit_mcp_tool_blocked 调用 record_evidence(subsystem="mcp")。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tool_blocked

        emit_mcp_tool_blocked(
            "demo_srv", "dangerous_tool",
            reason="unknown risk level",
            dry_run=True, transport="fake",
        )

        assert len(captured) >= 1
        call = captured[0]
        assert call["subsystem"] == "mcp"
        assert call["operation"] == "tool_blocked"
        assert call["status"] == "blocked"
        metadata = call.get("metadata", {})
        assert metadata.get("tool_name") == "dangerous_tool"
        assert call.get("reason_code") == "unknown risk level"


# ═══════════════════════════════════════════════════════════════════
# B: fake / real 区分
# ═══════════════════════════════════════════════════════════════════


class TestMCPAuditFakeRealDifferentiation:
    """B: 验证 fake/real path 在 evidence metadata 中可区分。"""

    def test_b1_fake_path_has_dry_run_true(self, monkeypatch):
        """B1: dry_run=True, transport="fake" 时 evidence 可见。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered

        emit_mcp_server_discovered("fake_srv", dry_run=True, transport="fake")

        call = captured[0]
        metadata = call.get("metadata", {})
        assert metadata.get("dry_run") is True
        assert metadata.get("transport") == "fake"

    def test_b2_real_path_has_dry_run_false(self, monkeypatch):
        """B2: dry_run=False, transport="stdio" 时 evidence 可见。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tool_registered

        emit_mcp_tool_registered("real_srv", "hello", dry_run=False, transport="stdio")

        call = captured[0]
        metadata = call.get("metadata", {})
        assert metadata.get("dry_run") is False
        assert metadata.get("transport") == "stdio"

    def test_b3_fake_path_shows_dry_run_in_safe_summary(self, monkeypatch):
        """B3: fake path 的 safe_summary 包含 dry_run 标识。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tools_listed

        emit_mcp_tools_listed("srv", tool_count=3, dry_run=True, transport="fake")

        call = captured[0]
        assert "dry_run" in str(call["safe_summary"]).lower()

    def test_b4_real_path_omits_dry_run_from_safe_summary(self, monkeypatch):
        """B4: real path (dry_run=False) 的 safe_summary 不含 dry_run。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered

        emit_mcp_server_discovered("real_srv", dry_run=False, transport="stdio")

        call = captured[0]
        assert "dry_run" not in str(call["safe_summary"]).lower()

    def test_b5_mode_field_in_evidence_metadata(self, monkeypatch):
        """B5: mode 字段在 evidence metadata 中存在且有正确值。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered, emit_mcp_tool_registered

        # registration path
        emit_mcp_server_discovered("srv", dry_run=False, transport="stdio", mode="registration")
        emit_mcp_tool_registered(
            "srv", "tool_a", dry_run=False, transport="stdio", mode="registration"
        )

        for call in captured:
            metadata = call.get("metadata", {})
            assert "mode" in metadata, (
                f"metadata must contain mode, got keys={list(metadata.keys())}"
            )
            assert metadata["mode"] == "registration", (
                f"registration path mode should be 'registration', got {metadata['mode']}"
            )

    def test_b6_mode_field_for_smoke_path(self, monkeypatch):
        """B6: smoke/health_check path 的 mode 应为 'smoke'。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered

        emit_mcp_server_discovered(
            "smoke_srv", dry_run=False, transport="health_check", mode="smoke",
        )

        call = captured[0]
        metadata = call.get("metadata", {})
        assert metadata.get("mode") == "smoke"
        assert metadata.get("transport") == "health_check"

    def test_b7_all_emit_functions_accept_dry_run_and_transport(self):
        """B7: 所有 5 个 emit 函数都接受 dry_run、transport、mode 关键字参数。"""
        import inspect

        from agent.mcp_audit import (
            emit_mcp_server_blocked,
            emit_mcp_server_discovered,
            emit_mcp_tool_blocked,
            emit_mcp_tool_registered,
            emit_mcp_tools_listed,
        )

        funcs = [
            emit_mcp_server_discovered,
            emit_mcp_server_blocked,
            emit_mcp_tools_listed,
            emit_mcp_tool_registered,
            emit_mcp_tool_blocked,
        ]
        for func in funcs:
            sig = inspect.signature(func)
            params = sig.parameters
            assert "dry_run" in params, f"{func.__name__} missing dry_run parameter"
            assert "transport" in params, f"{func.__name__} missing transport parameter"
            assert "mode" in params, f"{func.__name__} missing mode parameter"


# ═══════════════════════════════════════════════════════════════════
# C: safe_summary 不含敏感信息
# ═══════════════════════════════════════════════════════════════════


class TestMCPSafeSummary:
    """C: 验证 safe_summary 不包含 raw config/descriptor/secret。"""

    def test_c1_safe_summary_no_env_or_secret(self, monkeypatch):
        """C1: safe_summary 不包含 env / secret / API_KEY 等敏感词。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import (
            emit_mcp_server_blocked,
            emit_mcp_server_discovered,
            emit_mcp_tool_blocked,
            emit_mcp_tool_registered,
            emit_mcp_tools_listed,
        )

        emit_mcp_server_discovered("srv", dry_run=False, transport="stdio")
        emit_mcp_server_blocked("srv", reason="blocked", dry_run=False, transport="stdio")
        emit_mcp_tools_listed("srv", tool_count=1, dry_run=True, transport="fake")
        emit_mcp_tool_registered("srv", "tool_a", dry_run=False, transport="stdio")
        emit_mcp_tool_blocked("srv", "tool_b", reason="risky", dry_run=True, transport="fake")

        for call in captured:
            summary = str(call.get("safe_summary", ""))
            assert "API_KEY" not in summary
            assert "SECRET" not in summary.upper()
            # 不包含 raw config（如 command、args 等）
            assert "command" not in summary.lower()

    def test_c2_metadata_excludes_raw_config_fields(self, monkeypatch):
        """C2: metadata 不包含 raw config / raw descriptor / env / command。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_server_discovered, emit_mcp_tool_registered

        emit_mcp_server_discovered("srv", dry_run=True, transport="fake")
        emit_mcp_tool_registered("srv", "tool_a", dry_run=False, transport="stdio")

        for call in captured:
            metadata = call.get("metadata", {})
            forbidden_keys = {
                "raw_config", "raw_descriptor", "env", "command",
                "args", "secret", "api_key",
            }
            for key in forbidden_keys:
                assert key not in metadata, f"metadata must not contain '{key}'"

    def test_c3_safe_summary_is_readable(self, monkeypatch):
        """C3: safe_summary 是可读的简短摘要，不超过 200 字符。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import emit_mcp_tool_blocked

        emit_mcp_tool_blocked(
            "demo_srv", "my_tool", reason="high risk", dry_run=True, transport="fake"
        )

        call = captured[0]
        summary = str(call["safe_summary"])
        assert len(summary) <= 200
        # 包含关键信息
        assert "demo_srv" in summary or "my_tool" in summary


# ═══════════════════════════════════════════════════════════════════
# D: events.jsonl 写入验证
# ═══════════════════════════════════════════════════════════════════


class TestMCPAuditEventsJSONL:
    """D: 验证 MCP audit events 写入 per-session events.jsonl。"""

    def test_d1_events_written_to_events_jsonl(self, tmp_path):
        """D1: 真实 record_evidence → EventLogWriter → events.jsonl 落盘验证。

        不走 mock——使用 tmp_path 隔离，验证 MCP audit event 完整写入链路。
        """
        from agent.evidence_recorder import set_event_log_writer, set_session_context

        session_dir = tmp_path / "sessions" / "test-sid"
        session_dir.mkdir(parents=True, exist_ok=True)

        from agent.event_log import EventLogWriter
        writer = EventLogWriter(session_dir)

        set_session_context(
            session_id="test-sid",
            entry="plain",
            provider_type="fake",
            provider_model="fake",
        )
        set_event_log_writer(writer)

        try:
            from agent.mcp_audit import emit_mcp_server_discovered, emit_mcp_tool_registered

            emit_mcp_server_discovered(
                "jsonl_srv", dry_run=False, transport="stdio", mode="registration",
            )
            emit_mcp_tool_registered(
                "jsonl_srv", "hello_tool",
                dry_run=False, transport="stdio", mode="registration",
            )
        finally:
            set_event_log_writer(None)
            writer.close()

        events_path = session_dir / "events.jsonl"
        assert events_path.exists(), "events.jsonl should exist"

        lines = events_path.read_text().strip().split("\n")
        assert len(lines) >= 2, f"Expected >=2 events, got {len(lines)}"

        operations_seen: set[str] = set()
        for line in lines:
            event = json.loads(line)
            data = event.get("data", {})
            assert data.get("subsystem") == "mcp", (
                f"Expected subsystem=mcp, got {data.get('subsystem')}"
            )
            operations_seen.add(str(data.get("operation", "")))

            # 验证 metadata 包含必要字段
            metadata = data.get("metadata", {})
            assert "dry_run" in metadata, "metadata must contain dry_run"
            assert "transport" in metadata, "metadata must contain transport"
            assert "mode" in metadata, "metadata must contain mode"
            assert metadata.get("server_name") == "jsonl_srv"

            # 验证 safe_summary 不含敏感信息
            safe_summary = str(data.get("safe_summary", ""))
            assert "command" not in safe_summary.lower()
            assert "secret" not in safe_summary.lower()
            assert "api_key" not in safe_summary.lower()

            # metadata 不含禁字段
            forbidden_keys = {"raw_config", "raw_descriptor", "env", "command", "args", "secret"}
            for key in forbidden_keys:
                assert key not in metadata, f"metadata must not contain '{key}'"

        assert "server_discovered" in operations_seen
        assert "tool_registered" in operations_seen

    def test_d2_event_operation_distinguishes_semantics(self, monkeypatch):
        """D2: operation 字段能区分 server_discovered/tool_registered 等语义。"""
        _setup_session_context()
        captured: list[dict[str, Any]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return kwargs  # type: ignore[return-value]

        monkeypatch.setattr("agent.mcp_audit.record_evidence", _capture)
        from agent.mcp_audit import (
            emit_mcp_server_discovered,
            emit_mcp_tool_registered,
        )

        emit_mcp_server_discovered("srv", dry_run=True, transport="fake")
        emit_mcp_tool_registered("srv", "tool_a", dry_run=True, transport="fake")

        ops = {c["operation"] for c in captured}
        assert "server_discovered" in ops
        assert "tool_registered" in ops
        assert ops == {"server_discovered", "tool_registered"}


# ═══════════════════════════════════════════════════════════════════
# E: ToolRuntimeMediator 不回归
# ═══════════════════════════════════════════════════════════════════


class TestMCPToolExecutionNoRegression:
    """E: 验证 MCP tool execution 仍走普通 tool evidence，TOOL_INVOKE 仍 evidence-only。"""

    def test_e1_mcp_tool_invoke_is_still_evidence_only(self):
        """E1: TOOL_INVOKE dispatcher 路径仍为 evidence-only。"""
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.tool_registry import TOOL_REGISTRY

        tool_name = "mcp__e1_test__noop"
        TOOL_REGISTRY[tool_name] = {
            "name": tool_name,
            "func": lambda **kw: "ok",
            "capability": "mcp_tool",
            "risk_level": "high",
            "confirmation": "always",
        }
        try:
            registry = ActionHandlerRegistry()
            registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
            dispatcher = RuntimeActionDispatcher(
                registry=registry, observer=RuntimeActionModuleObserver()
            )

            result = dispatcher.route(RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="mcp_no_regression_test",
                parent_trace_id="trace:mcp-noreg",
                payload={"tool_name": tool_name, "tool_input": {}},
            ))

            payload = dict(result.payload)
            assert payload["disposition"] == "evidence_only"
            assert payload["tool_invoked"] is False
            assert payload["execution_status"] == "not_executed"
        finally:
            TOOL_REGISTRY.pop(tool_name, None)

    def test_e2_mcp_tool_execution_uses_tool_subsystem_evidence(self):
        """E2: MCP tool 执行仍走普通 tool subsystem evidence（不改 MCP audit 路径）。"""
        from agent.tool_registry import TOOL_REGISTRY, execute_tool

        tool_name = "mcp__e2_test__noop"
        TOOL_REGISTRY[tool_name] = {
            "name": tool_name,
            "func": lambda **kw: "mcp result ok",
            "capability": "mcp_tool",
            "risk_level": "high",
            "confirmation": "always",
        }
        try:
            result = execute_tool(tool_name, {})
            assert "mcp result ok" in str(result)
        finally:
            TOOL_REGISTRY.pop(tool_name, None)

    def test_e3_tool_runtime_mediator_not_changed(self):
        """E3: ToolRuntimeMediator 关键入口 mediate / mediate_pending 未变。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator
        assert hasattr(ToolRuntimeMediator, "mediate"), (
            "ToolRuntimeMediator must still have mediate"
        )
        assert hasattr(ToolRuntimeMediator, "mediate_pending"), (
            "ToolRuntimeMediator must still have mediate_pending"
        )

    def test_e4_production_code_does_not_import_run_mcp_tool_pipeline(self):
        """E4: agent/ 下生产代码不 import run_mcp_tool_pipeline。"""
        import ast

        project_root = Path(__file__).resolve().parent.parent
        agent_root = project_root / "agent"
        allowed = {"agent/runtime_integration/mcp_tool_orchestrator.py"}
        violations: dict[str, set[str]] = {}

        for py_file in agent_root.rglob("*.py"):
            rel = str(py_file.relative_to(project_root))
            if rel in allowed:
                continue
            tree = ast.parse(py_file.read_text())
            found: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "mcp_tool_orchestrator" in alias.name:
                            found.add(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if "mcp_tool_orchestrator" in (node.module or ""):
                        found.add(f"import from {node.module}")
                elif isinstance(node, ast.Name) and node.id == "run_mcp_tool_pipeline":
                    found.add("call run_mcp_tool_pipeline")
            if found:
                violations[rel] = found

        assert violations == {}, (
            f"run_mcp_tool_pipeline is harness-only: {violations}"
        )
