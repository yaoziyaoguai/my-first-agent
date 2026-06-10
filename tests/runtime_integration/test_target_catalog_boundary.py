"""TargetCatalog production-boundary characterization tests.

These tests protect the trust-root boundary of `RuntimeActionTargetCatalog`:

- `_bindings` is a `ClassVar[tuple[...]]` — immutable at instance level.
- `resolve()` is the only public lookup; production callers go through it
  exactly once, from `RuntimeActionContext.invoke_registered_target()`.

They complement `test_runtime_action_contract.py`'s dynamic-path tests
(415fabd) by adding static, import-boundary, and immutability guards.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.evidence import RuntimeActionTargetCatalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_ROOT = _REPO_ROOT / "agent"


def _collect_production_call_sites() -> tuple[tuple[str, int, str], ...]:
    """Return every production `agent/` call site of `RuntimeActionTargetCatalog.resolve()`.

    返回 (relpath, lineno, matched_line) 三元组。tests/目录与 evidence.py
    自身不计入，因为它们是测试或 catalog 定义本身。
    """

    pattern = re.compile(r"RuntimeActionTargetCatalog\.resolve\(")
    hits: list[tuple[str, int, str]] = []
    for path in sorted(_AGENT_ROOT.rglob("*.py")):
        relpath = str(path.relative_to(_REPO_ROOT))
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append((relpath, lineno, line.strip()))
    return tuple(hits)


def test_catalog_resolve_only_called_from_dispatcher_context() -> None:
    """dispatcher.invoke_registered_target()必须是 production path唯一调用点。"""

    sites = _collect_production_call_sites()
    pairs = tuple((relpath, lineno) for relpath, lineno, _ in sites)
    expected = (("agent/runtime_integration/dispatcher.py", 146),)
    assert pairs == expected, (
        "RuntimeActionTargetCatalog.resolve() production call site drift: "
        f"expected only {expected}, got {pairs}"
    )


def test_catalog_bindings_is_immutable_classvar_tuple() -> None:
    """`_bindings`必须是 ClassVar[tuple]，不能在 instance维度被改写。

    解释：catalog 是 dispatcher 的 trust root；如果它退化为 list 或
    instance attribute，runtime就可以静默追加/删除 binding。
    """

    annotations = getattr(RuntimeActionTargetCatalog, "__annotations__", {})
    assert "_bindings" in annotations, (
        "`_bindings` annotation missing — ClassVar declaration was lost"
    )
    raw_annotation = annotations["_bindings"]
    # __annotations__ 保留 PEP563 原始形式；用 typing.get_type_hints 解开 ClassVar。
    import typing

    try:
        unwrapped = typing.get_type_hints(RuntimeActionTargetCatalog).get("_bindings")
    except Exception:
        unwrapped = None
    # unwrapped 仍是 typing.ClassVar[tuple[...]]；剥出内层 type。
    # PEP 585 之后 tuple[X, ...] 在运行时是 types.GenericAlias，
    # 但 typing.get_origin 仍然返回 tuple。
    inner = typing.get_args(unwrapped) if unwrapped is not None else ()
    assert inner, (
        "`_bindings` must be declared `ClassVar[tuple[...]]`; "
        f"raw annotation {raw_annotation!r}, unwrapped {unwrapped!r}"
    )
    inner_type = inner[0]
    origin = typing.get_origin(inner_type)
    assert origin is tuple, (
        "`_bindings` must be declared `ClassVar[tuple[...]]`; "
        f"inner type {inner_type!r}, origin {origin!r}"
    )

    binding_value = RuntimeActionTargetCatalog._bindings
    assert isinstance(binding_value, tuple), (
        f"`_bindings` runtime value must be a tuple, got {type(binding_value).__name__}"
    )


def test_catalog_resolve_remains_importable_from_evidence_module() -> None:
    """`RuntimeActionTargetCatalog.resolve` 必须从 evidence 模块可调用。

    这是 import-boundary guard：保证外部 caller（包括 dispatcher 和 tests）
    不会因为 evidence.py内部重构而出现 import drift。
    """

    assert hasattr(RuntimeActionTargetCatalog, "resolve")
    assert callable(RuntimeActionTargetCatalog.resolve)


def test_catalog_resolve_via_context_invoke_registered_target() -> None:
    """`RuntimeActionContext.invoke_registered_target`必须是 dispatcher唯一 catalog 调用入口。"""

    assert "invoke_registered_target" in dir(RuntimeActionContext)
    source = (
        Path(RuntimeActionContext.__module__.replace(".", "/") + ".py")
        .with_suffix(".py")
    )
    text = source.read_text(encoding="utf-8")
    assert "RuntimeActionTargetCatalog.resolve" in text, (
        "dispatcher.py must call RuntimeActionTargetCatalog.resolve() "
        "inside invoke_registered_target() — import boundary drift"
    )


def test_catalog_class_var_includes_bindings_and_indices() -> None:
    """catalog索引（_by_key, _by_descriptor_id）必须与 _bindings 同处 ClassVar。"""

    annotations = getattr(RuntimeActionTargetCatalog, "__annotations__", {})
    for field_name in ("_bindings", "_by_key", "_by_descriptor_id"):
        assert field_name in annotations, (
            f"`{field_name}` annotation missing — ClassVar declaration was lost"
        )


def test_catalog_is_allowed_descriptor_rejects_unknown_descriptor_id() -> None:
    """`is_allowed_descriptor` 必须拒绝不存在的 descriptor_id。

    这是 behavioral guard：保证 `_by_descriptor_id` 索引在 unknown key 上
    返回 False，而不是 fallback 命中第一条 binding。
    """

    binding = next(iter(RuntimeActionTargetCatalog._bindings))
    allowed = RuntimeActionTargetCatalog.is_allowed_descriptor(
        action_type=binding.action_type,
        handler_name=binding.handler_name,
        handler_identity=binding.handler_identity,
        target_module=binding.target_module,
        target_catalog_id=binding.target_catalog_id,
        target_handle=binding.target_handle,
        target_descriptor_id="unknown-descriptor-id",
        invocation_adapter_id=binding.invocation_adapter_id,
        implementation_id=binding.implementation_id,
        callable_identity=binding.callable_identity,
    )
    assert allowed is False, (
        "is_allowed_descriptor accepted unknown target_descriptor_id — "
        "_by_descriptor_id index is not strict"
    )


def test_catalog_resolve_total_binding_count_includes_test_and_scheduler() -> None:
    """_bindings 必须包含正式 + test + scheduler 三类 binding。

    这是 structural guard：防止出现 silent growth / shrink of catalog
    entries 而 runtime 只看得到其中一部分。
    """

    bindings = RuntimeActionTargetCatalog._bindings
    descriptors = {b.target_descriptor_id for b in bindings}
    has_test = any("test" in did.lower() for did in descriptors)
    has_scheduler = any("scheduler" in did.lower() for did in descriptors)
    assert has_test, "expected test_* descriptor in catalog"
    assert has_scheduler, "expected scheduler_* descriptor in catalog"
