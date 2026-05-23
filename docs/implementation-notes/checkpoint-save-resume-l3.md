# Implementation Notes: Checkpoint Save/Resume L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](../specs/checkpoint-save-resume-l3/SPEC.md)

## 实现了什么

- 4 条新增测试覆盖 Checkpoint safe summary 的 L3 evidence
- T1: core.chat() turn-end 正确 dispatch CHECKPOINT_SAFE_SUMMARY + L3 evidence
- T2: hook 级 CHECKPOINT_SAFE_SUMMARY 独立 dispatch 验证
- T3: direct dispatcher.route 保持 L2（payload 伪造无效）
- T4: 隔离环境安全验证

## 生产代码改动

| 文件 | 改动 | 行数 |
|------|------|------|
| `agent/loop.py` | 在 turn-end hook 末尾增加 CHECKPOINT_SAFE_SUMMARY dispatch | +27 |
| `agent/runtime_integration/phase1_hook.py` | import + 注册 CheckpointSafeSummaryHandler | +5 |

总计生产代码改动：+32 行，两个文件。

## 测试文件改动

| 文件 | 改动 | 原因 |
|------|------|------|
| `tests/runtime_integration/test_checkpoint_save_resume_l3.py` | 新增 4 tests | T1-T4 覆盖 L3/L2 |
| `tests/runtime_integration/test_phase1_real_core_loop.py` | +3 lines | 本地 `_build_phase1_dispatcher()` 注册新 handler |
| `tests/runtime_integration/test_tool_pipeline_l3_completion.py` | +1 line | expected_types 加 `checkpoint.safe_summary` |

## 没做什么

- 未修改 `checkpoint_summary.py`（handler 零改动）
- 未修改 `evidence.py`（catalog descriptor 已存在）
- 未修改 `dispatcher.py`（路由逻辑零改动）
- 未修改 `schema.py`（RuntimeActionType.CHECKPOINT_SAFE_SUMMARY 已存在）
- 未修改 `checkpoint.py`（save/load/clear 函数零改动）
- 未新增 Anchor / branch point / runtime flow / RuntimeActionType

## 复用了哪些代码

| 模块 | 复用方式 |
|------|---------|
| `agent/runtime_integration/checkpoint_summary.py` | CheckpointSafeSummaryHandler 已存在，零改动直接注册 |
| `agent/runtime_integration/evidence.py` | checkpoint.safe_summary catalog descriptor 已存在 |
| `agent/loop.py` | 遵循 MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE 的完全相同 dispatch pattern |
| `agent/runtime_integration/phase1_hook.py` | 遵循已有 handler 注册 pattern |
| `agent/runtime_integration/dispatcher.py` | route_from_runtime_loop / _route / _mark_returned_to_parent 零改动 |
| `tests/runtime_integration/test_tool_gate_not_found_l3.py` | _PipelineSpy, _make_mock_state 模式复用 |

## Tradeoffs / Deviations

- CheckpointSafeSummaryHandler 在 turn-end 产生 checkpoint boundary evidence 但不调用 save_checkpoint。save_checkpoint 仍在 core.py 中直接调用。这是设计选择——handler 证明 boundary 被触达，save 由 core.py 在正确时机执行。
- 需要更新两个现有测试（test_phase1_real_core_loop.py 和 test_tool_pipeline_l3_completion.py），因为它们有本地 dispatcher builder 副本或硬编码 expected_types 集合。这是正常的上游变更传播。

## Tests/Gates

| Gate | Result |
|------|--------|
| `test_checkpoint_save_resume_l3.py` (4 tests) | 4 passed |
| `tests/runtime_integration/` (full) | 305 passed, 5 skipped |
| ruff | clean |
| git diff --check | clean |
