"""F5（P2 review finding 2026-08-16）：execution authority 必须显式投影，不得默认。

KTD13 的 explicit projection/no fallback：``ToolSpec`` / ``ToolDefinition`` /
``ExecutionIntent`` / ``ExecutingIntentRecord`` 的 ``execution_authority`` 此前靠
constructor default 静默赋 IN_PROCESS——新增工具遗漏 authority 声明仍会 Green。
Green 合同：字段无 default（遗漏即 TypeError），且 agent/ 下全部静态 ``ToolSpec``
构造都显式传 ``execution_authority=``。
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from agent.runtime.contracts import (
    ExecutingIntentRecord,
    ExecutionIntent,
    ToolDefinition,
    ToolSpec,
)

ROOT = Path(__file__).resolve().parents[2]


def test_015_execution_authority_fields_have_no_default() -> None:
    """authority 字段必须必填——遗漏在构造时即失败，不得静默 fallback IN_PROCESS。"""

    for cls in (ToolSpec, ToolDefinition, ExecutionIntent, ExecutingIntentRecord):
        fields = {field.name: field for field in dataclasses.fields(cls)}
        assert "execution_authority" in fields, cls
        field = fields["execution_authority"]
        assert field.default is dataclasses.MISSING, cls
        assert field.default_factory is dataclasses.MISSING, cls


def _base_spec_kwargs() -> dict:
    return {
        "name": "probe",
        "version": "1",
        "description": "probe",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "risk": "low",
        "side_effect": "read_only",
        "output_policy": "bounded_text",
        "approval_policy": "never",
        "safety_policy": {},
        "output_limit_chars": 100,
    }


def test_015_tool_spec_without_authority_fails_to_construct() -> None:
    with pytest.raises(TypeError):
        ToolSpec(**_base_spec_kwargs())  # type: ignore[arg-type]


def test_015_all_static_tool_specs_declare_authority_explicitly() -> None:
    """AST 扫描 agent/：每个 ``ToolSpec(...)`` 构造必须显式传 ``execution_authority=``。"""

    offenders: list[str] = []
    for path in sorted((ROOT / "agent").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = target.id if isinstance(target, ast.Name) else (
                target.attr if isinstance(target, ast.Attribute) else None
            )
            if name != "ToolSpec":
                continue
            if not any(kw.arg == "execution_authority" for kw in node.keywords):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"ToolSpec without explicit execution_authority: {offenders}"
