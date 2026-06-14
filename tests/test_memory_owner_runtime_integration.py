"""MemoryOwner runtime integration tests.

验证 MemoryRuntime explicit_user_request retain/forget 主路径经过 MemoryOwner。
"""

from __future__ import annotations

from pathlib import Path


def test_memory_owner_wired_into_runtime_retain_path(tmp_path: Path) -> None:
    """explicit_user_request retain path 经过 MemoryOwner。

    验证链：
    1. MemoryRuntime 创建后，MemoryOwner 在写路径上
    2. explicit retain 通过 confirmation → stored
    3. duplicate retain → noop（store 记录数不变）
    4. 敏感内容 → rejected
    """
    from agent.memory_confirmation import MemoryConfirmationChoice as Choice
    from agent.memory_owner import MemoryOwner
    from agent.memory_policy import DeterministicMemoryPolicy
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    owner = MemoryOwner(store=store)
    runtime = MemoryRuntime(policy=DeterministicMemoryPolicy(), store=store, owner=owner)

    # Step 1: explicit retain
    result = runtime.evaluate_user_text("remember that 用户喜欢用 Rust 编程")
    assert result.action == "confirmation_required", f"expected confirmation, got {result.action}"
    cid = result.candidate_id
    assert cid

    resolved = runtime.resolve_confirmation(cid, choice=Choice.ACCEPT)
    # With owner: returns owner_create; without owner: returns stored
    assert resolved.action == "stored", f"expected stored, got {resolved.action}: {resolved.reason}"

    # Step 2: verify store has Rust record
    records = store.list_records()
    rust_count = len([r for r in records if "Rust" in r.content])
    assert rust_count >= 1, f"expected >=1 Rust records, got {rust_count}"

    # Step 3: duplicate → noop
    result2 = runtime.evaluate_user_text("remember that 用户喜欢用 Rust 编程")
    assert result2.action == "confirmation_required"
    resolved2 = runtime.resolve_confirmation(result2.candidate_id, choice=Choice.ACCEPT)
    assert resolved2.action == "rejected", f"duplicate 应 rejected (noop), got {resolved2.action}"
    assert "noop" in (resolved2.reason or "").lower(), (
        f"reason should mention noop: {resolved2.reason}"
    )

    # count unchanged
    records2 = store.list_records()
    rust_count2 = len([r for r in records2 if "Rust" in r.content])
    assert rust_count2 == rust_count, f"noop 不应增加记录 ({rust_count}→{rust_count2})"

    # Step 4: sensitive content → rejected
    result3 = runtime.evaluate_user_text("remember that my API key is sk-ant-1234567890abc")
    if result3.action == "confirmation_required":
        resolved3 = runtime.resolve_confirmation(result3.candidate_id, choice=Choice.ACCEPT)
        assert resolved3.action == "rejected", (
            f"sensitive should be rejected, got {resolved3.action}"
        )
        assert (
            "policy" in (resolved3.reason or "").lower()
            or "owner" in (resolved3.reason or "").lower()
        )


def test_runtime_without_owner_still_works():
    """向后兼容：不传 owner 时 MemoryRuntime 仍用旧路径。"""
    from agent.memory_confirmation import MemoryConfirmationChoice as Choice
    from agent.memory_policy import DeterministicMemoryPolicy
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(policy=DeterministicMemoryPolicy(), store=store)

    result = runtime.evaluate_user_text("remember that 用户使用 VS Code")
    assert result.action == "confirmation_required"
    resolved = runtime.resolve_confirmation(result.candidate_id, choice=Choice.ACCEPT)
    assert resolved.action == "stored", f"without owner should still store, got {resolved.action}"
