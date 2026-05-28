# Real Evidence / Dogfood / Real API Validation Debt

**创建日期**: 2026-05-28
**最后更新**: 2026-05-28 (Loop 2.2b)

---

## 为什么存在

当前项目很多子系统已经通过 L2（contract tests via `dispatcher.route()`）和 L3（contract
tests via `dispatcher.route_from_runtime_loop()`）验证，但缺少真实 CLI / real core loop
/ real API / real dogfood 的端到端验证。

## 为什么不阻塞当前 loop

当前阶段优先完成 unified runtime path 和 subsystem main-path integration。把真实验证需求
集中收敛到本文档，避免每个 loop 被手工 dogfood 打断节奏。

## 不能 overclaim

缺少真实 dogfood 验证的能力**不能**标为 READY 或 COMPLETED，只能标为 PARTIAL 或
"code path complete, real validation pending"。在 PROJECT_STATUS 中对应行必须明确引用
本文档 ID。

## 后续处理原则

- 所有审计文档（`docs/audits/`）、dogfood 报告（`docs/dogfood/`）中出现的真实 API
  测试、真实 dogfood、real E2E、外部服务验证，都统一登记到本文档
- 最后集中处理（一个专门的 validation convergence loop），而非零散逐个验证
- 新的 capability loop 完成后，如果缺真实 dogfood，登记到本文档而不是把它写成
  loop 本身的 blocker

---

## Debt Items

### REAL-EVIDENCE-001

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.1 / commit 480da7e |
| **Capability** | Explicit Memory Main-Path Completion |
| **Missing evidence** | real core loop dogfood E2E |
| **Required validation** | 启动真实 chat loop；输入 `/forget` 或"忘记"命令；验证 dispatcher-mediated MEMORY_FORGET path；验证 retain/recall/forget 使用共享 store；验证用户可见结果与 durable evidence 一致 |
| **Current evidence** | 5 L2 MemoryForget contract tests pass；5 L3 shared-store contract tests pass；65 focused tests pass |
| **Status** | pending real dogfood |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-002

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2 / commit 749ad06 |
| **Capability** | Skill Activation — real model SKILL_SELECT tool call |
| **Missing evidence** | 真实模型（非 FakeProvider）通过 tool call 触发 SKILL_SELECT dispatch |
| **Required validation** | 使用真实 LLM provider 启动 chat；发送需要 skill 的任务；验证模型输出了 skill.select tool call；验证 dispatcher action_log 包含 SKILL_SELECT event；验证下一轮 system prompt 包含 [Active Skill Instructions] |
| **Current evidence** | FakeProvider 路径通过 turn-end hook 自动选择 skill；13 L2 skill bridge tests pass；3 L3 skill tests pass |
| **Status** | pending real model tool call |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-003

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2b |
| **Capability** | Skill allowed_tools enforcement — real dogfood E2E |
| **Missing evidence** | 真实 core loop 中 skill allowed_tools 约束工具执行的端到端验证 |
| **Required validation** | 启动真实 chat loop；激活一个声明了 allowed_tools 的 skill；验证在该 skill 激活期间，非允许工具被真实拦截；验证拦截日志和用户可见消息反映 skill constraint reject；验证 skill 取消激活后工具恢复正常 |
| **Current evidence** | 15 L2 skill tool enforcement contract tests pass；ToolGateHandler 检查 skill_allowed_tools payload；ToolRuntimeMediator 传递 skill_allowed_tools；被 block 的工具不进入 execute_single_tool |
| **Status** | pending real dogfood |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

## 登记模板

新 debt item 按以下格式追加：

```markdown
### REAL-EVIDENCE-NNN

| 字段 | 值 |
|------|-----|
| **Source** | Loop X.Y / commit <hash> |
| **Capability** | <capability name> |
| **Missing evidence** | <简要描述缺什么> |
| **Required validation** | <具体验证步骤> |
| **Current evidence** | <已有测试/dogfood/contract 证据> |
| **Status** | pending real dogfood / pending real API / pending external service |
| **Blocking current code loop** | yes / no |
| **Blocking READY claim** | yes / no |
```
