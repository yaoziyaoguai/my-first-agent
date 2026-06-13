# Architecture Repair Mainline Retrospective

- **日期**: 2026-06-13
- **性质**: final retrospective / human-readable summary
- **依据**: North Star、Repair Roadmap、Window 1/2/3 closure audit、final mainline closure audit、capability boundary docs、golden/adversarial tests
- **范围**: 只复盘，不继续 repair；不改 production code、tests、North Star，也不创建 Window 4。

---

## 1. Executive Summary

Architecture Repair 主线已经关闭。

**ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED**

这个结论不是说所有未来增强都已经完成，也不是说 North Star 中所有维度都达到满分
3。它的含义更窄、更可验证：当前 repair mainline 的 P0/P1、MUST_FIX_NOW、
Blocker/High 已清零；Golden E2E Phase A/B/C、docs fact alignment、GE-3 rubric
复算和 full suite 证据已经完成；剩余工作都已重新分类为 tracked debt、deferred、
blocked 或 optional。

因此，后续不应继续按 Window 4 无限滚动。除非明确触发新的架构需求或回归证据，
Architecture Repair mainline 应保持关闭。

---

## 2. 最初目标

Architecture North Star 是目标架构和原则权威；Repair Roadmap 是 Current vs Target
的差距清单。两者职责不同：

| 文档 | 角色 | 不应承担的角色 |
|---|---|---|
| docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md | Target / Principle authority | 不用来伪装当前 runtime fact |
| docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md | Current→Target gap tracker | 不是无限功能 backlog |
| Window closure audits | 每个 repair window 的验收记录 | 不应在事后改写历史事实 |
| Final closure audit | GE-3 复算和主线关闭判断 | 不代表所有未来增强完成 |

这次 repair 的目标不是把所有可能的架构目标一次性做完，而是把当前主线修到“可关闭”：

- 真实 production path 不再和目标 spine 明显冲突；
- 关键路径有 Golden E2E 和 adversarial evidence；
- runtime/source facts 与文档一致；
- 中低风险债务有 owner / trigger / exit condition；
- deferred、blocked、optional work 不再被误当成当前 must-fix。

---

## 3. 初始核心问题

初始 gap 可以概括为几个互相关联的问题：

| Gap | 影响 |
|---|---|
| SubAgent routing 不完整 | V0 已 registered + contract-verified，但 production path 仍偏向 inline-local fallback，主路径口径不清 |
| E2E / golden evidence 不足 | 关键路径缺 explicit Golden E2E，无法证明 conversation、tool、subagent、memory、checkpoint、policy、evidence trace |
| fallback / provider failure / missing descriptor taxonomy 不清 | 失败、回退、拒绝、缺 handler 之间容易混淆，可能把安全失败误读成成功 |
| safe metadata ownership 不清 | masking / projection owner 容易漂移，导致 evidence 与 display 输出边界不稳 |
| action_scheduler 状态容易误解 | 它不是 production-routed，但也不是“不可达”；真实状态是 dormant-by-default / registered-not-routed |
| config/provider import-boundary 不清 | provider config、simple_config、profiles、local_config、MCP config 的 owner 与 fallback 顺序需要 inventory |
| docs 与 runtime fact 漂移 | stale docs refs 会让 Roadmap 与源码/测试事实不一致 |
| rubric 未复算 | North Star §20 仍是 provisional，无法做 final closure decision |

这些问题的共同根源不是“缺更多抽象”，而是 Current 与 Target 的边界缺少可执行证据和稳定分类。

---

## 4. 修复时间线

### Window 1

Window 1 关闭结论：**ACCEPT_WITH_TRACKED_DEBT — WINDOW 1 CLOSED**。

这一阶段解决 SA-1 和 GE-1 Phase A 的主线问题：

- SubAgent V0 production routing 接入到 dispatcher-mediated path；
- SUBAGENT_V0_ROUTING_ENABLED 仍保持 default-off，保留 rollback-safe inline-local fallback；
- Golden E2E Phase A 覆盖 simple conversation、tool success、flag-off inline-local、flag-on V0、rollback、V0-unavailable fallback、provenance assertions；
- missing descriptor、provider failure、fallback taxonomy 被锁进测试与 closure evidence；
- 不伪造 L3 / core_loop provenance，真实 evidence level 保持 subsystem_integration。

Window 1 的重要边界是：它完成 V0 production-path migration，但不把 SA-2 lifecycle/L3
relocation、real provider E2E、default-on flip 混入当前关闭条件。

### Window 2

Window 2 关闭结论：**ACCEPT_WITH_TRACKED_DEBT — WINDOW 2 CLOSED**。

这一阶段解决 SPA-1、CR-1 和 W1-D4：

- display_events.py 被确认成 safe metadata canonical masking owner；
- safe_metadata projection wrapper 保留为兼容/投影边界，而不是新的 masking owner；
- action_scheduler 被治理为 dormant-by-default / registered-not-routed in production；
- fallback dispatch guard 被 test-locked：只有 not_supported 触发 inline fallback；
- Window 2 compatibility inventory 记录 inline-local fallback、pre-loop seam、L1 attempt、local_fake path、action_scheduler 等兼容路径。

Window 2 的重要边界是：它治理当前路径，不删除 rollback path，不接入 production
approval hook，也不把 action_scheduler 激活为生产主路径。

### Window 3

Window 3 关闭结论：**ACCEPT_WITH_TRACKED_DEBT — WINDOW 3 CLOSED**。

这一阶段解决 CM-1：

- 完成 config/provider import-boundary inventory；
- 明确 agent/provider/config.py、simple_config.py、profiles.py、local_config.py、mcp_config*.py 的 owner 与边界；
- 确认 agent/provider/factory.py 是 provider selection boundary；
- 明确当前不是 provider registry，也不引入 unified capability contract；
- 将 scheduler 口径从过度的 “unreachable” 收紧为 dormant-by-default / registered-not-routed in production / injectable seam exists / manually injectable in tests。

Window 3 的重要边界是：CM-1 是 inventory 和 boundary check，不是 CM-2，不做 provider
registry，不做 scheduler wiring。

### Closure Sequence

主线关闭前又完成了四个 closure step：

| Step | 结果 |
|---|---|
| RED-1 | 修复 stale env-var docs guard，恢复 full suite green |
| GE-1 Phase B/C | 补齐 memory、checkpoint、policy、evidence-trace、minimal adversarial stub golden |
| GE-2 docs alignment | docs/CAPABILITY_BOUNDARIES.md 增加 runtime fact diff table，并对齐 RS-1 / SPA-2 / MEM-1 / CR-2 / CR-3 / CR-4 |
| GE-3 rubric re-score | North Star §20 12 个维度逐项复算，全部 after score = 2；满足 §21 mainline closure gate，但不宣称全维 3 |

最终 closure audit 记录：

- MAINLINE_CLOSE_READY = YES
- Remaining must-fix items: none
- Full suite: 4730 passed, 12 skipped, 26 xfailed

---

## 5. 实际修复清单

| Area | Original gap | What changed | Evidence | Final status |
|---|---|---|---|---|
| SA-1 | SubAgent V0 未进入 production routing path | V0 flag-on path 通过 dispatcher route；flag-off / handler-missing 保留 inline-local fallback | agent/core.py V0 routing；tests/golden_e2e/test_golden_subagent_delegation.py；Window 1 closure | DONE |
| GE-1 Phase A | 无 explicit Golden E2E baseline | 新增 conversation / tool / subagent delegation golden | tests/golden_e2e/ G1-G7；Window 1 closure | DONE |
| GE-1 Phase B/C | memory / checkpoint / policy / evidence trace / adversarial stub 缺 golden | 新增 fixtures 与 tests，锁定当前真实能力和安全失败 | test_golden_memory_checkpoint.py、test_golden_policy_evidence.py、test_minimal_policy_stub.py、5 个 fixture | DONE |
| SPA-1 | safe metadata masking owner 不清 | display_events 作为 canonical owner，projection wrapper 保持薄边界 | agent/display_events.py；tests/runtime_integration/test_safe_metadata_ownership.py；Window 2 closure | DONE |
| CR-1 | action_scheduler governance 不清 | 标注并测试 dormant-by-default / registered-not-routed in production | agent/action_scheduler.py；tests/test_architecture_boundaries.py；Window 2/3 closure | DONE |
| W1-D4 | fallback negative match 有 silent fall-through 风险 | 加 fallback dispatch guard tests，未知 status 由闭集约束防止 silent success | tests/runtime_integration/test_subagent_v0_fallback_dispatch.py；Roadmap debt table | DONE / test-guarded |
| CM-1 | config/provider import-boundary 未审 | 建 inventory，明确 owner / precedence / keep-converge 结论 | WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md；architecture boundary tests | DONE |
| GE-2 | capability docs / runtime fact 漂移 | CAPABILITY_BOUNDARIES.md 对齐 provider/tool/subagent/scheduler/memory/checkpoint/policy facts | docs/CAPABILITY_BOUNDARIES.md；docs guard；Roadmap GE-2 | DONE / completed-docs |
| GE-3 | North Star rubric 仍 provisional | 12 维逐项复算，全为 2，不宣称 full Done | ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md | DONE / completed-docs |
| RED-1 | docs SoT guard 曾因 stale env-var 裸引用转红 | 补 legacy/deprecated 标记，恢复 docs guard 与 full suite | Roadmap RED-1；full suite 4730 passed | DONE |

---

## 6. 当前系统可信度

当前系统已经可信到“mainline repair 可关闭”的程度，依据是：

- 最近 full suite：4730 passed, 12 skipped, 26 xfailed；
- Golden/adversarial coverage 覆盖 Phase A/B/C；
- SubAgent V0 routing 有真实 dispatcher evidence，并保留 rollback path；
- policy gate / fallback / evidence trace 有可观察 evidence；
- docs/source-of-truth guard 已恢复 green；
- architecture boundary tests 覆盖 scheduler、config/provider、capability boundary 等不变量；
- final closure audit 已完成 GE-3 逐维复算；
- remaining debt 均有分类、trigger、exit condition，且不阻塞当前 mainline close。

同时必须避免 overclaim：

- real provider E2E 尚未完成；
- production approval hook 尚未完成；
- CM-2 unified capability model 尚未完成；
- MEM-2 memory canonical owner 尚未完成；
- action_scheduler 没有接入 production routing；
- North Star §20 没有全维达到 3；
- 本结论只说明 mainline closure gate 达成，不说明所有未来 architecture work 结束。

---

## 7. 为什么有些没有继续修

本次 closure 的关键是把“未完成”分成可治理的类别，而不是把所有 open item 都当成
must-fix。

| 类别 | 含义 | 是否阻塞 mainline close |
|---|---|---|
| deferred | 方向被认可，但当前没有真实消费者或收益证据，不在本轮建设 | 否 |
| blocked_by_decision | 需要 owner / 用户 / 架构决策，不能由 repair agent 擅自决定 | 否 |
| blocked_by_external | 需要 credential、CI secret、稳定外部环境或真实 provider 条件 | 否 |
| blocked_by_evidence | 需要新的 runtime/eval evidence 才能证明收益；没有证据前不建设 | 否 |
| accepted_deferred | 已接受的延期项；方向有效，但当前无消费者或收益不足 | 否 |
| blocked_by_approval | 需要明确批准才能修改上位原则或历史口径 | 否 |
| tracked debt | 已记录 owner / trigger / exit condition，当前风险可接受 | 否 |
| optional | 未来增强，不是当前架构不变量 | 否 |
| drop / no-op | 审计发现原判断过度、已过时或不再是问题 | 否 |

Owner / exit condition 的长期 source of truth 仍以 Repair Roadmap 的 remaining
gap classification 和 final closure audit 为准；本复盘只给人类读者提供摘要入口。

| Item | Category | Why not fixed now | Trigger to revisit | Blocks mainline close? |
|---|---|---|---|---|
| SA-2 | deferred / blocked_by_evidence | L3 lifecycle relocation 的收益未证明；当前真实 label 是 subsystem_integration，不伪造 core_loop provenance | 出现真实 L3/gate-to-3 需求，或评测要求 SubAgent governance 升到 3 | no |
| CM-2 | blocked_by_decision | 统一 Tool / Skill / MCP / SubAgent capability contract 没有当前消费者；贸然做会扩大 scope | OD-2 明确选择 unified contract，或出现跨 surface 消费者 | no |
| MEM-2 | blocked_by_decision | memory canonical write owner 是 owner 决策；当前 memory frozen/env-gated 已 golden-locked | owner 明确要解冻 memory 并指定 canonical owner | no |
| OD-7 | blocked_by_decision / accepted_deferred | production approval hook 需要产品/安全策略决策；当前只锁 policy gate 与 no-execution evidence | 出现多用户或生产高风险 side effect approval 需求 | no |
| W1-D5 real provider E2E | blocked_by_external | 需要 credential / CI secret / 稳定外部 provider；项目规则禁止本轮 real provider call | 可用受控 credential 和 CI 环境，且 owner 授权 real provider E2E | no |
| FOP-1 | tracked debt / pre-flip blocker | 默认仍 off；real provider flag-on flip 前才会成为 blocker | 准备把 SubAgent V0 default-on 或 real provider V0 dogfood | no for current default-off; yes for default-on flip |
| SPR-1 | deferred | 跨主机 / 长任务 / HITL resume 协议没有当前需求 | 出现真实 long-task、HITL、cross-host resume 消费者 | no |
| EOE-1 | deferred | cost 字段尚无评测消费者；latency/evidence 已存在 | eval harness 将 cost 作为一等字段消费 | no |
| W1/W2/W3 tracked debts | tracked debt | 均为 Low 或已 test-guarded，已有 owner/trigger/exit | 各 debt table 中记录的具体 trigger | no |
| North Star stale-current-state cleanup | tracked debt / blocked_by_approval | North Star 是 target/principle doc，本轮明确禁止修改；current-state stale 文本不能作为最新 runtime fact | owner 明确批准 North Star amendment | no |

---

## 8. 以后什么时候重新打开 repair

只有出现明确触发条件时，才应该重新打开 architecture repair 主线或开新专项：

- 准备把某条 default-off capability 改成 default-on；
- 需要 real provider E2E，并且 credential / CI secret / 外部环境已获授权；
- 要做 production approval hook / OD-7；
- 要做 CM-2 unified capability contract；
- 要解冻 memory，并决定 MEM-2 canonical write owner；
- 要把 action_scheduler 接入 production routing；
- full suite、docs/source-of-truth guard 或 architecture boundary tests 变红；
- 新功能触碰 runtime routing / provider / memory / scheduler / policy / fallback；
- 评测或真实用户路径证明当前 score = 2 的维度必须升到 3。

没有这些触发条件时，继续 repair 只会把已治理债务误当成当前 blocker，增加 scope 和回归风险。

---

## 9. 以后不要做什么

后续维护时应避免：

- 不要继续按 Window 4 无限滚动；
- 不要把 deferred 当 must-fix；
- 不要把 Low debt 当 blocker；
- 不要在没有 trigger 的情况下做 CM-2 / MEM-2 / OD-7；
- 不要为了“补齐目标”而过度设计；
- 不要把 fake provider 或 fixture evidence 说成 real provider E2E；
- 不要把 action_scheduler 描述成 production-routed；
- 不要把 memory frozen/env-gated 说成 production memory owner ready；
- 不要删除 rollback path，除非有独立 rollout evidence；
- 不要修改 North Star 来适配现状，除非 owner 明确批准 target/principle amendment。

---

## 10. Evidence Summary

本轮 closure evidence 使用 Graphify 做 runtime/source discovery；本复盘以真实文件、测试和 closure audits 作为最终证据。

| Claim | Evidence |
|---|---|
| SubAgent V0 routing path exists and is dispatcher-mediated | agent/core.py V0 route；agent/runtime_integration/subagent_action.py；tests/golden_e2e/test_golden_subagent_delegation.py |
| RuntimeAction / dispatcher / handler 是治理扩展点 | agent/runtime_integration/schema.py；agent/runtime_integration/dispatcher.py；agent/runtime_integration/phase1_hook.py |
| safe metadata canonical owner 是 display_events | agent/display_events.py；Window 2 closure；safe metadata ownership tests |
| action_scheduler 当前 dormant-by-default / registered-not-routed | agent/action_scheduler.py；Window 2 inventory；Window 3 inventory |
| config/provider import-boundary 已 inventory | WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md；docs/CAPABILITY_BOUNDARIES.md |
| policy / rejected / no-execution path 有 golden | agent/runtime_integration/tool_gate.py；tests/golden_e2e/test_golden_policy_evidence.py；tests/adversarial/test_minimal_policy_stub.py |
| memory 当前 frozen / env-gated | agent/memory_consolidation_pipeline.py；agent/memory_runtime_hooks.py；fixtures/memory_disabled.json |
| checkpoint 当前是 local-file / intra-process roundtrip | agent/checkpoint.py；fixtures/checkpoint_local_roundtrip.json |
| evidence trace 不宣称 real provider E2E | fixtures/evidence_trace.json；GE-1 Phase B/C closure evidence |
| final closure verdict 已记录 | ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md |

---

## 11. 最终结论

Architecture Repair mainline is closed.

Remaining work is managed as tracked debt / deferred / blocked / optional work.

Do not continue repair windows unless a documented trigger fires.

**ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED**
