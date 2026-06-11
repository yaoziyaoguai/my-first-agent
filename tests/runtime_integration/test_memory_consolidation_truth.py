"""Memory consolidation state-distinction tests.

The consolidation pipeline was frozen 2026-05-25; subsequent drift
attempts could re-promote a frozen module to product without anyone
noticing. These tests lock the four-state distinction:
  * implementation_frozen — file-level FROZEN banner present
  * dispatcher_registered — wired into RuntimeActionDispatcher
  * runtime_reachable — actually called from runtime_integration
  * default_product_usage — default in production prompt/runbooks

The current state: all 6 consolidation modules are
implementation_frozen, none are dispatcher-registered, none are
runtime-reachable, none are default_product_usage. The tests pin
this so a refactor that promotes one must update the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CONSOLIDATION_MODULES = (
    "agent/memory_consolidation.py",
    "agent/memory_consolidation_engine.py",
    "agent/memory_consolidation_pipeline.py",
    "agent/memory_consolidation_loader.py",
    "agent/memory_consolidation_llm.py",
    "agent/memory_consolidation_review.py",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_consolidation_module_count_is_six() -> None:
    """If this test ever needs an update, the road-map also must."""
    for rel in CONSOLIDATION_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing: {rel}"
    assert len(CONSOLIDATION_MODULES) == 6


def test_all_consolidation_modules_have_frozen_banner() -> None:
    """Each frozen module must carry the canonical ⛔ FROZEN banner."""
    pattern = re.compile(r"⛔ FROZEN \(\d{4}-\d{2}-\d{2}\)")
    for rel in CONSOLIDATION_MODULES:
        text = _read(rel)
        assert pattern.search(text), (
            f"{rel} is missing the FROZEN banner; "
            "if you intend to unfreeze, update the roadmap first."
        )


def test_frozen_consolidation_modules_are_not_imported_by_phase1_hook() -> None:
    """phase1_hook must not import any FROZEN consolidation module directly.

    The dispatcher registers `MemoryConsolidateHandler` (a NON-frozen handler in
    `agent/runtime_integration/memory_consolidate.py`). That handler reaches the
    frozen pipeline only through the documented compatibility adapter in
    target_catalog. This test guards against a refactor that imports a frozen
    module (e.g. `memory_consolidation_pipeline`) straight into the dispatcher
    builder, which would promote frozen code to the hot path.

    The previous version of this test compared the frozen module *file stems*
    against dispatcher *action-type strings* (e.g. `memory_consolidation_pipeline`
    vs `memory.consolidate`), which never matched and was therefore vacuously
    true. This version inspects the actual phase1_hook source for frozen-module
    imports.
    """
    import inspect

    from agent.runtime_integration import phase1_hook

    src = inspect.getsource(phase1_hook)
    offenders = []
    for rel in CONSOLIDATION_MODULES:
        stem = Path(rel).stem  # e.g. "memory_consolidation_pipeline"
        if f"agent.{stem}" in src or f"import {stem}" in src or f"from {stem}" in src:
            offenders.append(stem)
    assert not offenders, (
        "phase1_hook must not import frozen consolidation modules directly; "
        f"offenders={offenders}. The non-frozen MemoryConsolidateHandler is the "
        "only allowed dispatcher entry point."
    )


def test_memory_consolidate_handler_module_is_not_frozen() -> None:
    """The dispatcher-registered handler module itself must NOT carry a FROZEN banner.

    MEMORY_CONSOLIDATE is registered and runtime-reachable (loop.py emits it).
    Its handler lives in a non-frozen module; only the downstream pipeline is
    frozen. If someone freezes the handler module, this test fails so the
    runtime-reachable/implementation-frozen distinction stays explicit.
    """
    handler_src = _read("agent/runtime_integration/memory_consolidate.py")
    assert "⛔ FROZEN" not in handler_src, (
        "memory_consolidate.py (the dispatcher-registered handler) must not be "
        "frozen; it is the active runtime-reachable entry point."
    )


def test_consolidation_pipeline_is_referenced_only_via_compatibility_adapter() -> None:
    """The frozen pipeline may be reached only through a documented compatibility adapter.

    runtime_integration target_catalog may invoke the frozen pipeline via a
    shim whose docstring explicitly states it is compatibility, and the
    binding must mark itself legacy. This guards against a refactor that
    silently promotes a frozen module to product by importing it directly
    into a hot handler.
    """

    from agent.runtime_integration import target_catalog

    adapter = getattr(target_catalog, "_memory_consolidation_adapter", None)
    assert adapter is not None, "compatibility adapter must exist"
    assert "compatibility" in adapter.__doc__.lower() or "frozen" in adapter.__doc__.lower(), (
        "compatibility adapter docstring must state 'compatibility' or 'frozen' "
        f"to flag the legacy contract; got: {adapter.__doc__!r}"
    )


def test_frozen_pipeline_is_runtime_reachable_via_phase1_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the four-state truth: implementation_frozen BUT runtime_reachable.

    The frozen ``agent.memory_consolidation_pipeline`` module is reached from
    runtime_integration only via the catalog-owned compatibility adapter. The
    dispatcher-registered handler ``MemoryConsolidateHandler`` (non-frozen)
    invokes that adapter. This test pins the runtime-reachable side of the
    four-state distinction by monkey-patching ``run_consolidation_pipeline``
    on the module the adapter imports from and asserting the patch is hit
    when the real Phase 1 dispatcher routes a MEMORY_CONSOLIDATE request.
    """
    from agent import memory_consolidation_pipeline as frozen_pipeline
    from agent.runtime_integration.dispatcher import RuntimeActionDispatcher
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.runtime_integration.schema import (
        RuntimeActionRequest,
        RuntimeActionType,
    )

    hit_count: list[int] = []
    original_run = frozen_pipeline.run_consolidation_pipeline

    def _spy(store, *, detector=None, llm_generator=None, dry_run=False):
        hit_count.append(1)
        # Return the real pipeline result so the dispatcher's evidence chain
        # stays structurally intact; this is a reachability probe, not a
        # behavior change.
        return original_run(
            store, detector=detector, llm_generator=llm_generator, dry_run=dry_run
        )

    monkeypatch.setattr(
        frozen_pipeline, "run_consolidation_pipeline", _spy
    )
    # Catalog adapter does ``from agent.memory_consolidation_pipeline import
    # run_consolidation_pipeline`` inside the function body, so we also patch
    # the symbol on the target_catalog module (same module object under the
    # hood, but both binding points must see the patch).
    from agent.runtime_integration import target_catalog

    monkeypatch.setattr(
        target_catalog._memory_consolidation_adapter,  # type: ignore[attr-defined]
        "__wrapped__", _spy, raising=False,
    )

    dispatcher = build_phase1_dispatcher()
    assert isinstance(dispatcher, RuntimeActionDispatcher)
    # Handler must be wired; this proves dispatcher_registered.
    assert dispatcher.get_handler(RuntimeActionType.MEMORY_CONSOLIDATE) is not None

    from agent.memory_store import InMemoryMemoryStore
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_CONSOLIDATE,
        source="consolidation-truth-reachability",
        parent_trace_id="t-cst-truth",
        payload={"store": InMemoryMemoryStore()},
    )
    result = dispatcher.route(request)

    # Adapter imports the symbol fresh, so the call into
    # ``run_consolidation_pipeline`` resolves to the spied function.
    # If a future refactor stops routing through the adapter (and thus
    # stops invoking the frozen pipeline), ``hit_count`` is empty and this
    # assertion fails — that is the exact regression we want to catch.
    assert hit_count, (
        "MEMORY_CONSOLIDATE dispatch did not reach the frozen "
        "consolidation pipeline; runtime-reachable property violated. "
        f"result.status={result.status!r}"
    )
    assert result.status == "success"  # no error path; readonly
