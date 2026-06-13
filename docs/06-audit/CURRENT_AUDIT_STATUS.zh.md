# Current Audit Status

> **Status: superseded for post-repair navigation.**
> Architecture Repair Mainline is closed. Use docs/06-audit/README.md,
> ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md,
> ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md, and
> docs/CAPABILITY_BOUNDARIES.md for current post-repair orientation. This file
> remains historical source-of-truth cleanup context and is not an active repair
> queue.

历史审计状态入口。post-repair 阶段请先读 [Audit Documents Navigation](README.md)。事实源以 [Project Status](../PROJECT_STATUS.md) 和 [Current Capability Status](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md) 为准。archive docs 不是当前入口。

## 总体结论

Status: **Superseded — repository cleanup / source-of-truth repair history**。

- 当前阶段是 **developer prototype / local development**。
- 当前代码主线是 `main.py → agent/core.py → agent/loop.py`。
- 工具主线是 `ToolRuntimeMediator → tool_executor`；`TOOL_INVOKE` dispatcher path 只保留 evidence-only marker。
- Memory v0、Skill lifecycle、Sub-agent v0 已有当前实现和测试保护网，清理时不得破坏。

## 当前审计边界

| Area | 状态 | 风险 |
|---|---|---|
| Runtime/Core/Loop | preserve | 不引入第二 runtime，不做大重构 |
| Tool/MCP boundary | preserve | 不恢复 direct execution；MCP 走普通 tool 管线 |
| Memory v0 | preserve | 不新增 raw write / auto-adoption |
| Skill lifecycle | preserve | checkpoint metadata 不保存 raw skill body |
| Sub-agent v0 | preserve | child 不直接执行工具/MCP/Memory；parent runtime 负责裁决 |
| Legacy L1/L2 | frozen / compatibility only | 不恢复为当前主线 |
| Documentation | cleanup target | 删除旧计划、旧审计和错误方向上下文 |

## 冻结项

- **FakeProvider 冻结**：FakeProvider 只能作为 deterministic test double，不继续扩成 fake planner / fake reasoning engine。
- **Memory Consolidation pipeline 冻结**：Consolidation 相关路径保留为 deferred / contract evidence，不作为当前推进目标。
- 旧 TUI/B7/B8 closeout、旧 evidence report、旧 archive docs 不作为当前行动源。

## 当前可推送性

cleanup/source-of-truth 文档改动可以在本地检查通过后提交。不要 push，除非用户明确授权。
