# Runtime Decision Spine — Design Document

Status: Loop 1.1 implementation design
Date: 2026-05-28
Scope: agent/runtime_decision_frame.py

## 1. 问题

First Agent 的子系统（Tool / MCP / Skill / Memory / SubAgent / Checkpoint / Trace）
当前各自通过不同路径进入运行时：

- Tool 真实执行走 `response_handlers.handle_tool_use_response` → `tool_executor`
- Tool RuntimeAction pipeline 走 turn-end hook → dispatcher → `_safe_noop` probe
- Memory recall 走 `refresh_runtime_system_prompt(dispatcher=...)`，dispatcher=None 时走 direct snapshot
- Memory retain 部分走 dispatcher，forget/list 走 CLI shortcut
- Skill 默认 `skill_registry=None`，`build_skills_section()` 返回空字符串
- MCP bridge 默认 disabled，不走 core.chat
- SubAgent 仅 L0 deterministic executor，core.chat 中通过 CLI/NL shortcut 拦截
- Checkpoint save 分散在 core.chat 多处手动调用

没有统一的地方表达"这个子系统在当前 turn 中处于什么状态"。

上一版审计（2026-05-28 full-subsystem-capability-completion-audit）将 registry/descriptor/docs/guard-test 存在算作 COMPLETE，
导致声称完成率 77%（90/117）。
红队补审校正后真实完成率 23.1%（27/117）。

根因：缺少一个 runtime-owned decision vocabulary，导致注册表存在即 COMPLETE、probe 通过即 E2E、direct-call 即 capability。

## 2. RuntimeDecisionFrame 的目的

RuntimeDecisionFrame 不是新 runtime，不是 scheduler，不是 executor。

它只做一件事：**在 core.chat() 入口处描述当前 turn 各子系统的参与状态**。

具体来说：

1. **表达，不执行** — 所有字段都是描述性的（str / bool / enum），没有 execute()/run()/dispatch() 方法
2. **诚实标记** — 未 ready 的子系统必须显式标 NOT_READY / DEFERRED / PARTIAL / FAKE_DEMO，不能 silent pass
3. **有限 branch point** — 14 个预定义 branch point，禁止无限发散
4. **证据等级绑定** — 每个 branch point 绑定当前证据等级，防止 docs/test/guard 冒充 capability
5. **供 summary/trace 引用** — `_emit_run_summary` 可读取 decision frame，产出诚实摘要

它不替代：
- core.chat() 的执行路径
- loop.py 的模型循环
- RuntimeActionDispatcher 的 action dispatch
- 任何 handler 的执行逻辑

## 3. 为什么不是第二 runtime

Decision frame 和 runtime 的边界：

| 维度 | Runtime (core/loop) | Decision Frame |
|------|-------------------|----------------|
| 目的 | 执行用户请求 | 描述各子系统状态 |
| 操作 | 调模型、调工具、写 memory、改 state | 只读查询 (getattr, list_visible) |
| 副作用 | 有（修改 state, 发送 API 请求） | 无（frozen=True dataclass） |
| 循环 | while True 主循环 | 无循环 |
| 调度 | dispatch_model_output, turn-end hook | 无调度 |
| 构造时机 | 每次 chat() 持续运行 | chat() 入口一次性构造 |
| 对其他模块依赖 | 依赖 provider, tool, memory, skill 等 | 仅依赖 runtime_decision_frame 自身的静态注册表 |

核心原则：
- Decision frame 是 **core/loop 主路径内的决策脊柱**，不是路径外的第二系统
- 它不改变任何执行路径 —— 现有 if/return/while 逻辑全部保留
- 它不引入新的 import 依赖链 —— 枚举和 dataclass 是纯数据

## 4. 与 core/loop 的边界

```
用户输入 → core.chat()
  ├─ 空输入守卫
  ├─ CLI meta-command 检测（提前 return）
  ├─ ★ build_decision_frame_from_chat_params()   ← 新增：一次性构造
  ├─ Memory evaluation（evaluate_user_text）
  ├─ refresh_runtime_system_prompt()
  ├─ planning phase / 确认 / 主循环
  │    └─ _try_phase1_turn_end_runtime_action()
  │         └─ TOOL_GATE / SKILL_SELECT / MEMORY_* / SUBAGENT_DELEGATE_L0 ...
  └─ _emit_run_summary()                         ← 读取 decision frame 摘要
```

Decision frame 构造在 chat() 入口、参数解析完成后。
构造时机在所有 CLI shortcut 检查**之前**，确保所有路径都有 frame。
构造是纯读操作：getattr(provider, "provider_type")、skill_registry.list_visible()（try/except 保护）。

## 5. BranchPoint Status / Evidence Model

### 5.1 BranchPointStatus

| Status | 含义 | 示例 |
|--------|------|------|
| READY | 已接入主路径，真实执行业务闭环 | (当前无) |
| PARTIAL | 部分接入，存在 direct/shortcut 路径 | memory.recall, tool.gate |
| DEFERRED | 明确延期 | mcp.discover, mcp.invoke |
| NOT_READY | 能力未就绪 | skill.select（默认 registry=None） |
| FAKE_DEMO | 仅 fake/demo | subagent.delegate (L0) |
| DIRECT_CALL_ONLY | 只有直接调用路径 | — |
| STUB | 接口存在但无实际行为 | skill.apply |

### 5.2 EvidenceLevel

| Level | 含义 | 是否支撑 COMPLETE |
|-------|------|-------------------|
| PRODUCTION_PATH | 生产级主路径验证 | 是 |
| REAL_API_INTERACTIVE | 真实 API 交互验证 | 是 |
| REAL_API_SMOKE | 真实 API smoke 验证 | 是 |
| FAKE_LOCAL_USER_PATH | fake provider 下用户路径 | 可支撑 fake/local 阶段 |
| UNIT_DIRECT_CALL | 直接子系统调用 | 否 |
| GUARD_TEST | 守护/不变式测试 | 否 |
| DOCS_DESIGN | 只有设计文档 | 否 |

### 5.3 Overclaim 防护规则

```python
# is_capability_complete() = status==READY AND evidence_level >= FAKE_LOCAL_USER_PATH
# should_not_silent_pass() = status in (NOT_READY, DEFERRED, STUB)
```

禁止的组合：
- status=PARTIAL + "capability complete" → 拒绝
- status=FAKE_DEMO + "E2E verified" → 拒绝
- evidence_level=GUARD_TEST + evidence=COMPLETE → 拒绝
- no-crash → PASS → 拒绝（no-crash 不是 capability 证据）

## 6. 各子系统如何通过 Decision Frame 表达

### Tool
- Branch points: tool.gate, tool.invoke, tool.result
- 当前状态: PARTIAL
- 为什么 PARTIAL: 模型 tool_use → tool_executor（真实路径）和 RuntimeAction TOOL_GATE/INVOKE/RESULT（turn-end probe, 默认 _safe_noop）是两条分离路径，尚未统一
- 证据等级: FAKE_LOCAL_USER_PATH

### MCP
- Branch points: mcp.discover, mcp.invoke
- 当前状态: DEFERRED
- 为什么 DEFERRED: bridge 默认 disabled, core.chat 不调用 run_mcp_bridge()
- 证据等级: DOCS_DESIGN
- 后续: Loop 2.4 — 复用 Tool pipeline

### Skill
- Branch points: skill.select, skill.apply
- 当前状态: skill.select=NOT_READY, skill.apply=STUB
- 为什么 NOT_READY: LoopDependencies.skill_registry 默认 None, build_skills_section() 返回空
- 证据等级: GUARD_TEST / DOCS_DESIGN
- 后续: Loop 2.2 — Skill Activation MVP

### Memory
- Branch points: memory.recall, memory.propose, memory.retain
- 当前状态: PARTIAL
- 为什么 PARTIAL: 用户主动 retain 已走 dispatcher; recall 有 direct fallback; forget/list 走 CLI shortcut; model-suggested/implicit DEFERRED
- 证据等级: FAKE_LOCAL_USER_PATH
- 后续: Loop 2.1 — Explicit Memory Main-Path Completion

### SubAgent
- Branch point: subagent.delegate
- 当前状态: FAKE_DEMO
- 为什么 FAKE_DEMO: L0 是 deterministic executor, 不调 provider/不执行工具/不写 memory
- 证据等级: FAKE_LOCAL_USER_PATH（但仅标记为 demo）
- 后续: Loop 3.2 — Real SubAgent L1/L2

### Checkpoint
- Branch points: checkpoint.save, checkpoint.resume
- 当前状态: PARTIAL
- 为什么 PARTIAL: save/load schema 存在; true resume 不恢复 running tool/model 状态
- 证据等级: FAKE_LOCAL_USER_PATH
- 后续: Loop 2.3 — Storage / Checkpoint True Resume

### Trace / Summary
- Branch point: trace.summary
- 当前状态: PARTIAL
- 为什么 PARTIAL: in-memory action_log, 无 durable evidence store
- 证据等级: FAKE_LOCAL_USER_PATH
- 后续: 随其他子系统成熟而成熟

## 7. 哪些能力只允许标 PARTIAL/DEFERRED/FAKE_DEMO

当前 14 个 branch point 中：
- READY: 0 个
- PARTIAL: 8 个 (memory.recall, memory.propose, memory.retain, tool.gate, tool.invoke, tool.result, checkpoint.save, checkpoint.resume, trace.summary)
- NOT_READY: 1 个 (skill.select)
- DEFERRED: 2 个 (mcp.discover, mcp.invoke)
- FAKE_DEMO: 1 个 (subagent.delegate)
- STUB: 1 个 (skill.apply)

**任何情况下，以下不能标 COMPLETE**：
- Skill select/apply — 直到 registry 注入 main path 且 body 进入 model prompt
- MCP discover/invoke — 直到 bridge 在 core.chat 中接入 main path
- SubAgent delegate — 直到 L1 child provider loop 实现
- 任何 evidence_level < FAKE_LOCAL_USER_PATH 的 branch point

## 8. 后续 Loops 如何基于 Decision Frame 接入真实能力

Decision frame 是一个"升级追踪器"：

1. **Loop 1.3 — Tool Path Unification** 完成时：tool.gate/invoke/result 从 PARTIAL → READY（如果两条路径统一）
2. **Loop 2.1 — Explicit Memory Main-Path** 完成时：memory.recall/propose/retain 从 PARTIAL → READY
3. **Loop 2.2 — Skill Activation MVP** 完成时：skill.select 从 NOT_READY → PARTIAL/READY
4. **Loop 2.4 — MCP Main-Path Readiness** 完成时：mcp.discover/invoke 从 DEFERRED → PARTIAL
5. **Loop 3.2 — Real SubAgent** 完成时：subagent.delegate 从 FAKE_DEMO → PARTIAL/READY

每次升级必须伴随：
- BRANCH_POINT_REGISTRY 中对应 BranchPointState 的 status/evidence_level 更新
- 回归测试证明升级是真实的（不是换了标签但能力不变）
- PROJECT_STATUS 更新

## 9. 实现决策

### 9.1 文件位置

`agent/runtime_decision_frame.py` — 独立模块，不修改现有 schema.py / core.py / loop.py 的结构。

### 9.2 数据不可变性

- BranchPointState: frozen=True, slots=True
- RuntimeDecisionFrame: frozen=True, slots=True
- BRANCH_POINT_REGISTRY: 应冻结为只读

### 9.3 测试接缝

- `get_last_decision_frame()` / `set_last_decision_frame()` — 模块级 inspection seam
- `build_decision_frame()` — 纯工厂，可独立测试
- `build_decision_frame_from_chat_params()` — 接受 mock provider/registry

### 9.4 与现有 runtime_integration/schema.py 的关系

schema.py 管理 per-action 消息（RuntimeActionRequest → handler → RuntimeActionResult）。
decision_frame.py 管理 per-turn subsystem 状态（BranchPointState → RuntimeDecisionFrame）。

两者是互补的：schema 描述"这个 action 发生了什么"，decision frame 描述"这个子系统当前处于什么状态"。

decision frame 不重复 schema 的 RuntimeActionType 枚举，而是新增 BranchPointStatus / EvidenceLevel 两个正交维度。

### 9.5 对 core.py/loop.py 的影响

- core.py: 新增 ~13 行（import + 构造 + 存储）
- loop.py: 新增 ~9 行（import + 读取 + 传参）
- display_events.py: 新增 ~3 行（可选参数）

所有改动都是增量的，不删除、不重写、不改变现有行为。
