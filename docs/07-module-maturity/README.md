# Module Maturity — Navigation

Post-repair module maturity / hardening 阶段的工作目录。

**当前状态:Module Taxonomy Gate 已通过(`MODULE_TAXONOMY_APPROVED = YES`,Option γ,15 模块)。Module Maturity Audit 已完成。**

- Architecture Repair Mainline 仍 CLOSED(`ACCEPT_WITH_TRACKED_DEBT`)。本目录**不是** active repair queue,不开启 Window 4。
- 本阶段只做文档型审计,不改 code / tests / North Star,不硬化任何模块。
- North Star 是目标模型,不是待办队列;North Star gap ≠ must-fix。

## 文件

| Path | Role | Status |
|---|---|---|
| `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md` | 模块分法 gate 发现 + 决策(D1–D4 / C1–C2)+ 候选 option | current — 已由用户以 Option γ 批准 |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | 15 模块 L0–L4 成熟度审计 + action 分类 + HARDEN_NEXT(1)| current |
| `POST_REPAIR_TRIGGER_REGISTRY.zh.md` | trigger 寄存器 + 激活 playbook("No trigger, no work");每个 blocked/deferred/harden 项的触发条件与开工路径 | current |

## 阅读顺序

1. 先读 `AGENT_MODULE_MATURITY_AUDIT.zh.md`(总表在 §4,逐模块在 §5,下一步在 §7)。
2. taxonomy 决策依据见 `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`。
3. 背景按 `docs/06-audit/README.md` 顺序:retrospective → closure audit → `docs/CAPABILITY_BOUNDARIES.md` → North Star(目标,不是 runtime fact)。

## 关键结论(摘要)

- Mainline 已串通;问题是**模块成熟度不均衡**(L3 骨架/横切簇 + L2 能力簇 + L1 dormant scheduler),且不均衡几乎全是**有意 deferred/blocked**。
- **HARDEN_NEXT 仅 1 个**:Skill System 补 Golden E2E(锁当前实验行为);本轮仅推荐,不执行。
- 其余 L2/L1 模块按 BLOCKED_BY_DECISION / BLOCKED_BY_EXTERNAL / TRACKED_DEBT 管理,无 trigger 不动。
