# S1 readiness matrix (draft) — 中间产物

按五层能力给"S1 基本可用"就绪度（不是最终成熟）。状态：OK=基本可用/边界清楚；PARTIAL=可用但有缺口；RISK=有风险待决；OUT=S1 不接入（by design）。

| 层 | 能力 | 就绪 | 依据 | S1 缺口/风险 |
|---|---|---|---|---|
| L1 | 单一入口 + runtime loop | OK | main.py:637→core.py:763→loop | — |
| L1 | provider 薄边界 + 单工厂 | OK | protocol.py:77, factory.py:18 | — |
| L1 | fake/real same spine | OK | loop.py:249/690, core.py:1158-1159, legacy_adapter | 仅 legacy planning facade 形态待迁移（TD-002） |
| L1 | real provider smoke | PARTIAL | real adapters + test_provider_real_smoke.py | 无 key-safe smoke 步骤文档；受 config key 阻塞（G-15） |
| L2 | memory recall/retain/turn-end | OK | core.py:961/1065, loop.py:285-435 | fs store 默认关（可配置） |
| L2 | 压缩配对安全 | OK | memory.py:220/261-263 | 并存 context.py 无守卫（TD-003） |
| L2 | state machine | OK | state.py:13/192 | — |
| L2 | checkpoint save/resume | PARTIAL | checkpoint.py, session.py:405 | 大结果摘要后 resume 形态未验证（G-07b unknown） |
| L3 | tool registry + mediator + executor | OK | tool_registry/mediator/executor | — |
| L3 | policy/confirmation gate | OK | tool_gate.py:32（两模式一致） | 无顶层统一 policy 开关 |
| L3 | tool result→context/state | OK | conversation_events.py:116 | — |
| L3 | evidence 可观测 | PARTIAL | logger/event_log/record_evidence | 不存模型/工具正文（TD-001）；pending tool_output=""（TD-004） |
| L4 | 最小多步任务状态 + 进度 | PARTIAL | state.py:192, meta.py:45, transitions.py:639 | 进度=checkpoint 快照，无独立 ledger；ActionPlan 路径 dormant |
| L5 | Scheduler | OUT | action_scheduler dormant, main.py 0 引用 | S1 不接入/不删除 |
| L5 | MCP | PARTIAL(边界清) | main.py:587 默认关 | S1 只需边界清楚，不默认激活 |
| L5 | SubAgent | PARTIAL(边界清) | V0 默认关 + local_fake stub | 生产 wiring 未完成（S2+） |
| L5 | Skill | PARTIAL(实验) | skill_system + lifecycle | 实验性 |
| X | config key 未提交 | RISK | config.yaml 被跟踪含 key | release blocker（G-15） |
| X | README/quickstart 可用 | RISK | README 导航指向 history | must_fix（G-16） |
| X | S/旧 v 命名区隔 | RISK | 代码 v0.x/Phase 命名 | 由 S_ROADMAP/S1_GOAL 收口 |
