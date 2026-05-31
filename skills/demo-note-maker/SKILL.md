---
name: demo-note-maker
description: 围绕 demo 工具创建本地任务笔记。当用户要求"写笔记"、"记录任务"、"待办"、"备忘"、"记个笔记"、"创建 demo note"、"make a note"时匹配。
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
# ── Plan 3 结构化检索字段 ──
# triggers: 精确/子串匹配权重最高的触发词（中英文双语）
triggers:
  - write note
  - make a note
  - 写笔记
  - 记笔记
  - 做笔记
  - 创建笔记
  - 记录任务
  - 待办
  - 备忘
  - 写个笔记
  - 记个笔记
# aliases: 别名匹配（中英文变体）
aliases:
  - note
  - notes
  - 笔记
  - 记事
  - 记事本
  - task note
  - demo note
# negative_triggers: 命中则排除此 skill
negative_triggers:
  - 数学
  - 计算
  - 解方程
  - 微积分
  - 天气
  - 翻译
  - 查天气
  - 算一下
  - 求值
  - evaluate
  - what is the weather
# when_to_use: 适合使用的场景
when_to_use: "用户想要写笔记、记录任务、创建待办或备忘时"
# when_not_to_use: 不适合使用的场景
when_not_to_use: "用户询问数学、计算、天气、翻译等无关任务时"
# locale: 主要语言区域
locale: zh-CN
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
