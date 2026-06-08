"""Backend/provider closeout guardrails for post-memory hardening."""

from __future__ import annotations

import pytest


def test_filesystem_backend_guardrail_is_real_like_not_fake_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent.memory_fs_store import FilesystemMemoryStore
    from agent.memory_runtime import create_memory_runtime

    root = tmp_path / "memory"
    monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(root))

    runtime = create_memory_runtime()

    assert isinstance(runtime._store, FilesystemMemoryStore)
    assert runtime._store.root_dir == root


def test_provider_guardrail_does_not_claim_real_provider_from_fake_provider() -> None:
    from agent.provider.fake_provider import FakeProvider

    provider = FakeProvider()

    assert getattr(provider, "provider_type", "") == "fake"
    assert "real" not in getattr(provider, "provider_type", "").lower()
