"""证据等级分类守护测试 (Loop 7)。

验证测试代码中对 evidence_level 的断言一致性：
- real_core_loop_runtime_e2e 只能由 route_from_runtime_loop() 路径产生
- harness_runtime_e2e 只能由 dispatcher.route() 直接调用产生
- subsystem_integration 不经过 dispatcher

中文学习说明：
  这些 guard tests 防止测试代码在证据等级上 overclaim——例如把
  direct dispatcher.route() 调用的结果标记为 real_core_loop_runtime_e2e。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
L3_FILE_PATTERN = "*l3*"


def _find_l3_files() -> list[Path]:
    """返回 tests/ 下所有名字包含 l3 的 .py 文件。"""
    matches = []
    for dirpath, _dirnames, filenames in os.walk(TESTS_DIR):
        for fn in filenames:
            if "l3" in fn.lower() and fn.endswith(".py") and not fn.startswith("test_"):
                # skip: files without test_ prefix that aren't test files
                continue
            if "l3" in fn.lower() and fn.endswith(".py"):
                matches.append(Path(dirpath) / fn)
    return sorted(matches)


def _extract_test_methods(filepath: Path) -> list[dict]:
    """用 AST 提取文件中所有 test_* 方法，标注正向 L3 断言和直接 dispatcher.route() 调用。"""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                continue
            source_text = ast.unparse(node) if hasattr(ast, "unparse") else ""
            results.append({
                "name": node.name,
                "source": source_text,
                "lineno": node.lineno,
                "has_positive_l3": _has_positive_l3_assertion(source_text),
                "has_direct_dispatcher_call": _has_direct_dispatcher_call(node),
            })
    return results


def _has_positive_l3_assertion(source: str) -> bool:
    """检测源码中是否有对 REAL_CORE_LOOP_RUNTIME_E2E 的正向断言（== 而非 !=）。

    只用逐行字符串扫描——测试中断言模式固定，无需完整 AST 比较分析。
    """
    for line in source.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "REAL_CORE_LOOP_RUNTIME_E2E" not in stripped:
            continue
        if stripped.startswith("from ") or stripped.startswith("import "):
            continue
        if "!= REAL_CORE_LOOP_RUNTIME_E2E" in stripped:
            continue
        if "is not RealCoreLoopRuntimeE2E" in stripped:
            continue
        return True
    return False


def _has_direct_dispatcher_call(func_node: ast.AST) -> bool:
    """检测方法体中是否直接调用了 dispatcher.route()（AST 级别，不匹配 docstring）。"""
    for sub in ast.walk(func_node):
        if not isinstance(sub, ast.Call):
            continue
        if not isinstance(sub.func, ast.Attribute) or sub.func.attr != "route":
            continue
        # 匹配 dispatcher.route() / spy.route() 等
        if (isinstance(sub.func.value, ast.Name)
                and "dispatcher" in sub.func.value.id.lower()):
            return True
        # 匹配 spy_dispatcher.route() 等链式调用
        if (isinstance(sub.func.value, ast.Attribute)
                and "dispatcher" in ast.unparse(sub.func.value).lower()):
            return True
    return False


@pytest.mark.parametrize("file_path", _find_l3_files(), ids=lambda p: p.name)
def test_l3_file_has_at_least_one_real_core_loop_assertion(file_path: Path):
    """*_l3.py 文件必须至少含有一个 real_core_loop_runtime_e2e 断言。

    一个文件以 l3 命名意味着它覆盖了 L3 证据等级。如果文件
    中完全没有 REAL_CORE_LOOP 引用，应降级文件命名或提升测试。
    """
    content = file_path.read_text(encoding="utf-8")
    has_real = "REAL_CORE_LOOP_RUNTIME_E2E" in content or "real_core_loop_runtime_e2e" in content
    has_route_from_rl = "route_from_runtime_loop" in content

    assert has_real, (
        f"{file_path.name} 以 l3 命名但没有任何 REAL_CORE_LOOP_RUNTIME_E2E 引用。"
        f" 如果此文件只覆盖 L2，应从文件名中移除 'l3'。"
    )
    assert has_route_from_rl, (
        f"{file_path.name} 以 l3 命名但没有 route_from_runtime_loop 引用。"
        f" real_core_loop_runtime_e2e 要求通过 route_from_runtime_loop() 路径。"
    )


def test_no_l3_assertion_via_direct_dispatcher_route():
    """任何测试方法中，直接 dispatcher.route() 调用不应同时正向断言 real_core_loop_runtime_e2e。

    使用 AST 静态检查：如果 test_* 方法中正向断言（==）了
    REAL_CORE_LOOP_RUNTIME_E2E，则方法体中不应直接调用 dispatcher.route()。
    否定断言（!=）和仅 docstring 中提及的不算。
    """
    suspicious: list[tuple[str, str, int]] = []
    guard_file = Path(__file__).resolve()

    for file_path in sorted(TESTS_DIR.rglob("test_*.py")):
        if "__pycache__" in str(file_path):
            continue
        if file_path.resolve() == guard_file:
            continue
        methods = _extract_test_methods(file_path)
        for m in methods:
            if m["has_positive_l3"] and m["has_direct_dispatcher_call"]:
                suspicious.append((str(file_path), m["name"], m["lineno"]))

    if suspicious:
        msg_lines = [
            (
                "以下 test 方法同时包含 REAL_CORE_LOOP_RUNTIME_E2E 断言"
                " 和 dispatcher.route() 直接调用："
            ),
            "",
        ]
        for fpath, mname, lineno in suspicious:
            msg_lines.append(f"  {fpath}::{mname} (line {lineno})")
        msg_lines.extend([
            "",
            "dispatcher.route() 直接调用只能产生 harness_runtime_e2e。",
            "如果此方法测试的是 direct-dispatcher 路径，应改为断言 HARNESS_RUNTIME_E2E。",
            "如果此方法测试的是 route_from_runtime_loop 路径但误调用了 dispatcher.route()，",
            "应改为使用 SpyDispatcher 的 route_from_runtime_loop()。",
        ])
        pytest.fail("\n".join(msg_lines))
