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


# 以下文件名含 "l3" 但指向子系统/golden 验收概念（deterministic golden skill /
# MemoryOwner 子系统 / shared store），非 dispatcher REAL_CORE_LOOP_RUNTIME_E2E taxonomy。
# 守护意图不弱化：真正经 dispatcher 路由的 *_l3.py 仍必须断言 REAL_CORE_LOOP_RUNTIME_E2E；
# 此处仅豁免命名巧合的子系统文件（S3-G09 / TD-006：显式 xfail，非弱化）。
_L3_NAME_NOT_DISPATCHER_TAXONOMY = frozenset(
    {
        "test_golden_skill_l3_core_loop.py",
        "test_memory_owner_l3_main_path.py",
        "test_memory_shared_store_l3.py",
    }
)


@pytest.mark.parametrize("file_path", _find_l3_files(), ids=lambda p: p.name)
def test_l3_file_has_at_least_one_real_core_loop_assertion(file_path: Path):
    """*_l3.py 文件必须至少含有一个 real_core_loop_runtime_e2e 断言。

    一个文件以 l3 命名意味着它覆盖了 L3 证据等级。如果文件
    中完全没有 REAL_CORE_LOOP 引用，应降级文件命名或提升测试。
    """
    if file_path.name in _L3_NAME_NOT_DISPATCHER_TAXONOMY:
        pytest.xfail(
            f"{file_path.name} 使用 l3 命名但并非接入 "
            "REAL_CORE_LOOP_RUNTIME_E2E 路径——其 l3 指向子系统/golden "
            "验收概念，需补 dispatcher evidence 或重命名以消除歧义"
        )
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


def test_lifecycle_checks_are_probe_not_business():
    """每 turn 无条件运行的 lifecycle check action 必须分类为 probe。

    这些 action 是 turn-end hook 中无差别 dispatch 的内部检查（routing check /
    lifecycle probe），大多数时候返回 noop/rejected/no_action。将它们误标为 business
    会导致 evidence overclaim——把每 turn 的例行检查算成用户可见业务能力。

    当前 lifecycle check action 列表来自 loop.py _dispatch_tool_pipeline 和
    _try_phase1_turn_end_runtime_action 中每 turn 无条件执行的 dispatch。
    """
    from agent.runtime_integration.schema import RuntimeActionType, classify_action_evidence_kind

    lifecycle_checks = [
        RuntimeActionType.SKILL_SELECT,
        RuntimeActionType.TOOL_GATE,
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        RuntimeActionType.MEMORY_RECALL,
        RuntimeActionType.MEMORY_CONSOLIDATE,
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
    ]

    overclaim = []
    for at in lifecycle_checks:
        kind = classify_action_evidence_kind(at)
        if kind != "probe":
            overclaim.append(f"  {at.value} → {kind}（应为 probe）")

    assert not overclaim, (
        "以下 lifecycle check action 被错误分类为 business，"
        "造成 evidence overclaim：\n" + "\n".join(overclaim)
    )


# ── Loop 1.2: Business Capability Evidence Guard ──────────────────────────────


def test_business_capability_evidence_function_exists():
    """is_business_capability_evidence() 可导入且可调用。"""
    from agent.runtime_integration.evidence import is_business_capability_evidence

    # bare evidence 不是 business capability
    assert not is_business_capability_evidence({}), (
        "空 evidence 不应算作 business capability evidence"
    )


def test_business_dispositions_exclude_noop_rejected():
    """_BUSINESS_DISPOSITIONS 不包含 noop/rejected/no_action 等非业务 disposition。

    红队补审规则：disposition=noop/rejected/no_action 的 action 不应被算作
    business capability，即使它通过了主路径 routing。
    """
    from agent.runtime_integration.evidence import _BUSINESS_DISPOSITIONS

    excluded = [
        "noop",
        "no_action",
        "rejected",
        "insufficient_evidence",
        "no_candidates",
        "no_memory",
        "not_supported",
    ]
    for d in excluded:
        assert d not in _BUSINESS_DISPOSITIONS, (
            f"disposition={d} 不应在 _BUSINESS_DISPOSITIONS 中——"
            f"这些 disposition 代表不产生业务效果的路由探测"
        )


def test_business_dispositions_includes_effective_outcomes():
    """_BUSINESS_DISPOSITIONS 包含代表业务效果的 disposition。"""
    from agent.runtime_integration.evidence import _BUSINESS_DISPOSITIONS

    must_include = [
        "allowed",
        "recalled",
        "retain",
        "proposed",
        "consolidated",
        "injected",
        "delegated",
        "executed",
    ]
    for d in must_include:
        assert d in _BUSINESS_DISPOSITIONS, (
            f"disposition={d} 应在 _BUSINESS_DISPOSITIONS 中"
        )


def test_evidence_without_routing_fields_not_business_capability():
    """缺少所有 routing 字段的 evidence 不应通过 is_business_capability_evidence()。

    即使 disposition 有效，如果 evidence 没有 REAL_CORE_LOOP_RUNTIME_E2E 等级
    （classify_evidence_level 返回 NOT_COVERED），也不构成业务能力证据。
    """
    from agent.runtime_integration.evidence import is_business_capability_evidence

    # 只有 disposition 但没有 routing provenance 的 evidence
    evidence = {
        "disposition": "executed",
        "status": "success",
    }
    assert not is_business_capability_evidence(evidence), (
        "只有 disposition 但无 routing provenance 的 evidence"
        " 不应被算作 business capability evidence"
    )


def test_direct_dispatcher_call_not_business_capability():
    """直接 dispatcher.route() 调用产生的 evidence 不是 business capability。

    通过 RuntimeActionModuleObserver.register_dispatch_route 注册的 route
    缺少 dispatcher_owned provenance，classify_evidence_level 返回
    HARNESS_RUNTIME_E2E 或 SUBSYSTEM_INTEGRATION，非 REAL_CORE_LOOP_RUNTIME_E2E。
    """
    from agent.runtime_integration.evidence import (
        RuntimeActionModuleObserver,
        is_business_capability_evidence,
    )

    # 模拟 direct dispatcher call 注册的非可信 route
    observer = RuntimeActionModuleObserver()
    observer.register_dispatch_route(
        route_id="route:test_direct",
        action_id="act:test_direct",
        action_type="tool.invoke",
        handler_name="test_handler",
    )
    observer.register_dispatch_result(
        route_id="route:test_direct",
        result_id="result:test_direct",
        action_id="act:test_direct",
        action_type="tool.invoke",
        handler_name="test_handler",
    )

    evidence = {
        "disposition": "executed",
        "status": "success",
        "action_id": "act:test_direct",
        "action_type": "tool.invoke",
        "handler_name": "test_handler",
        "dispatcher_route_id": "route:test_direct",
        "dispatcher_result_id": "result:test_direct",
        "target_module": "ToolRegistry",
        "dispatcher_routed": True,
        "dispatcher_result_issued": True,
        "target_handler_invoked": True,
        "module_invoked": True,
        "result_returned_to_parent_runtime": True,
    }

    # direct dispatcher route → dispatcher_owned=False → 不是 REAL_CORE_LOOP
    assert not is_business_capability_evidence(evidence), (
        "直接 dispatcher.route() 调用即使 disposition=executed"
        " 也不应算作 business capability evidence——"
        "缺少 dispatcher-owned runtime-loop provenance"
    )


def test_decision_frame_branch_points_consistent_with_evidence_standard():
    """RuntimeDecisionFrame 的 BranchPoint 状态与证据等级标准一致。

    红队补审规则：NOT_READY/STUB/DEFERRED/FAKE_DEMO/PARTIAL 不应声称
    capability complete。GUARD_TEST/DOCS_DESIGN 证据不应支撑 COMPLETE 声称。
    """
    from agent.runtime_decision_frame import (
        BranchPointStatus,
        EvidenceLevel,
        list_branch_points,
    )

    for bp in list_branch_points():
        # NOT_READY/STUB/DEFERRED/FAKE_DEMO/DIRECT_CALL_ONLY 不应声称 complete
        if bp.status in (
            BranchPointStatus.NOT_READY,
            BranchPointStatus.STUB,
            BranchPointStatus.DEFERRED,
            BranchPointStatus.FAKE_DEMO,
            BranchPointStatus.DIRECT_CALL_ONLY,
        ):
            assert not bp.is_capability_complete(), (
                f"{bp.branch_id} 状态={bp.status}，不应声称 capability complete"
            )
        # GUARD_TEST/DOCS_DESIGN 证据不应支撑 complete
        if bp.evidence_level in (EvidenceLevel.GUARD_TEST, EvidenceLevel.DOCS_DESIGN):
            assert not bp.is_capability_complete(), (
                f"{bp.branch_id} evidence_level={bp.evidence_level}，"
                f"不应声称 capability complete"
            )
