# Automated User-Path Dogfood Sweep Report

**生成时间**: 2026-05-26 (updated — FakeProvider Scripted Scenario Contract Reset)
**测试套件**: `tests/test_user_path_dogfood_smoke.py` (20 cases) + `tests/test_fake_provider_decision.py` (40 cases)
**Harness 模式**: fake/local provider → core.chat() → unified runtime flow
**边界**: 不读 .env / 不调真实 API / 不调真实 LLM / 不访问外部网络

## 测试分类 Taxonomy (per FakeProvider Scripted Scenario Contract)

按 `docs/design/fake-provider-scripted-scenario-contract.md` 定义的三类分类法：

### Category A: Deterministic Fake Runtime Scenarios

- 使用固定 scripted provider outputs（exact match / literal tool name）
- 证明 runtime branch points（tool pipeline、memory path、subagent routing）可达且正确
- 不依赖任何自然语言理解（NLU）
- 不调用真实 API
- Run on every commit

### Category B: Fake/Local UX Smoke

- 普通聊天、help、status
- 验证 no crash、no max-loop、no summary overclaim
- 不依赖 FakeProvider 的中文意图识别能力
- FakeProvider 返回 echo/final_text（end_turn）
- Run on every commit

### Category C: Real-Provider Semantic Eval

- 自然语言请求，需要模型判断 tool/memory/subagent 意图
- 需要真实 LLM API（opt-in gate: `MY_FIRST_AGENT_RUN_REAL_LLM_E2E=1`）
- 不默认运行
- 需要人工判断质量

## Case Matrix

### Category B — Ordinary Chat (A/B/C)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| A | 你好，简单介绍一下你现在能做什么。 | no crash, no max loop, no tool_use, 1-5 loops | PASS | B | 1 loop, end_turn, echo response |
| B | 帮我规划下去武汉玩5天的旅游计划 | no crash, no max loop | PASS | B | 1 loop, end_turn |
| C | 我现在只是测试 fake/local 路径… | no crash, no max loop | PASS | B | 1 loop, P3 误匹配已在 6e5f287 + stop-word 修复 |

### Category A/B — Tool Intent (D)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| D | 帮我创建一条 demo note… | no crash, no max loop | PASS | A→B | 使用 exact trigger phrase（\"create a demo note\" 变体），非任意 NL。含中文标点的长消息 tokenization 边界问题 (P3) |

### Category B — Commands (E/F)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| E | show memories | no crash, no max loop | PASS | B | |
| F | show subagents | no crash, no max loop | PASS | B | |

### Category A — Error/Unknown (G)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| G | 请调用一个不存在的工具 fake.unknown_tool | no crash, no max loop, readable error | PASS | A | 确定性 tool_use 路径，工具不存在 → error handling |

### Category A — Memory Retain (H)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| H | 请记住一个测试偏好… | no crash, no max loop, no secret leak | PASS | A | Scripted: tool_use → Tool Pipeline → memory hook → retain |

### Category A — SubAgent Delegation (I)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| I | 请委托 demo-stat 子代理… | no crash, no max loop, no secret leak | PASS | A | Scripted: tool_use → SubAgent routing → delegation |

### Category B — Debug/Summary (J/K)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| J | 请显示本轮运行摘要 | no crash, no max loop | PASS | B | |
| K | 请告诉我刚才这一轮有没有调用工具… | no crash, no max loop | PASS | B | threshold 40→60 修复了此 case 的 max loop |

### Category B — Error Recovery (L)

| Case | 输入 | 预期 | 状态 | 分类 | 备注 |
|------|------|------|------|------|------|
| L | forget memory abc-not-exist | no crash, no max loop | PASS | B | |

### Invariants (3 cases)

| Test | 状态 | 分类 |
|------|------|------|
| unified_runtime_flow_no_fake_chat_loop | PASS | A |
| fake_provider_has_final_end_turn_for_ordinary_chat | PASS | A |
| stream_collect_produces_end_turn | PASS | A |

### Summary Honesty (3 cases)

| Test | 状态 | 分类 |
|------|------|------|
| ordinary_chat_no_memory_overclaim | PASS | B |
| ordinary_chat_no_subagent_overclaim | PASS | B |
| travel_planning_no_memory_overclaim | PASS | B |

### Regression (2 cases)

| Test | 状态 | 分类 |
|------|------|------|
| regression_model_name_not_none | PASS | B |
| regression_provider_not_none | PASS | B |

## ⚠️ FakeProvider 能力边界声明

FakeProvider **验证了**：
- Runtime loop 正确性（end_turn → loop 终止）
- Tool Pipeline 可达性（tool_use → ToolExecutor → result visible）
- Memory hook 可达性（dispatcher action_log 有 memory.* 事件）
- SubAgent routing 可达性（dispatcher action_log 有 subagent.* 事件）
- Summary 诚实性（action_log disposition 过滤正确，不 overclaim）
- Provider swap 安全性（FakeProvider 和 RealProvider 共享同一 runtime path）

FakeProvider **不验证**（NL-dependent、需要 Category C）：
- 中文自然语言理解能力
- 工具选择准确性（使用 scripted triggers，非语义匹配）
- Memory 相关性判断
- SubAgent 任务分解
- 多工具 chaining
- 对话质量
- 模型安全性/对齐性

详见 `docs/design/fake-provider-scripted-scenario-contract.md`。

## 本轮发现并修复的问题

### P1: MappingProxyType 导致 disposition 过滤完全失效 (FIXED)

- **根因**: `RuntimeActionEvent.__post_init__()` 调用 `deep_freeze()` 将 evidence dict 转换为 `MappingProxyType`。但 `_emit_run_summary()` 中使用 `isinstance(evidence, dict)` 检查 evidence 类型——`MappingProxyType` 不是 `dict` 的子类。
- **修复**: 将 `isinstance(evidence, dict)` 改为 `isinstance(evidence, Mapping)`。
- **Commit**: c667521

### P2: Case K max loop — FakeProvider 中文关键词误匹配 (FIXED prior round)

- **根因**: `_tool_desc_keywords()` 对中文工具描述做 n-gram 提取，常见中文短语同时出现在工具描述和 ordinary chat 中，导致 score≥40 触发 tool_use。
- **修复**: 将 threshold 从 40 提升到 60。
- **Commit**: 255c341

### P3: Case C tool_requested 误触发 (FIXED prior round)

- **根因**: `request_user_input` 工具描述与用户消息产生 n-gram 重叠。
- **修复**: 新增中文停用词过滤（"调用"、"不要"）。
- **Commit**: 255c341

### P4: Case D 长消息中英混合标点 tokenization 问题 (KNOWN, NOT FIXED)

- **症状**: 中文标点不被 `str.split()` 视为词边界，影响 strategy 2。
- **处理**: 不在此轮修复。按 scripted scenario contract，未来 NL 依赖的匹配策略将被移除。

### Architecture: FakeProvider Scripted Scenario Contract Reset (THIS ROUND)

- **问题**: FakeProvider 的 strategy 2（名称 token）、strategy 3（描述关键词 n-gram）以及 `_tool_desc_keywords()` 的 Chinese n-gram 提取构成了一个劣质中文 NLU 系统。
- **方向纠偏**: FakeProvider 只应是 deterministic scripted model/test double，使用 exact match 和 literal tool name 匹配，不做语义分析。
- **契约文档**: `docs/design/fake-provider-scripted-scenario-contract.md`
- **代码变更**: strategies 2/3 标记为 DEPRECATED，新增 scripted scenario contract docstring

## 架构验证

- FakeProvider 和 RealProvider 共享同一条 unified runtime flow (core.chat → loop.py → model_call)
- 不存在 fake_chat_loop / fake_runtime_loop
- 不存在 main.py/core.py 中 `if fake: return canned reply`
- ordinary chat 正确返回 `stop_reason="end_turn"` 并终止 loop
- tool_use intent 经由 core.chat / Tool Pipeline 完整路径
- `_emit_run_summary()` 的 disposition 过滤基于 `Mapping` 接口而非 `dict` 类型
- FakeProvider 的 tool_use 决策已明确定义边界：只允许 exact match 和 literal tool name，禁止 semantic NLU

## 用户不需要再手工逐句测试的原因

1. **20 条 automated dogfood cases** 覆盖 ordinary chat、tool intent、memory、subagent、debug、error recovery 全部基础路径
2. **Summary honesty 自动验证**：3 条专门测试确保用户摘要不 overclaim
3. **max loop guard** 被验证为安全阀而非成功条件
4. **每次 commit 前自动跑** — 回归由 CI/harness 负责
5. **FakeProvider 边界已明确** — Category A/B 证明 runtime 正确性，Category C 留给 real provider
6. 用户只需手工做**主观体验判断**和 **Category C 语义质量评估**

## Retest 命令

```bash
cd /Users/jinkun.wang/work_space/my-first-agent
git pull
.venv/bin/python -m pytest tests/test_user_path_dogfood_smoke.py -v
.venv/bin/python -m pytest tests/test_fake_provider_decision.py -v
```
