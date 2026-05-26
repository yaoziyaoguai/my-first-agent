# Real API Full Dogfood Remediation Plan

**日期**: 2026-05-26
**状态**: draft
**来源**: real-api-full-dogfood-sweep-report-2026-05-26

## 问题分组

### 1. Runtime 文本返回值 (P3 — ISSUE-002)

**问题**: G2 (Safety: 拒绝打印 API key) 通过 core.chat() 调用后返回空字符串。
模型确实被调用了 (4.2s elapsed)，3 个 RuntimeEvent 被触发，但最终文本为空。

**影响**: 用户看不到模型的拒绝回复。在真实 CLI 使用中这可能意味着某些模型响应被静默丢弃。

**排查方向**:
1. 跟踪 `agent/loop.py::run_main_loop()` 的返回值构建逻辑
2. 检查 turn-end summary 是否在特定条件下覆盖了模型文本输出
3. 检查 streaming event 是否被 runtime_event callback 正确转换为文本
4. 验证 `_call_model()` → response → text extraction 链路

**建议修复**: 在 loop.py 中添加 focused test，覆盖 "模型返回纯文本拒绝" 场景，确保文本经过完整链路到达 chat() 返回值。

**优先级**: 低 (P3)。不影响真实 API 基本使用，但可能影响用户体验。

### 2. Interactive Confirmation Harness (P3 — ISSUE-001)

**问题**: C1 (Memory: 记住偏好) 返回空字符串——memory confirmation 等待 y/n 交互。
当前 harness 不支持多轮对话，无法完成 confirmation → retain → store 的完整链路。

**影响**: Memory 写入功能无法通过自动化 dogfood 验证。

**解决方案**:
1. **方案 A (推荐)**: 新增 `scripts/interactive_dogfood.py` —— 通过 subprocess + stdin/stdout 模拟 CLI 交互式会话
2. **方案 B**: 在 harness 中增加 `--interactive` flag，接收预定义的用户回复序列
3. **方案 C**: 直接从代码层调用 confirmation handler 完成自动化验证（会绕过 checkpoint/resume 路径）

**推荐方案 A**，因为交互式 dogfood 同时覆盖 checkpoint/resume 和 tool confirmation 场景。

**优先级**: 低 (P3)。Memory 写入的正确性已有 focused unit test 覆盖。

### 3. Provider Identity (P3)

**问题**: A1 中 Kimi K2.5 自称 "Claude"——兼容模式 adapter 未注入品牌 identity。

**影响**: 用户可能困惑当前使用的是哪个模型。不影响功能，但影响透明度。

**建议修复**: 在 runtime system prompt 中注入 `provider_name` / `model_name` 字段，
让模型知道自己的身份。修改位置：`agent/core.py` 的 `refresh_runtime_system_prompt()`。

**优先级**: 低 (P3)。用户可通过 status/provider-diagnostics 确认模型身份。

### 4. Product Context (P3)

**问题**: I1 (help) 和 I7 (配置路径) 返回通用 AI 助手回答，未指向 First Agent 项目特定信息。

**影响**: 新用户无法通过对话获取 First Agent 的 help/status/config 信息。

**建议修复**: 在 system prompt 中注入 First Agent 项目简介，包括：
- 项目名称和定位
- config/config.yaml 配置路径
- 可用命令 (help, status, provider-diagnostics, show memories, forget, show subagents)

**优先级**: 低 (P3)。这不影响功能，但影响产品 onboarding。

### 5. Untested Capabilities

以下能力需要交互式 dogfood 支持：

| Capability | 需要交互类型 | 优先级 |
|------------|-------------|--------|
| E. Checkpoint / Resume | Ctrl+C + resume y/n | P2 |
| F. Streaming display | 逐 token 观察 | P2 |
| Tool confirmation (y/n) | 用户确认/拒绝 | P2 |
| Memory confirmation (y/n) | 用户确认/拒绝 | P2 |
| Plan mode confirmation | /plan → y/n | P2 |
| Multi-turn context | 多轮对话 | P3 |

**建议**: 在 `scripts/interactive_dogfood.py` 建成后，一次性覆盖以上所有场景。

## 已修复项目

本轮 dogfood 未触发需要自动修复的代码级问题。

## 不建议修复的项目

无。

## 下一步建议

1. **立即**: 修复 G2 空响应根因 (loop.py 文本返回值)
2. **本周**: 构建交互式 dogfood harness
3. **本周**: 注入 provider identity 和 product context 到 system prompt
4. **Week 2**: 执行完整交互式 dogfood (E/F + confirmation flows)

---
*Generated from real-api-full-dogfood-sweep-report-2026-05-26*
