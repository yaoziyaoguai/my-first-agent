# First Agent Current-Stage Close-out Handoff

**创建日期**: 2026-06-02
**类型**: Current-stage close-out freeze / handoff
**状态**: FROZEN — current-stage closed with caveats

---

## 1. Final Baseline

| 项目 | 值 |
|------|-----|
| Final commit | `60fd71e` |
| 包含 | `2f995b9` (B8 final close-out) + `12675dd` (B1-B8 close-out sweep) |
| HEAD == origin/main | yes |
| Working tree | clean |
| Gemini final verification | pass |
| Codex final verification | pass |

---

## 2. Final Verification

- **Gemini final verification**: pass
- **Codex final verification**: pass
- **No P0/P1/P2 current-stage blocker**
- **No further remediation loop required**

当前阶段的 known caveats 均为 future debt 或 validation-scope caveats，不是 current blockers。

---

## 3. Current-Stage Close-out Decision

**First Agent current-stage close-out: yes-with-caveats.**

Caveats 说明：
- B1-B7 有 validation-scope 或 future-debt caveats（非 current blocker）
- B8 TUI 仍为 fake/local interaction-first MVP（非 real adapter / 非 product-ready）
- TUI default entry NOT ACTIVATED
- 这些 caveats 是下一阶段的起点，不是当前阶段的 bug

---

## 4. Source of Truth

### 当前能力定义

**REAL-EVIDENCE-001..008** 是当前核心能力的唯一 source of truth：

| Evidence ID | Capability | Status |
|-------------|-----------|--------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | accepted-with-caveats |
| REAL-EVIDENCE-002 | Skill selection / SKILL_SELECT | accepted-with-caveats |
| REAL-EVIDENCE-003 | Skill allowed_tools enforcement | accepted-with-caveats |
| REAL-EVIDENCE-004 | Checkpoint save/resume | accepted-with-caveats |
| REAL-EVIDENCE-005 | MCP bridge readiness | accepted-with-caveats |
| REAL-EVIDENCE-006 | SubAgent L1 | accepted-with-caveats |
| REAL-EVIDENCE-007 | MCP runtime-mediated invocation | accepted-with-caveats |
| REAL-EVIDENCE-008 | Advanced scheduler | accepted |

### 架构历史参考

**B1-B8 架构演进里程碑** 是历史架构分类账，不作为当前能力定义。详见 `docs/PROJECT_STATUS.md`。

### 文档层级

1. **`docs/PROJECT_STATUS.md`** — 第一优先读取入口
2. **`docs/handoff/first-agent-current-stage-close-out-2026-06-02.md`** — 本文件，close-out freeze 声明
3. **REAL-EVIDENCE-001..008** 对应的 dogfood/review docs — 证据详情
4. **历史 docs** — 仅作架构上下文参考

**禁止**：从旧 B8 SDD（`docs/design/b8-ts-tui-workbench-sdd.md`）或 Claude stale task list 恢复已关闭的工作。

---

## 5. B7 Status

- **Status**: accepted-with-caveats
- **Current-stage**: closed
- **Key commit**: `3f2f6b2` (Codex independent red-team audit)
- **Delivered**: namespace/events 基础契约、identity model、EventLogWriter contract
- **Future debt**: real multi-instance adapter

B7 不重新打开，除非出现新的 P0 证据。

---

## 6. B8 Status

- **Status**: accepted
- **Key commit**: `2f995b9` (final caveats closed)
- **Delivered**: fake/local Interaction-first Workbench MVP (M1-M8)
  - M1: 3-zone layout (Agent Lens / Interaction View / Context Panel)
  - M2: Agent Lens selection (fake fixture)
  - M3: Fake/local interaction (FakeRuntimeGateway)
  - M4: Context Inspector MVP
  - M5: Controlled Action / Pending Confirmation
  - M6: Multi-instance History Foundation (contracts, no real runtime)
  - M7: Runtime Event Stream (contracts + EventStreamReader, no live tail)
  - M8: Default Entry Readiness checklist
- **TUI default entry**: NOT ACTIVATED
- **Product-ready**: NO
- **Test count**: 412/412 TUI tests PASS, tsc clean
- **Future debt**: real runtime gateway, default entry activation, IME/paste validation

---

## 7. What is Frozen

以下内容在当前阶段**冻结**，不得恢复：

- B1-B8 remediation loops
- B8 feature expansion
- B7 reopening (除非新 P0 证据出现)
- Dashboard / AutoRun / Project Operations / Dynamic Audit resurrection
- TUI default entry activation (需下一阶段用户显式批准)
- Any new Branch Point / architecture change without new SPEC → review → plan cycle

---

## 8. Future Debt

以下为已知 future debt，在下一阶段重新评估优先级：

| # | Debt | 当前状态 | 下一阶段动作 |
|---|------|---------|------------|
| D-01 | B3 SubAgent L2 native loop | L1 accepted-with-caveats, L2 future debt | 独立 SPEC + TDD |
| D-02 | B4 real external MCP server connection | bridge 可信, real flight pending | 需外部 MCP server fixture |
| D-03 | B7 real multi-instance adapter | namespace/events contracts only | 需真实 runtime identity |
| D-04 | B8 real runtime gateway | fake/local MVP only | 连接 core.chat 主路径 |
| D-05 | B8 TUI default entry activation | NOT ACTIVATED | 需用户显式批准 + real gateway |
| D-06 | B8 IME / paste / multiline validation | blocked-ime (R14) | 实际终端验证 |
| D-07 | Legacy Dashboard / AutoRun cleanup | 保留在磁盘，不 import | 确定清理策略后执行 |
| D-08 | Product-ready / release readiness | not product-ready | 需 real adapter E2E 全部通过 |

---

## 9. Next-Stage Candidate Routes

按优先级排列：

| Priority | Route | 前置条件 |
|----------|-------|---------|
| 1 | Real runtime gateway (B8) | core.chat access, user approval |
| 2 | Real multi-instance adapter (B7) | runtime identity infrastructure |
| 3 | MCP real server connection (B4) | external MCP server fixture |
| 4 | SubAgent L2 native loop (B3) | L1 stable, L2 SPEC |
| 5 | TUI productization / default entry (B8) | real gateway + IME validation + user approval |
| 6 | Legacy Dashboard / AutoRun cleanup | 确定不保留后执行 |

---

## 10. Next Session Instructions

**下次继续时必须先读本 handoff。**

关键规则：
1. 不要从旧 B8 SDD（`docs/design/b8-ts-tui-workbench-sdd.md`）恢复工作方向
2. 不要从 Claude stale task list（`#269-#339` 系列）的旧状态继续执行
3. 不要把 future debt 当 current-stage blocker
4. REAL-EVIDENCE-001..008 是当前能力 source of truth
5. B1-B8 是历史架构分类账，不是待办列表
6. **如果进入下一阶段，必须重新写 SPEC → TDD Plan → Review Plan**
7. 不要在当前阶段冻结后继续 B1-B8 remediation
8. 不要激活 TUI default entry（需用户显式批准）
9. 不要恢复 Dashboard / AutoRun / Project Operations / Dynamic Audit

**本 handoff 是下一阶段开发的启动基线。**

---

## 11. Next-Stage Evidence Notes

### 2026-06-02 — Post-Closeout 008 Re-Validation

b3e0863 `validation(evidence): validate scheduler model generated plan`:

- REAL-EVIDENCE-008 v3 re-validation ran post-closeout。
- **ENV_CONCERN**: `config.yaml` provider.api_key 是 `sk-REPLACE_ME` 占位符（SEC-001），模型调用返回 401。
- 008 caveat 已于 2026-05-31 关闭（v3: 14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN），当前 ENV_CONCERN **不重新打开 caveat**。
- 104/104 scheduler focused tests PASS。Malformed safety 4/4 PASS。
- ENV_CONCERN 是环境配置问题，非代码缺陷，非 current-stage blocker。

### 002 Skill Selection Design

REAL-EVIDENCE-002 当前状态: **credible**（12/12 PASS, ab013ed）。已知 scope caveats（prompt-steered, single-skill）为非 blocker 限制。
002 的多语言 skill manifest / 非 prompt-steered activation 设计是 **future debt**，归入下一阶段 D-09，不阻塞 current-stage close-out。
