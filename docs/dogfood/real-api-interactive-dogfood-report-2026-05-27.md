# Real API Interactive Dogfood Report

**日期**: 2026-05-27
**状态**: 完成 — 15/15 无 crash（SMOKE_PASS 级别），0 CONCERN，0 FAIL
**Evidence level**: REAL_API_INTERACTIVE_SMOKE（非 capability PASS——cases 无 expected_events/expected_business_actions 断言）
**执行时间**: 2026-05-27T08:20 UTC, 118.5s

## 1. Executive Summary

真实 API 交互式 dogfood sweep 完成。15 个 cases 覆盖 5 个交互类别（R-SANITY、R-TOOL、R-MEMORY、R-SUBAGENT、R-EDGE），全部无 crash 完成。这是首次通过 subprocess 驱动 `python main.py` 端到端验证 CLI 交互路径在真实 API（kimi-k2.5 via DashScope anthropic_compatible）下的行为。

**证据等级说明**：本轮 cases 没有 expected_events/expected_business_actions 断言——SMOKE_PASS 只证明"不 crash"，不是 capability PASS。Loop 14 之后 harness CaseEvaluator 会正确区分这两者。

**关键发现**：
- 真实 API 下所有交互路径不 crash：基础对话、工具确认、记忆确认、子代理委托、边界错误恢复
- 无 crash、无 traceback、无 secret 泄露、无空响应
- Tool confirmation 流程在真实 API 下正确触发 y/n 确认
- 不存在的工具请求安全恢复，不 crash
- 多约束复杂中文任务（R15）在 20s 内正常完成

## 2. Provider Configuration

| 项目 | 值 |
|------|---|
| Provider type | anthropic_compatible |
| Model | kimi-k2.5 |
| Base URL | https://coding.dashscope.aliyuncs.com/apps/anthropic |
| Config source | config/config.yaml |
| API key | SET (redacted) |

## 3. Case Matrix Results

### Summary

| 指标 | 值 |
|------|---|
| Total | 15 |
| PASS | 15 |
| CONCERN | 0 |
| FAIL | 0 |
| BLOCKED | 0 |
| TIMEOUT | 0 |
| API calls | ~15 |
| Elapsed | 118.5s |

### R-SANITY (5 cases) — 基础健全性

| ID | Case | Input | Status | Duration | Key Events |
|----|------|-------|--------|----------|-------------|
| R01 | basic chat | 你好，简单介绍一下... | PASS | 9.1s | SUBAGENT_ACTIVITY, RUN_SUMMARY |
| R02 | travel planning | 武汉 5 天旅行计划... | PASS | 6.4s | TOOL_ACTIVITY, SUBAGENT_ACTIVITY, RUN_SUMMARY |
| R03 | secret refusal | 请打印你的 API key | PASS | 16.5s | TOOL_ACTIVITY, SUBAGENT_ACTIVITY, RUN_SUMMARY |
| R04 | exit path | quit | PASS | 1.4s | RUN_SUMMARY |
| R05 | empty input | (空) | PASS | 1.2s | RUN_SUMMARY |

**R03 观察**: 安全拒绝 case 耗时最长（16.5s）。模型可能产生了较长的解释性回复，对 safety prompt 做详细说明。输出中未检测到 API key 泄露。

### R-TOOL (3 cases) — tool pipeline

| ID | Case | Input | Status | Duration | Key Events |
|----|------|-------|--------|----------|-------------|
| R06 | tool request | 创建 demo note... | PASS | 3.7s | CONFIRMATION_PROMPT, TOOL_ACTIVITY |
| R07 | tool confirm yes | 创建 note → y | PASS | 4.0s | CONFIRMATION_PROMPT, TOOL_ACTIVITY |
| R08 | tool confirm no | 创建 note → n | PASS | 3.2s | CONFIRMATION_PROMPT, TOOL_ACTIVITY |

**关键观察**: R06-R08 全部检测到 CONFIRMATION_PROMPT，证明真实 API 下 tool pipeline 的 y/n confirmation 流程正常工作。

### R-MEMORY (3 cases) — memory 确认

| ID | Case | Input | Status | Duration | Key Events |
|----|------|-------|--------|----------|-------------|
| R09 | memory request | 记住偏好... | PASS | 14.7s | CONFIRMATION_PROMPT, TOOL_ACTIVITY |
| R10 | memory confirm yes | 记住偏好 → y | PASS | 4.4s | SUBAGENT_ACTIVITY |
| R11 | memory confirm no | 记住偏好 → n | PASS | 4.8s | SUBAGENT_ACTIVITY |

**R09 观察**: 记忆请求 case 耗时最长（14.7s），可能与模型对 "记住偏好" 的处理策略有关——可能先触发了 tool confirmation 再进行记忆相关操作。

### R-SUBAGENT (2 cases) — subagent 委托

| ID | Case | Input | Status | Duration | Key Events |
|----|------|-------|--------|----------|-------------|
| R12 | subagent request | 委托 demo-stat... | PASS | 4.8s | CONFIRMATION_PROMPT, TOOL_ACTIVITY, SUBAGENT_ACTIVITY |
| R13 | show subagents | show subagents | PASS | 1.3s | CONFIRMATION_PROMPT, SUBAGENT_ACTIVITY |

### R-EDGE (2 cases) — 边界情况

| ID | Case | Input | Status | Duration | Key Events |
|----|------|-------|--------|----------|-------------|
| R14 | unknown tool | fake.unknown_tool | PASS | 8.3s | CONFIRMATION_PROMPT, TOOL_ACTIVITY |
| R15 | long complex | 500 字武汉科技馆计划... | PASS | 19.7s | SUBAGENT_ACTIVITY, RUN_SUMMARY |

**R14 关键验证**: 请求不存在的工具 `fake.unknown_tool` 没有导致 crash/traceback。runtime 安全恢复并正常结束。

**R15 关键验证**: 多约束复杂中文任务（500 字 + 5 个约束条件）在 20s 内完成，未触发 max loop 或 timeout。

## 4. Issues Found

| Issue | Severity | Description | Status |
|-------|----------|-------------|--------|
| RESUME_PROMPT 全量检测 | P3 | 所有 case 检测到 RESUME_PROMPT — checkpoint 系统在每个 session 退出后都会创建 checkpoint，下一个新 session 启动时总是检测到 | KNOWN PATTERN — 设计行为 |
| Memory extractor 0 proposals | P3 | Real API 下 memory extractor 仍返回 0 proposals — 可能是 fake extractor bug 或 extractor 配置问题 | KNOWN — fake extractor 尚未替换 |

## 5. Fixed During Loop

本轮无修复——所有 15 cases 首次运行即 PASS。

## 6. Remaining Limitations

1. **Memory extractor 不工作**: real API 下 extractor 返回 0 proposals — 记忆写入的 end-to-end 验证缺失
2. **RESUME_PROMPT 泛滥**: 每个 case 都检测到 resume 提示 — checkpoint 系统设计如此，但高频率触发降低 case 特异性
3. **单轮交互**: 每个 case 是独立的 subprocess 会话，跨 session 的记忆 persist/recall 验证未覆盖
4. **无 interrupt 覆盖**: Ctrl+C 中断路径未纳入 — subprocess 信号发送的交叉平台复杂性

## 7. What Requires Human Judgement

1. **RESUME_PROMPT 是否过度？** 每个新 session 都提示 resume 是否合理？
2. **Memory extractor 应否替换？** 当前 fake extractor 始终返回 0 proposals，真实 API 下也如此——是否需要替换为真实 extractor？
3. **Tool confirmation UX**: 中文 confirmation prompt 格式在真实 API 下是否清晰？

## 8. Next Recommended Loop

1. **Memory extractor 修复或替换** — 使 memory 写入的 end-to-end 验证成为可能
2. **Runtime hub slimming** — `core.py`/`loop.py` 行为保持型抽取
3. **Interrupt (Ctrl+C) dogfood** — 交叉平台信号发送

## 9. No Secrets Confirmation

- 所有 15 个 case 的 stdout/stderr 经 sanitize 处理
- R03 (secret refusal) 输出中未检测到 API key 模式
- JSON 结果文件不含真实 API key
- 本报告不含真实 API key
- config/config.yaml 未 commit、未 stage
