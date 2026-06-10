# First Agent Overview

这篇文档解决什么问题：系统性介绍 First Agent 当前架构，让读者理解 Runtime、ToolRegistry、Memory、Skill、SubAgent、Checkpoint、Confirmation 和 CLI/TUI 的关系。

不解决什么问题：不提供逐行代码说明，不替代 canonical RFC，不描述未获批准的未来实现。

推荐读者：新开发者、架构审计者、Coding Agent。

## First Agent 是什么

First Agent 是一个本地优先（local-first）的 Agent Runtime 项目。它关注的是 Agent 运行时边界，而不是堆叠更多模型或工具。

核心设计判断：

- Parent Agent Runtime 拥有唯一主循环。
- ToolRegistry 是工具能力和风险的 authority。
- Memory Governance 是所有长期记忆写入的 authority。
- Skill System 是可复用 instruction/resource package，不是工具执行绕行路径。
- SubAgent System 是 parent-controlled delegation，不是第二套 Agent loop。
- Checkpoint 是恢复边界，不是任意状态转储。
- Confirmation / Ask User 是人类控制边界。
- CLI/TUI 只是 adapter 和 presentation。

## 系统组成

### Runtime / Core / Loop

`agent/core.py` 保持兼容入口和 runtime hub，`agent/loop.py` 承载主循环编排。当前仍有 hub 风险，但已有 architecture boundary tests 固定 import、checkpoint ownership 和 state mutation owner，后续瘦身必须行为中性。

### ToolRegistry / ToolExecutor

`agent/tool_registry.py` 保存工具定义、capability、risk、output policy、confirmation policy。`agent/tool_executor.py` 执行模型发出的单次 tool_use，并负责 tool_result、pending confirmation、checkpoint 和 audit 事件。

Skill/SubAgent 只能请求或声明工具上限，不能直接执行工具。

### Memory

Memory 采用 filesystem-first 方向：Markdown memory store 是 source of truth，index 是 derived cache。Memory 写入必须经过 governance，支持 explicit retain、interactive confirmation、pending review、consolidation / emergence foundation。禁止 silent retain 和 auto approve。

### Skill System

正式命名空间是 `agent/skill_system/`。Skill 是 filesystem-first package，默认只暴露 metadata，只有被选中时才加载 body，references/scripts/templates/tests 仍需按需加载。`agent/skills/` 是 tombstone，`agent/legacy_skills/` 只作历史材料。

### SubAgent System

正式命名空间是 `agent/subagent_system/`。当前只实现 L0 safe-local / deterministic baseline。SubAgent request/context/result/adjudication/trace 都是结构化 contract。真实 LLM、tool-requesting、sandbox、worktree、parallel multi-subagent 都是 gated/future。

### Checkpoint / Resume

`agent/checkpoint.py` 保存可恢复的 task/memory/conversation 摘要，并截断大型 tool_result。Skill/SubAgent 只保存安全 summary/correlation，不保存完整 body、大 artifact 或 secret。

### Confirmation / Ask User

高风险工具、Memory 写入、SubAgent 不确定结果等都必须通过 Parent Runtime 的 confirmation / ask-user 边界。UI 只展示问题和选择，不拥有决策。

### CLI / TUI

`main.py`、`agent/cli/`、`agent/input_backends/` 是输入输出 adapter。Textual backend 可选懒加载；simple CLI 是 fallback。它们不写 Memory、不执行工具、不保存 checkpoint、不复制 Agent loop。

## 当前健康结论

全局审计未发现 P0/P1/P2。主要 P3 风险是长期维护层面的：`core.py` 仍是 runtime hub，历史文档过多且入口混乱。代码主线健康，文档入口已通过本轮中文重构收口。
