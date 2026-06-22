"""G-041: Per-tool input/output guardrail primitive.

学习型说明：
这是 tool platform 的 **guardrail 扩展点**——一个统一的 pre/post 检查接口，
让 operator 或 policy 可以在不修改每个 tool 的前提下，添加跨 tool 的安全检查：

- check_input(tool_name, tool_input): 执行前检查（例如检测 tool 参数中的 secret）
- check_output(tool_name, result): 执行后检查（例如 scrub 工具输出中的 secret）

默认 guardrail：
- InputGuardrail: 检测 tool 参数中的 sk- / Bearer / token 模式 → block
- OutputGuardrail: scrub 工具结果中的 sk- / Bearer 模式 → safe result

这些是 platform-level guardrail，与 per-tool confirmation/governance 互补：
confirmation 是「是否允许执行」，guardrail 是「输入/输出是否安全」。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Secret patterns for guardrail detection (reused from evidence_redaction concept).
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_-]{16,}"),
    re.compile(r"x-api-key:\s*\S{12,}", re.IGNORECASE),
]


@dataclass(frozen=True)
class GuardrailResult:
    """Guardrail check result."""

    ok: bool
    reason: str = ""


# Type aliases for guardrail callables.
InputGuardrailFn = Callable[[str, dict[str, Any]], GuardrailResult]
OutputGuardrailFn = Callable[[str, str], str]


def _detect_secrets_in_value(value: Any) -> str | None:
    """Return the first secret pattern found in a value, or None."""
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            match = pattern.search(value)
            if match:
                return match.group(0)[:8] + "..."
    elif isinstance(value, dict):
        for v in value.values():
            found = _detect_secrets_in_value(v)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _detect_secrets_in_value(item)
            if found:
                return found
    return None


def default_input_guardrail(tool_name: str, tool_input: dict[str, Any]) -> GuardrailResult:
    """Default input guardrail: block tool calls whose args contain secret patterns."""
    found = _detect_secrets_in_value(tool_input)
    if found:
        return GuardrailResult(
            ok=False,
            reason=f"blocked: secret-like pattern detected in tool input ({found})",
        )
    return GuardrailResult(ok=True)


def default_output_guardrail(tool_name: str, result: str) -> str:
    """Default output guardrail: scrub secret patterns from tool results."""
    scrubbed = result
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    return scrubbed


class ToolGuardrailRegistry:
    """Extensible registry of per-tool input/output guardrails.

    The mediator/tool executor can call check_input/check_output before/after
    each tool execution. Custom guardrails can be registered per tool or globally.
    """

    def __init__(self) -> None:
        self._global_input: list[InputGuardrailFn] = [default_input_guardrail]
        self._global_output: list[OutputGuardrailFn] = [default_output_guardrail]
        self._per_tool_input: dict[str, list[InputGuardrailFn]] = {}
        self._per_tool_output: dict[str, list[OutputGuardrailFn]] = {}

    def register_input_guardrail(
        self, fn: InputGuardrailFn, *, tool_name: str | None = None
    ) -> None:
        """Register an input guardrail (global or per-tool)."""
        if tool_name:
            self._per_tool_input.setdefault(tool_name, []).append(fn)
        else:
            self._global_input.append(fn)

    def register_output_guardrail(
        self, fn: OutputGuardrailFn, *, tool_name: str | None = None
    ) -> None:
        """Register an output guardrail (global or per-tool)."""
        if tool_name:
            self._per_tool_output.setdefault(tool_name, []).append(fn)
        else:
            self._global_output.append(fn)

    def check_input(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> GuardrailResult:
        """Run all applicable input guardrails. First failure wins."""
        for fn in self._global_input:
            result = fn(tool_name, tool_input)
            if not result.ok:
                return result
        for fn in self._per_tool_input.get(tool_name, ()):
            result = fn(tool_name, tool_input)
            if not result.ok:
                return result
        return GuardrailResult(ok=True)

    def check_output(self, tool_name: str, result: str) -> str:
        """Run all applicable output guardrails. Each transforms the result."""
        scrubbed = result
        for fn in self._global_output:
            scrubbed = fn(tool_name, scrubbed)
        for fn in self._per_tool_output.get(tool_name, ()):
            scrubbed = fn(tool_name, scrubbed)
        return scrubbed


# Module-level singleton for the default guardrail set.
_registry = ToolGuardrailRegistry()


def get_guardrail_registry() -> ToolGuardrailRegistry:
    """Get the module-level guardrail registry singleton."""
    return _registry
