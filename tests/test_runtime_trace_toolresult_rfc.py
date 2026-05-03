"""RFC-gated Runtime Trace + ToolResult first slice tests.

这些测试打开下一阶段 gate，但只做 non-invasive first slice：RFC 文档 +
ToolResult 到 TraceEvent 的纯投影 adapter。它不调用 runtime、不执行工具、不写
checkpoint、不读取 agent_log/sessions/runs，也不迁移 tool_executor。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RFC_PATH = PROJECT_ROOT / "docs" / "rfcs" / "0001-runtime-trace-toolresult-boundary.md"
ADAPTER_PATH = PROJECT_ROOT / "agent" / "runtime_trace_projection.py"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 守住 RFC first slice 的依赖方向。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def test_runtime_trace_toolresult_rfc_exists_and_is_draft() -> None:
    """RFC gate 必须先落文档，说明为什么 first slice 不越界。"""

    text = RFC_PATH.read_text(encoding="utf-8")

    required = (
        "RFC 0001: Runtime Trace + ToolResult Boundary",
        "Status: Draft",
        "Context",
        "Problem",
        "Goals",
        "Non-goals",
        "Current behavior",
        "Proposed design",
        "Architecture boundaries",
        "Safety boundaries",
        "First safe slice",
        "Alternatives considered",
        "Why rejected",
        "Test strategy",
        "Migration plan",
        "Rollback plan",
        "Risks",
        "Open questions",
        "Required human authorization",
        "Future gates",
        "no broad runtime rewrite",
        "no broad tool_executor rewrite",
    )
    for phrase in required:
        assert phrase in text


def test_tool_result_trace_projection_builds_redacted_trace_event() -> None:
    """first slice 只把 legacy ToolResult 投影成 TraceEvent，不改 executor 行为。"""

    from agent.runtime_trace_projection import build_tool_result_trace_event

    event = build_tool_result_trace_event(
        run_id="run-test",
        trace_id="trace-test",
        span_id="span-tool-result",
        parent_span_id="span-tool-call",
        tool_name="read_file",
        tool_result="错误：api_key=sk-test-secret " + ("x" * 600),
        tool_use_id="toolu-test",
        step_id="step-1",
    )
    payload = event.to_json_dict()
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["span_type"] == "tool_call"
    assert payload["name"] == "tool_result:read_file"
    assert payload["status"] == "failed"
    assert payload["step_id"] == "step-1"
    assert payload["metadata"]["tool_result_status"] == "failed"
    assert payload["metadata"]["display_event_type"] == "tool.failed"
    assert payload["metadata"]["tool_use_id"] == "toolu-test"
    assert payload["metadata"]["preview_truncated"] is True
    assert "sk-test-secret" not in encoded
    assert "[REDACTED]" in encoded


def test_tool_result_trace_projection_maps_rejection_to_skipped_status() -> None:
    """rejected_by_check 不是 runtime failure；trace 中应表达为 skipped。"""

    from agent.runtime_trace_projection import build_tool_result_trace_event

    event = build_tool_result_trace_event(
        run_id="run-test",
        trace_id="trace-test",
        span_id="span-tool-result",
        parent_span_id=None,
        tool_name="shell",
        tool_result="拒绝执行：unsafe shell",
    )

    assert event.status == "skipped"
    assert event.metadata["tool_result_status"] == "rejected_by_check"
    assert event.metadata["error_type"] == "tool_safety_rejected"


def test_runtime_trace_projection_does_not_import_runtime_executor_or_registry() -> None:
    """adapter 是纯投影 seam，不能反向依赖 runtime/tool executor。"""

    imports = _agent_imports(ADAPTER_PATH)

    assert imports == {"agent.local_trace", "agent.tool_result_contract"}
    assert {
        "agent.core",
        "agent.checkpoint",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.mcp",
        "agent.memory_store",
    }.isdisjoint(imports)


def test_rfc_execution_evidence_is_linked_from_final_docs() -> None:
    """RFC gate 完成后，final evidence 要能找到 RFC 和 first slice。"""

    final = (PROJECT_ROOT / "docs" / "FINAL_ROADMAP_COMPLETION_EVIDENCE.md").read_text(
        encoding="utf-8"
    )
    design = (
        PROJECT_ROOT / "docs" / "RUNTIME_TRACE_TOOLRESULT_SLICE_DESIGN.md"
    ).read_text(encoding="utf-8")
    closure = (
        PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")

    for text in (final, design, closure):
        assert "docs/rfcs/0001-runtime-trace-toolresult-boundary.md" in text
        assert "agent.runtime_trace_projection" in text
