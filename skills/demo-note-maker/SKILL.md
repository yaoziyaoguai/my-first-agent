---
name: demo-note-maker
description: 围绕 demo 工具创建本地任务笔记。当用户要求"写笔记"、"记录任务"、"创建 demo note"、"make a note"时匹配。
version: 0.1.0
status: active
risk_level: low
allowed_tools:
  - demo.echo_task_summary
  - demo.write_demo_note
tags:
  - demo
  - note
  - local
memory_scope: none
---

# Demo Note Maker

围绕 First Agent 本地 demo 工具的任务笔记创建 skill。

## 行为

1. 用 `demo.echo_task_summary` 获取当前任务摘要
2. 将摘要与用户输入组合
3. 用 `demo.write_demo_note` 写入受控的 workspace/demo/ 目录

## 约束

- 零网络调用
- 零真实 API
- 零私人数据读取
- 只在 workspace/demo/ 内写入
- 所有工具调用走完整 Tool pipeline (TOOL_GATE → TOOL_INVOKE → TOOL_RESULT)
