# Implementation Plan: Checkpoint Save/Resume L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Parent TDD: [TDD.md](TDD.md)

## Implementation Units

### U1: Register CheckpointSafeSummaryHandler in build_phase1_dispatcher()

**File**: `agent/runtime_integration/phase1_hook.py`
**Change**: 在 `build_phase1_dispatcher()` 中 import 并注册 `CheckpointSafeSummaryHandler`
**Lines**: +2 import, +4 register

### U2: Dispatch CHECKPOINT_SAFE_SUMMARY in turn-end hook

**File**: `agent/loop.py`
**Change**: 在 `_try_phase1_turn_end_runtime_action()` 中增加 CHECKPOINT_SAFE_SUMMARY dispatch（独立 try/except，与 MEMORY 和 TOOL_GATE 同 pattern）
**Lines**: ~15

### U3: Write L3 tests

**File**: `tests/runtime_integration/test_checkpoint_save_resume_l3.py` (新增)
**Tests**: T1-T4 per TDD.md

## TDD-First 顺序

```
U3 (写测试，RED) → U1+U2 (最小实现，GREEN) → U3 (验证 GREEN) → T5 (回归)
```

## 允许修改范围

- `agent/runtime_integration/phase1_hook.py` — import + register handler
- `agent/loop.py` — 增加 CHECKPOINT_SAFE_SUMMARY dispatch

## 禁止修改范围

- `agent/runtime_integration/checkpoint_summary.py` — 零改动
- `agent/runtime_integration/evidence.py` — 零改动
- `agent/runtime_integration/dispatcher.py` — 零改动
- `agent/runtime_integration/schema.py` — 零改动
- `agent/checkpoint.py` — 零改动
- `agent/core.py` — 零改动
- 不新增 RuntimeActionType
- 不修改 checkpoint schema

## 如何接入 loop.py turn-end hook

遵循已有 MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE 的完全相同的 pattern：

```python
# CHECKPOINT_SAFE_SUMMARY action（独立 try/except——失败不阻断 MEMORY 和 TOOL_GATE）
try:
    checkpoint_request = RuntimeActionRequest(
        action_type=RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        source="core_loop",
        parent_trace_id="",
        payload={
            "runtime_state_summary": result_text,
            "trigger": "turn_end",
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": provider_kind,
            "provider_external_call": provider_external_call,
            "external_side_effects": False,
        },
    )
    route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
    route(checkpoint_request)
except Exception:
    pass
```

## 如何保持 loop.py thin orchestration

- CHECKPOINT_SAFE_SUMMARY dispatch 只构造 request 并 route
- 不解析 checkpoint 内部语义
- 不调用 save_checkpoint
- 不读/写 checkpoint 文件
- 失败 silent fail，不阻塞其他 dispatch

## Stop Conditions

- P0/P1 in review
- 需要新增 branch point
- 需要真实 API / .env / secret
- 需要真实 sessions/runs
- 已有测试回归失败

## Implementation Notes 路径

`docs/implementation-notes/checkpoint-save-resume-l3.md`
