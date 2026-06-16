# Gap candidates (draft) — 中间产物

候选 gap，整理后写入 S1_GOAL_GAP.md / TECH_DEBT.md。剔除"愿望/历史 roadmap/S2+ 增强"。

S1_GOAL_GAP 候选：
- G-01 L1 入口存在 — satisfied
- G-02 L1 fake 稳定回归 — satisfied
- G-03 L1 real smoke 路径 — partially（缺 key-safe 步骤；受 G-15 阻塞）should_fix
- G-04 L1 fake/real same spine — satisfied（建议加同 spine 对照验收）
- G-05 L1 provider 边界薄 — satisfied
- G-06 L1 planning legacy facade 同 provider — defer_to_tech_debt TD-002
- G-07 L2 context/memory/state/checkpoint 基本可用 — partially；含 G-07b checkpoint 大结果 resume 形态 unknown_needs_audit
- G-08 L3 tool/policy/dispatcher/mediator 基本可用 — satisfied/partial
- G-09 L3 tool result→context/state 稳健；evidence 正文缺失 — partially；→ TD-001/TD-004
- G-10 L3 evidence 支撑 S1 可观测 — partially，should_fix（最小可观测已具备）
- G-11 L3 evidence 不存模型 req/resp 正文 — defer_to_tech_debt TD-001（最小观测足够，full 留 S2+）
- G-12 L4 最小多步任务状态/进度 — partially（legacy Plan 路径=S1；durable ledger=S2+）
- G-13 L5 Scheduler dormant，S1 不接入 — out_of_scope（s2_or_later）
- G-14 L5 MCP/Skill/SubAgent 边界清楚 — partially（S1 要边界清，不要激活）
- G-15 X config.yaml 被跟踪含 key — s1_blocker / release_blocker（本轮不处理密钥，记录+延期动作）
- G-16 X README/quickstart + 导航失效 — s1_gap / must_fix（本轮禁改 README，记录）
- G-17 tests 区分 acceptance vs harness — partially / should_fix（指定 S1 acceptance 子集）
- G-18 命名 v1/v2/v3 vs S — s1_gap / should_fix（由 S_ROADMAP/S1_GOAL 收口）

TECH_DEBT 候选（确认 S1 不解决、延期）：
- TD-001 evidence 不存模型/工具正文（full-fidelity capture）
- TD-002 planning/compress legacy client facade 未 provider-neutral
- TD-003 agent/context.py 并存 compress_history 无配对守卫（非主路径）
- TD-004 pending-tool events.jsonl tool_output="" 日志保真缺口

不入 gap（剔除理由）：
- ActionScheduler 全功能接入 = S2+ enhancement，非 S1 gap。
- MCP/SubAgent 全量激活 = S2+，非 S1 gap。
- 历史 roadmap 的 Window/Theme 项 = 历史证据，非当前 gap。
