"""W2-T1 / W2-T2: SPA-1 — safe metadata masking ownership lock.

SPA-1 决策（Option B 已批准）：
- `display_events.py` 是 canonical secret-masking owner
  （定义 `_SECRET_MASK_PATTERNS` + `mask_user_visible_secrets`）。
- `safe_metadata.py` 是 projection wrapper / truncation / boundary-local
  extra redaction；它委托 canonical masker，**不重新定义**同一组 canonical 正则。
- `_EXTRA_REDACT_PATTERNS` 保留在 projector，定位为 evidence_persistence 边界
  专用的额外脱敏层（boundary-local extra redaction），不是第二个 canonical owner。

这些测试锁定 ownership contract，而不是 masking 行为本身：
masking 行为由 `test_safe_metadata_projector.py` + `test_safe_metadata_leak_gate.py`
已充分覆盖。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

# ── 源码路径（repo-relative）──────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent
_DISPLAY_EVENTS_PY = _REPO_ROOT / "agent" / "display_events.py"
_SAFE_METADATA_PY = _REPO_ROOT / "agent" / "runtime_integration" / "safe_metadata.py"


# ══════════════════════════════════════════════════════════════════════════════
# W2-T1: _SECRET_MASK_PATTERNS 只能在 display_events 中定义
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T1SingleOwner:
    """`_SECRET_MASK_PATTERNS` 必须只由 `display_events` 定义，projector 不重复编译
    同组 canonical 正则。"""

    def test_display_events_defines_secret_mask_patterns(self) -> None:
        """W2-T1a: display_events.py 必须定义 `_SECRET_MASK_PATTERNS`。"""
        source = _DISPLAY_EVENTS_PY.read_text(encoding="utf-8")
        assert "_SECRET_MASK_PATTERNS" in source, (
            "display_events.py 必须定义 _SECRET_MASK_PATTERNS（canonical owner）"
        )

    def test_safe_metadata_does_not_define_secret_mask_patterns(self) -> None:
        """W2-T1b: safe_metadata.py 不得定义 `_SECRET_MASK_PATTERNS`。"""
        source = _SAFE_METADATA_PY.read_text(encoding="utf-8")
        assert "_SECRET_MASK_PATTERNS" not in source, (
            "safe_metadata.py 不得定义 _SECRET_MASK_PATTERNS "
            "（应从 display_events 委托，不重复编译 canonical 正则）"
        )

    def test_projector_does_not_duplicate_canonical_sk_pattern(self) -> None:
        """W2-T1c: projector 不复制 canonical sk-ant-* / sk-* 正则（第一组关键 pattern）。

        display_events 的前两条 pattern（sk-ant / sk-) 是识别 OpenAI/Anthropic key 的
        canonical 来源。projector 不应重复编译同一正则，否则两套脱敏逻辑会产生漂移。
        """
        source = _SAFE_METADATA_PY.read_text(encoding="utf-8")
        # canonical patterns in display_events: r"sk-ant-[...]" and r"sk-[...]{12,}"
        # projector must NOT re-define these patterns
        sk_ant_pos = source.find("sk-ant-")
        if sk_ant_pos >= 0:
            line_before = source[:sk_ant_pos].split("\n")[-1]
            assert "compile" not in line_before, (
                "safe_metadata.py 不得重新 compile sk-ant- 正则"
                "（canonical owner 是 display_events）"
            )

    def test_canonical_patterns_defined_as_module_level_tuple(self) -> None:
        """W2-T1d: `_SECRET_MASK_PATTERNS` 在 display_events 以 module-level 定义。

        验证 ownership 是结构化的（module-level const），而非散落函数内部。
        接受 ast.Assign（无注解）和 ast.AnnAssign（带类型注解，如 tuple[...]）两种形式。
        """
        tree = ast.parse(_DISPLAY_EVENTS_PY.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            # 无类型注解赋值：_SECRET_MASK_PATTERNS = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_SECRET_MASK_PATTERNS":
                        found = True
            # 带类型注解赋值：_SECRET_MASK_PATTERNS: tuple[...] = ...
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_SECRET_MASK_PATTERNS"
            ):
                found = True
        assert found, (
            "display_events.py 必须以 module-level assignment 定义 _SECRET_MASK_PATTERNS"
        )

    def test_safe_metadata_does_not_recompile_sk_pattern_via_ast(self) -> None:
        """W2-T1e: AST 验证 safe_metadata.py 没有 compile(r'sk-') 调用（canonical pattern 复制）。

        使用 AST 而非 grep，避免注释行误报。
        """
        tree = ast.parse(_SAFE_METADATA_PY.read_text(encoding="utf-8"))
        # 寻找 re.compile('sk-...' ) 或 re.compile(r"sk-...") 形式
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # re.compile(...)
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "compile"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "re"
                    and node.args
                ):
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(
                        first_arg.value, str
                    ):
                        pattern_str = first_arg.value
                        assert not pattern_str.startswith("sk-ant"), (
                            f"safe_metadata.py 不得重新 compile sk-ant 正则: {pattern_str!r}"
                        )
                        # "sk-" with length qualifier is canonical
                        if pattern_str.startswith("sk-") and (
                            "{12," in pattern_str or "+" in pattern_str
                        ):
                            pytest.fail(
                                "safe_metadata.py 不得重新 compile sk- 长度限定正则: "
                                f"{pattern_str!r}"
                            )


# ══════════════════════════════════════════════════════════════════════════════
# W2-T2: projector 委托 mask_user_visible_secrets（projection-only）
# ══════════════════════════════════════════════════════════════════════════════


class TestW2T2ProjectionOnlyDelegation:
    """projector 必须委托 `mask_user_visible_secrets`；`_EXTRA_REDACT_PATTERNS`
    是 boundary-local extra redaction，有文档，不是第二个 canonical owner。"""

    def test_projector_imports_mask_user_visible_secrets(self) -> None:
        """W2-T2a: safe_metadata.py 必须从 display_events import mask_user_visible_secrets。"""
        source = _SAFE_METADATA_PY.read_text(encoding="utf-8")
        assert "from agent.display_events import mask_user_visible_secrets" in source, (
            "safe_metadata.py 必须 import mask_user_visible_secrets（委托 canonical masker）"
        )

    def test_projector_calls_mask_user_visible_secrets(self) -> None:
        """W2-T2b: projector 函数体必须调用 mask_user_visible_secrets。"""
        import importlib

        sm = importlib.import_module("agent.runtime_integration.safe_metadata")
        src_main = inspect.getsource(sm.project_safe_metadata_text)
        src_marker = inspect.getsource(sm.project_safe_metadata_text_with_marker)
        delegated = (
            "mask_user_visible_secrets" in src_main
            or "mask_user_visible_secrets" in src_marker
        )
        assert delegated, (
            "projector 函数体必须调用 mask_user_visible_secrets（委托，而非内联复制正则）"
        )

    def test_extra_redact_patterns_is_boundary_local(self) -> None:
        """W2-T2c: `_EXTRA_REDACT_PATTERNS` 只在 safe_metadata.py 内定义，
        不导出到 display_events（boundary-local，非 canonical owner）。"""
        de_source = _DISPLAY_EVENTS_PY.read_text(encoding="utf-8")
        assert "_EXTRA_REDACT_PATTERNS" not in de_source, (
            "_EXTRA_REDACT_PATTERNS 不应出现在 display_events.py "
            "（它是 projector 级 boundary-local extra redaction）"
        )

    def test_extra_redact_patterns_has_docstring_rationale(self) -> None:
        """W2-T2d: `_EXTRA_REDACT_PATTERNS` 附近必须有 docstring/注释说明 boundary-local 用途。

        防止未来维护者误认为它是 canonical masking 的备份。
        """
        source = _SAFE_METADATA_PY.read_text(encoding="utf-8")
        # 找到 _EXTRA_REDACT_PATTERNS 前后 5 行，检查是否包含 boundary 相关说明
        lines = source.splitlines()
        pattern_line = next(
            (i for i, ln in enumerate(lines) if "_EXTRA_REDACT_PATTERNS" in ln and "=" in ln),
            None,
        )
        assert pattern_line is not None, "_EXTRA_REDACT_PATTERNS 未找到定义行"
        context = "\n".join(lines[max(0, pattern_line - 5) : pattern_line + 3])
        has_rationale = any(
            kw in context
            for kw in ("boundary", "trust boundary", "projector-level", "display_events")
        )
        assert has_rationale, (
            f"_EXTRA_REDACT_PATTERNS 附近缺少 boundary-local 用途说明。\n"
            f"上下文:\n{context}"
        )

    def test_projector_is_thin_wrapper_not_reimplementation(self) -> None:
        """W2-T2e: safe_metadata.py module docstring 必须声明 thin wrapper 性质。

        这是 Option B 的架构语义：projector 不是 masking 的第二个实现。
        """
        source = _SAFE_METADATA_PY.read_text(encoding="utf-8")
        # docstring 在文件顶部，检查关键词
        assert "thin wrapper" in source, (
            "safe_metadata.py 必须在 module docstring 中声明 'thin wrapper' "
            "以区分 projector 与 canonical masker owner"
        )

    def test_project_safe_metadata_text_delegates_to_canonical(self) -> None:
        """W2-T2f: 端到端验证 projector 最终调用 canonical masker（行为等价）。

        用一个 canonical sk-ant- 模式验证 projector 脱敏结果等于 mask_user_visible_secrets。
        """
        from agent.display_events import mask_user_visible_secrets
        from agent.runtime_integration.safe_metadata import project_safe_metadata_text

        secret = "sk-ant-api03-testtoken12345678"
        projected = project_safe_metadata_text(secret)
        canonical = mask_user_visible_secrets(secret)
        assert projected == canonical, (
            f"projector 结果必须等于 canonical masker 结果（无 max_length 时）:\n"
            f"projected={projected!r}\ncanonical={canonical!r}"
        )
        assert "sk-ant-api03" not in projected, "canonical sk-ant 不应通过 projector 泄漏"
