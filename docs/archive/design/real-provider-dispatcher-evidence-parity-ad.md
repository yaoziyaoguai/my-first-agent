# Real-Provider Dispatcher / Evidence Parity AD

- **Date:** 2026-05-25
- **Status:** active
- **Source:** RT-01 from `docs/audit/global-red-team-product-architecture-audit-2026-05-25.md`
- **Decision:** Make Phase 1 RuntimeActionDispatcher the product default for ALL providers

## Problem

`agent/core.py:782-791` 的分支逻辑：

```python
if runtime_action_dispatcher is not None:
    _phase1_dispatcher = runtime_action_dispatcher  # dogfood/测试注入
elif getattr(provider, "provider_type", None) == "fake":
    _phase1_dispatcher = build_phase1_dispatcher()  # fake 自动构建
else:
    _phase1_dispatcher = None  # real/default provider — 无 dispatcher！
```

当 real provider 走默认路径时，`_phase1_dispatcher = None`，导致：
- loop turn-end hook 不触发
- MEMORY_PROPOSE、SKILL_* 等 turn-end runtime actions 不执行
- evidence path 在 fake/real 之间不一致
- fake 路径有 dispatcher/evidence，real 路径没有

## Why This Matters

这不是"real provider 是否需要 dispatcher"的问题——dispatcher 本身不调用任何 LLM 或外部 API。它是纯 runtime logic：memory propose、skill routing 等都是本地逻辑，provider-agnostic。

当前分支逻辑其实是历史遗留：dispatcher 最初只在 fake provider 下测试，后来 dogfood 脚本通过注入参数使用，但默认 real provider 路径从未被更新为自动构建。

## Decision

**所有 provider 类型统一自动构建 Phase 1 RuntimeActionDispatcher。**

理由：
1. Dispatcher 是 provider-neutral runtime logic，不依赖任何特定 provider
2. 它不调用 LLM、不读 .env、不访问网络
3. 证据/可观测性路径应该在 fake 和 real 之间一致
4. 这是统一 runtime flow contract 的要求

## Implementation

`agent/core.py` 中改动：移除 `elif provider type == "fake"` 的检查，改为总是自动构建 dispatcher，除非调用方显式传入 `None`。

```python
if runtime_action_dispatcher is not None:
    _phase1_dispatcher = runtime_action_dispatcher
else:
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    _phase1_dispatcher = build_phase1_dispatcher()
```

关键点：
- 调用方仍可通过显式传入 dispatcher 覆盖（dogfood 注入点保留）
- 默认路径对所有 provider 一致
- 构建本身无副作用——只有 turn-end 时 `.route()` 才被调用

## What This Does NOT Do

- 不改变 tool_use 模型触发路径（response_handlers → tool_executor，与 dispatcher 无关）
- 不新增 provider-specific hack
- 不为 dogfood script 特判
- 不改变 core.chat 行为语义
- 不新增 RuntimeActionType

## Verification

Contract test 覆盖：
- fake provider default path builds dispatcher ✅ (existing)
- real/anthropic_compatible provider default path builds dispatcher (NEW)
- dogfood injected dispatcher still takes priority (existing injection point)
- dispatcher is provider-neutral — same handlers for all provider types

Gates:
- `git diff --check`
- `.venv/bin/ruff check agent/core.py`
- `HOME=/private/tmp .venv/bin/python -m pytest tests/test_provider_contract.py tests/runtime_integration/ -q`
