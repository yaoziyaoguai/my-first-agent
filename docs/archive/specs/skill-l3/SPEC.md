# Skill L3 Activation SPEC

Status: draft
Date: 2026-05-24

## Architecture Decision: SKILL_SELECT turn-end dispatch for L3 evidence

### 为什么现有 branch point 能承载

loop.py 的 `_try_phase1_turn_end_runtime_action()` 是统一的 turn-end hook，已经
dispatch 7 个 RuntimeActionType。SKILL_SELECT 复用同一 hook——不新增 branch point。

### 为什么 turn-end 对 L3 evidence 是合理的

1. SkillRuntimeActionHandler 已存在 (`agent/runtime_integration/skill_action.py`)
2. RuntimeActionType.SKILL_SELECT 已定义 (`schema.py:22`)
3. handler 需要 SkillRegistry + SkillLoader（构造参数），两者均可在不扫描任何
   目录的情况下构造（empty roots → no skills → handler returns rejected）
4. L3 evidence 关注「handler 是否从真实 runtime loop dispatch」而非「handler
   是否成功 load 了一个 skill」
5. rejected/failed disposition 不影响 evidence level — 证据链仍完整
6. 实际 skill selection 由模型输出驱动（mid-loop），L3 wiring 只证明 dispatch
   路径可行；不影响现有 skill selection 行为

### 为什么这不改变生产行为

- SkillRegistry 构造时不扫描任何 skill 目录（empty roots）
- 因此 `list_visible()` 返回空 → handler 总是 rejected
- 不加载任何 skill body、不注入 system prompt、不改变工具可见性
- 现有 skill system 通过模型输出 dispatch 工作，不经过 turn-end hook

### 与 MEMORY_RECALL/MEMORY_CONSOLIDATE 的同构性

两者均在 turn-end hook 上 dispatch，但语义上分别属于 pre-loop 和 post-session。
L3 wiring 不改变它们的实际执行时机——只提供 evidence chain 证明。SKILL_SELECT
同此模式。

## Evidence Classification Target

| Level | 条件 |
|-------|------|
| `subsystem_integration` | direct handler 调用 |
| `harness_runtime_e2e` | dispatcher.route() with target_module_proof |
| `real_core_loop_runtime_e2e` | route_from_runtime_loop with core_entrypoint |

本轮目标：`real_core_loop_runtime_e2e`（rejected disposition，完整 evidence chain）

## Fake/Real Boundary

- Fake: SkillRegistry(roots=[]) → empty registry → handler always rejected
- Real: SkillRegistry(roots=[Path("./skills")]) → populated registry → handler may succeed
- 不新增 fake-only/real-only path
- 不改变 core.chat() 的 skill selection 行为

## Stop Conditions

- 不读 .env / 真实 sessions / skill 目录
- 不连外部服务 / API
- 不加载真实 skill body
- 测试失败 → 回退到 TDD 或实现

## Review Checklist

- [ ] 不新增 branch point / Anchor / runtime flow
- [ ] fake/real 只有 registry roots 差异
- [ ] 不读取真实 skill 文件
- [ ] 不改变模型输出 dispatch 行为
- [ ] L3 evidence chain 完整（dispatcher_origin、runtime_loop_invoked、core_entrypoint）
