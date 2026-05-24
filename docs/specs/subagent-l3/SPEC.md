# SubAgent L3 Activation SPEC

Status: draft
Date: 2026-05-24

## Architecture Decision: SUBAGENT_DELEGATE_L0 turn-end dispatch for L3 evidence

### 为什么现有 branch point 能承载

loop.py 的 `_try_phase1_turn_end_runtime_action()` 是统一的 turn-end hook，已经
dispatch 9 个 RuntimeActionType（含 SKILL_SELECT）。SUBAGENT_DELEGATE_L0 复用同一
hook——不新增 branch point。

### 模式同构性

与 SKILL_SELECT L3 完全相同的模式：

1. SubAgentDelegateL0Handler 已存在 (`agent/runtime_integration/subagent_action.py`)
2. RuntimeActionType.SUBAGENT_DELEGATE_L0 已定义 (`schema.py`)
3. handler 需要 SubAgentRegistry（构造参数），可在不扫描任何目录的情况下构造
   （empty roots → no subagents → handler returns rejected）
4. L3 evidence 关注「handler 是否从真实 runtime loop dispatch」而非
   「handler 是否成功 delegate 了一个 subagent」
5. rejected/failed disposition 不影响 evidence level

### 为什么不改变生产行为

- SubAgentRegistry 构造时不扫描任何 subagent 目录（empty roots）
- handler 总是 rejected（no subagent_name → _reject()）
- 不启动任何 subagent、不执行 delegation、不改变模型行为

### Evidence Classification Target

`real_core_loop_runtime_e2e`（rejected disposition，完整 evidence chain）

### Fake/Real Boundary

- Fake: SubAgentRegistry(roots=[]) → empty registry → handler always rejected
- Real: SubAgentRegistry(roots=[Path("./subagents")]) → populated registry
- 不新增 fake-only/real-only path

### Stop Conditions

- 不读 .env / 真实 sessions / subagent 目录
- 不连外部服务 / API
- 不加载真实 subagent body
- 测试失败 → 回退到 TDD 或实现
