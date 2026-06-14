# Module Maturity — Navigation

Post-repair module maturity / hardening 阶段的工作目录。

**当前状态:Module Taxonomy Gate 已通过(`MODULE_TAXONOMY_APPROVED = YES`,Option γ,15 模块)。Module Maturity Audit 已完成;T-SKILL-GOLDEN 已关闭。**

**T-PROVIDER-E2E activation audit 已完成;trigger 仍为 `BLOCKED_BY_EXTERNAL`,未运行真实 API,未产生 L4 evidence。**
**T-PROVIDER-E2E secret safety hardening 已完成**：`api_key_env` indirection、`config.local.yaml` 本地优先、real/fake guard fix、response body leak fix、real smoke preview hardening。
**T-PROVIDER-E2E real provider smoke PASSED**（2026-06-14）：DeepSeek `deepseek-v4-flash` via `anthropic_compatible` + `https://api.deepseek.com/anthropic`。**这不是 L4**，只是 minimal adapter smoke。

- Architecture Repair Mainline 仍 CLOSED(`ACCEPT_WITH_TRACKED_DEBT`)。本目录**不是** active repair queue,不开启 Window 4。
- 原 maturity audit 为 docs-only;T-SKILL-GOLDEN 关闭仅新增 golden test / fixture 与最小状态文档,不改 production code / North Star。
- North Star 是目标模型,不是待办队列;North Star gap ≠ must-fix。

## 文件

| Path | Role | Status |
|---|---|---|
| `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md` | 模块分法 gate 发现 + 决策(D1–D4 / C1–C2)+ 候选 option | current — 已由用户以 Option γ 批准 |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | 15 模块 L0–L4 成熟度审计 + action 分类;当前无 HARDEN_NEXT | current |
| `POST_REPAIR_TRIGGER_REGISTRY.zh.md` | trigger 寄存器 + 激活 playbook("No trigger, no work");每个 blocked/deferred/harden 项的触发条件与开工路径 | current |
| `L3_HARDENING_TRIAGE.zh.md` | L3 hardening triage——8 模块逐模块 triage + recommended next target | current — triage completed; Skill L3 done; recommended next: State or SubAgent FOP-1 |
| `FREEZE_FILE_INTEGRITY_AUDIT.zh.md` | Freeze file integrity audit——验证冻结文件未被越权修改 | current — audit completed; verdict CLEAN_WITH_LOW_RISK_NOTES |
| `MEMORY_OWNER_DECISION_SPIKE.zh.md` | MEM-2 decision spike——12 决策域拆解 + 推荐选项 + 激活路径 | current — decision spike completed;T-MEM2 remains blocked_by_decision |
| `POST_MEMORY_L3_NEXT_TARGET_SELECTION.zh.md` | Post-Memory-L3 next target selection——从治理文档推导下一刀 | current — selection completed; recommended: State resume golden |

## 阅读顺序

1. 先读 `AGENT_MODULE_MATURITY_AUDIT.zh.md`(总表在 §4,逐模块在 §5,下一步在 §7)。
2. taxonomy 决策依据见 `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`。
3. 背景按 `docs/06-audit/README.md` 顺序:retrospective → closure audit → `docs/CAPABILITY_BOUNDARIES.md` → North Star(目标,不是 runtime fact)。

## 关键结论(摘要)

- Mainline 已串通;问题是**模块成熟度不均衡**(L3 骨架/横切簇 + L3 Skill System + L2 能力簇 + L1 dormant scheduler),且不均衡几乎全是**有意 deferred/blocked**。
- **T-MEM2 L3 achieved**: MemoryOwner wired into MemoryRuntime explicit_user_request retain path；create/noop/reject on runtime；not L4。
- **State/Checkpoint/Resume L3**: 47 local roundtrip/resume flow/L3 dispatcher tests passed；cross-host/HITL still deferred。
- **T-SKILL-GOLDEN 已完成并关闭**:Skill System golden 锁定当前实验性本地 dispatcher/lifecycle 行为;当前无 HARDEN_NEXT。
- 其余 L2/L1 模块按 BLOCKED_BY_DECISION / BLOCKED_BY_EXTERNAL / TRACKED_DEBT 管理,无 trigger 不动。
