# Module Maturity — Navigation

Post-repair module maturity / hardening 阶段的工作目录。

**当前状态:Module Taxonomy Gate 未通过(`MODULE_TAXONOMY_APPROVED = NO`)。**

- Architecture Repair Mainline 仍 CLOSED(`ACCEPT_WITH_TRACKED_DEBT`)。本目录**不是** active repair queue,不开启 Window 4。
- Module Maturity Audit **尚未开始**:在 taxonomy 被用户批准前,不创建 `AGENT_MODULE_MATURITY_AUDIT.zh.md`。

## 文件

| Path | Role | Status |
|---|---|---|
| `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md` | 模块分法 gate 发现 + 需用户拍板的决策(D1–D6)+ 候选 option | current — 待用户答复 |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | 逐模块 L0–L4 成熟度审计 + harden-next 推荐 | **not created**(taxonomy 批准后才生成) |

## 阅读顺序

1. 先读 `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`。
2. 背景按 `docs/06-audit/README.md` 指定顺序:retrospective → closure audit → `docs/CAPABILITY_BOUNDARIES.md` → North Star(目标,不是 runtime fact)。

## 原则

North Star 是目标模型,不是待办队列;North Star gap ≠ must-fix。本目录只做文档型审计,不改 code / tests / North Star。
