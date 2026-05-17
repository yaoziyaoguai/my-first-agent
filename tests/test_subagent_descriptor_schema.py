"""SubAgent Phase 1: Descriptor Schema tests.

这些测试先定义 formal SubAgent descriptor 的安全边界：
- SUBAGENT.md 只解析 frontmatter，不执行 body；
- v1 model 只能是 fake / fixture / none；
- secret-like metadata 必须 redacted；
- invalid descriptor 必须 fail closed，不能变成 registry-visible 对象。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from textwrap import dedent

import pytest

from agent.subagent_system.descriptor import load_subagent_descriptor
from agent.subagent_system.errors import SubAgentLoadError


def _write_subagent_md(root: Path, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "SUBAGENT.md"
    path.write_text(dedent(content).strip(), encoding="utf-8")
    return path


def _valid_descriptor(name: str = "code-reviewer") -> str:
    return f"""
    ---
    name: {name}
    description: Review code safely.
    role: reviewer
    model: fake
    status: active
    risk_level: low
    version: 0.1.0
    allowed_tools:
      - read_file
    allowed_skills: []
    memory_scope: read_context
    max_iterations_default: 3
    confirmation_policy: inherit_tool_policy
    supported_modes:
      - local_fake
      - local_deterministic
    tags:
      - review
    metadata:
      api_token: literal-secret-value
    ---
    # Code Reviewer

    Body is not executed in Phase 1.
    """


def test_valid_subagent_descriptor_is_frozen_and_redacted(tmp_path: Path) -> None:
    """合法 descriptor 只产生不可变 metadata，secret-like 字段被审计性脱敏。"""

    manifest_path = _write_subagent_md(tmp_path / "code-reviewer", _valid_descriptor())

    descriptor = load_subagent_descriptor(manifest_path)

    assert descriptor.name == "code-reviewer"
    assert descriptor.source_dir == manifest_path.parent
    assert descriptor.allowed_tools == ("read_file",)
    assert descriptor.supported_modes == ("local_fake", "local_deterministic")
    assert descriptor.is_visible() is True
    assert descriptor.metadata["api_token"] == "<redacted>"
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("name", "MISSING_NAME"),
        ("description", "MISSING_DESCRIPTION"),
        ("role", "MISSING_ROLE"),
        ("status", "MISSING_STATUS"),
    ],
)
def test_missing_required_fields_fail_closed(
    tmp_path: Path,
    field: str,
    expected_code: str,
) -> None:
    """缺必填字段必须抛 typed error，避免部分有效 descriptor 泄漏到 registry。"""

    frontmatter = {
        "name": "code-reviewer",
        "description": "Review code safely.",
        "role": "reviewer",
        "model": "fake",
        "status": "active",
    }
    frontmatter.pop(field)
    lines = ["---", *(f"{key}: {value}" for key, value in frontmatter.items()), "---", "body"]
    manifest_path = _write_subagent_md(tmp_path / "code-reviewer", "\n".join(lines))

    with pytest.raises(SubAgentLoadError) as exc_info:
        load_subagent_descriptor(manifest_path)

    assert exc_info.value.code == expected_code
    assert exc_info.value.recoverable is False


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ("name: Bad Name", "INVALID_NAME"),
        ("status: hidden", "INVALID_STATUS"),
        ("model: claude-sonnet", "INVALID_MODEL"),
        ("risk_level: critical", "INVALID_RISK_LEVEL"),
        ("memory_scope: write", "INVALID_MEMORY_SCOPE"),
        ("max_iterations_default: 0", "INVALID_MAX_ITERATIONS"),
        ("supported_modes:\n  - real_llm_readonly", "INVALID_SUPPORTED_MODE"),
    ],
)
def test_invalid_descriptor_values_fail_closed(
    tmp_path: Path,
    override: str,
    expected_code: str,
) -> None:
    """Phase 1 不接受真实 LLM / unsupported modes / unsafe metadata。"""

    base = _valid_descriptor()
    for key in ("name", "status", "model", "risk_level", "memory_scope", "max_iterations_default", "supported_modes"):
        if override.startswith(key):
            lines = base.splitlines()
            output: list[str] = []
            skip_nested = False
            for line in lines:
                stripped = line.strip()
                if skip_nested and line.startswith("      - "):
                    continue
                skip_nested = False
                if stripped.startswith(f"{key}:"):
                    output.extend(f"    {part}" for part in override.splitlines())
                    skip_nested = key == "supported_modes"
                else:
                    output.append(line)
            base = "\n".join(output)
            break
    manifest_path = _write_subagent_md(tmp_path / "code-reviewer", base)

    with pytest.raises(SubAgentLoadError) as exc_info:
        load_subagent_descriptor(manifest_path)

    assert exc_info.value.code == expected_code
