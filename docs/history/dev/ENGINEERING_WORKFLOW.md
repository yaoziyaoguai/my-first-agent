# Engineering Workflow

my-first-agent 项目工程流程。本文档固定 SDD → TDD → Implementation → Review → Debug 的迭代 loop 纪律，包括 review gate、回退规则、重试上限、升级条件和禁止模式。

Status: active
Date: 2026-05-22

---

## 1. 大 Loop：完整工程闭环

工程流程是迭代 loop，不是线性瀑布流。每个阶段完成后必须 review，发现问题时按证据回退到对应上游阶段，不允许在下游打补丁掩盖上游错误。

```text
Unified Runtime Flow Contract / 项目宪法          ← 最高上游
  → SDD / SPEC                                     ← 规格层
    → SPEC Review                                  ← review gate
      → TDD / Test Plan                           ← 测试设计层
        → Test Plan Review                        ← review gate
          → Implementation Plan                    ← 执行规划层
            → Plan Review                         ← review gate
              → Implementation                    ← 执行层
                → Implementation Audit            ← review gate
                  → Debug / Remediation           ← 修复层
                    → 复审                        ← 最终 gate
```

任何阶段都可以回退到上游，不可跳过 review gate。

大 loop 是完整流程的上界，不是所有任务的强制全路径。低风险改动（docs-only、typo、单文件小修）可跳过前半段，从 Implementation 或 Gate 直接进入。跳过不是绕过工程纪律，而是基于风险分级选择更轻的入口——即便跳过，也必须满足对应 gate（git diff --check、build、专项测试、exit code = 0）。

---

## 2. 小 Loop：阶段内迭代

每个阶段内部有自己的回退循环：

| 阶段 | 小 Loop | 回退触发条件 |
|------|---------|-------------|
| SDD / SPEC | 写 → 审查 → 修正 → 再审查 | SPEC Review 发现 branch point 判断错误、scope 不清、需求矛盾 |
| TDD / Test Plan | 设计测试 → 审查 → 修正 → 再审查 | 测试覆盖不足、分类边界错误、负例缺失 |
| Implementation Plan | 规划 → 审查 → 修正 → 再审查 | 执行路径与 contract 不一致、包含禁止事项 |
| Implementation | 实现 → 自测 → 对照 plan 检查 | 实现偏离 plan、发现规格缺失、越界改动 |
| Review / Audit | 审查 → 发现问题 → 修正 → 再审查 | 实现与 plan 不一致、引入越界改动 |
| Debug | 查证据 → 定位根因 → 修正 → 回归验证 | 根因在设计层而非代码层、需要改上游文档 |

---

## 3. Review Gate 清单

以下文档生成后必须经过独立 review/audit：

| 文档类型 | Review 时机 | 说明 |
|---------|------------|------|
| SPEC / SDD 文档 | 写完后立即 review | 验证 branch point 判断、capability milestone 判断 |
| TDD / 测试计划文档 | 写完后立即 review | 验证测试覆盖 branch behavior、负例、分类边界 |
| Implementation Plan | 写完后立即 review | 验证执行路径与 contract 一致，不含禁止事项 |
| implementation notes | 完成后 audit | 验证实际改动与 plan 一致 |
| remediation plan | 写完后立即 review | 验证根因分析和回退路径正确 |
| 重要架构文档 | 写完后立即 review | 验证与 Unified Runtime Flow Contract 一致 |

Review 不是只发生在实现完成之后。每个阶段的输出进入下一阶段前必须经过 review gate。

---

## 4. 按证据回退规则

发现问题时必须向上游追溯根因，不允许在下游打补丁：

| 发现位置 | 根因在上游 | 回退目标 |
|---------|-----------|---------|
| Implementation | 实现逻辑错误 | 回 Implementation |
| Implementation | 测试设计未覆盖该路径 | 回 TDD / Test Plan |
| Implementation | 实现计划遗漏边界条件 | 回 Implementation Plan |
| Implementation | 规格对 branch point 判断错误 | 回 SDD / SPEC |
| Debug / Remediation | 根因是 validation/evidence 叙事错误 | 回文档和分类契约 |
| Debug / Remediation | 根因是 branch point 不存在或定义错误 | 回 Unified Runtime Flow Contract |
| Review 阶段 | 发现上游文档缺陷 | 回对应上游阶段 |

"只在出问题的地方修"等价于积累技术债。必须回退到根因所在的最上游阶段。

回退不是惩罚。回退是正常的工程纠偏行为。不回退才是异常。

---

## 5. 回退有上限：重试与升级

### 5.1 重试上限

同一问题在同一阶段来回修 **最多 2 次**。第 3 次尝试前必须停止并升级。

这条规则不削弱正常的小修复（typo、lint、格式、单行修正），只防止以下无限振荡：

- plan ↔ review 来回拉锯
- test ↔ implementation 反复推翻
- debug ↔ patch 试错循环

### 5.2 升级条件

触发升级的场景：

| 场景 | 说明 |
|------|------|
| 重试超限 | 同一问题在同一阶段已修 2 次仍未通过 gate |
| 架构分歧 | plan 和实现之间的分歧无法通过现有规则解决 |
| 安全/隐私 | 发现的问题涉及安全、隐私、数据完整性 |
| 产品判断 | 需求取舍、优先级冲突、scope 变更 |
| 外部依赖 | 需要真实 secret、真实 API key、真实外部服务调用确认 |
| 流程卡住 | Agent 无法判断该回到哪一步 |

### 5.3 升级格式

升级时必须说明：

- **已尝试的路径** — 两次尝试分别做了什么
- **失败证据** — 每次尝试的具体失败输出或矛盾点
- **当前判断** — 根因可能在哪里
- **需要用户决策的问题** — 优先给出明确的二选一或多选一；如果问题尚未收敛到可选项，必须给出开放式澄清问题、已知约束、当前判断和推荐的澄清方向

不允许在无证据的情况下说"搞不定"就升级。也不允许在第三次继续无证据尝试。

---

## 6. 每项任务的前置判断

所有 coding agent / Claude Code / Codex 任务开始前，必须先回答：

```text
1. 当前任务属于哪个 unified runtime flow branch point？
2. 该 branch point 是否已在 Contract 中定义？
3. 如果已存在：
   - 只做 branch behavior 的 SDD → TDD → 实现 → 测试
   - 不新增 capability milestone
   - 不新增 Anchor
4. 如果不存在：
   - 先回到 Contract / SDD 阶段设计 branch point
   - 不跳过设计直接实现
```

---

## 7. 回退记录

每次发生跨阶段回退，必须记录：

- **回退到哪一步** — SPEC/Plan、TDD、Implementation、Review 中的哪一个
- **为什么回退** — 发现了什么具体证据或矛盾
- **修改了什么** — 哪个上游文档、测试文件、或实现代码被修改
- **如何验证修正** — 回退修正后跑了什么检查确认问题已解决

记录方式：
- 关键回退写入 commit message body
- 跨多阶段的重大回退同时写入 implementation notes
- 不要求每次小修正都写长篇记录，但跨阶段回退不得遗漏

---

## 8. 明确禁止的旧模式

以下做法已被 remediation 纠正，不得复用：

- 临时 prompt 补红线（应用 Contract 而非绕过）
- Anchor 叙事无限拆分（使用 branch behavior 而非新 Anchor）
- validation harness 进入 core runtime（验证只能调用 core.chat 并收集 evidence，不能成为第二 runtime）
- fake/real 两套路径（fake/real 共享同一业务流，仅配置层不同）
- 子系统 direct call 冒充 E2E（direct call 必须降级）
- 只在最后做 review（review gate 必须在每个阶段之后）
- 在下游打补丁掩盖上游错误（必须回到根因所在阶段修正）
- 无证据回退（回退必须有具体 log、测试失败、文档矛盾或 review 发现支撑）
- 超限重试不升级（同一问题在同一阶段修 2 次仍失败，第 3 次前必须升级）

---

## 参考

- [Unified Runtime Flow Contract](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) — 项目宪法，定义 runtime architecture、branch points、classification rules
- [AGENTS.md](../../AGENTS.md) — 安全边界、架构规则、TDD 和质量 gate
