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
