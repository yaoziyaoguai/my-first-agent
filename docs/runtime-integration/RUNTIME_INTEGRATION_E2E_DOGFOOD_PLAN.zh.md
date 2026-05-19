# Runtime Integration / Runtime Action Harness — E2E Dogfood Plan

> 状态：验证计划（不包含实现代码）
> 关联文档：RFC、SDD、TDD、Implementation Loop、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 0. 核心变更：从 "RuntimeActionEvent" 到 "Module Invocation Proof"

### 前一版 E2E Dogfood 的问题

| 问题 | 影响 |
|------|------|
| 6/9 scenario 是 direct subsystem invocation，未经过 `core.chat()` | 验证的是 API 正确性，不是 runtime 集成 |
| E08（full combined）的 pass 条件仅检查 "模型输出文本是否提到了能力关键词" | "提到" ≠ "触发"，无法区分 LLM 的 text generation 和 actual system invocation |
| capability matrix 命名 mismatch | 展示层 bug，掩盖了真实的 coverage gap |
| 没有 RuntimeAction event 抽象 | 无法精确验证"哪个能力被触发、结果如何" |

### 审计发现的新问题（本轮修复）

| 问题 | 严重度 | 修复 |
|------|--------|------|
| RuntimeActionEvent 可能变成新的自欺层——没有 module invocation proof | P1 | 所有 pass 条件增加 module_invoked=true 要求 |
| E01 使用 `bash` 作为 allowed tool，违反 non-goal | P1 | 替换为 `fake.list_directory` + 项目真实 read tool |
| Memory hook 只在 tool 后触发，E04 对话场景无法触发 | P1 | 改为 turn-end hook |
| Streaming E07 未处理 unsupported provider | P2 | 增加 provider_supports_streaming 分支 |
| 文档使用不存在的 tool name（bash/write/read/grep） | P2 | 引入 Tool Alias Policy，区分 generic capability 和 actual tool name |

### 本轮的解决方法

- **所有 pass 条件基于 module invocation proof**：必须同时满足 RuntimeActionEvent + module_invoked=true + handler_name + target_module
- **"模型文本提到 X" 不算任何级别的 evidence**
- **RuntimeActionEvent 不是充分证据**——它是"收据"，module invocation proof 才是"证据"
- **禁止使用 bash/shell/run_shell**——假 tool 用 `fake.` 前缀
- **Memory 场景不依赖 tool call**——turn-end hook 在任何 turn 后触发

---

## 1. Scenario 设计

### 设计原则

1. 每个 scenario 对应一个 Track 的 RuntimeAction path
2. 每个 scenario 通过 `core.chat()` + real LLM 执行
3. 每个 scenario 的 pass 条件包含 module invocation proof（SDD R.6 Action Evidence Contract）
4. E08 是 full combined scenario，要求多个 action_type + module invocation proof
5. 所有 allowed_tools 必须来自 ToolRegistry 真实 tool name，或 `fake.` 前缀的测试 tool
6. **禁止**使用 `bash`、`shell`、`run_shell`、`write` 等作为 allowed tool（除非是 `fake.write_file` 且明确不真实执行）

---

### E01：Base Runtime + Provider

```
track: R (Runtime Action Harness)
action_type: tool.request（至少）
描述:
  Runtime 通过 chat() 启动，LLM 产生 tool call，
  RuntimeActionDispatcher 将 tool call 包装为 tool.request action。

输入:
  - provider: 真实 LLM provider（kimi-k2.5 via DashScope Anthropic-compatible）
  - 用户 prompt: "列出当前目录的文件"
  - allowed_tools: [项目实际存在的 read-only tool name]（如 ToolRegistry 中对应的 file listing tool）
  - 注意：不使用 bash。使用 ToolRegistry 中实际的 safe/low-risk read tool

pass 条件（同时满足）:
  1. chat() 返回非空响应
  2. RuntimeActionEvent(action_type="tool.request") 存在于 action log
  3. 对应 event 的 evidence["module_invoked"] == true
  4. evidence["handler_name"] 非空
  5. evidence["target_module"] 非空
  6. 无 secret 泄露在 event.evidence 中
  7. evidence["resolved_tool_name"] 来自 ToolRegistry（非臆造）

invocation_mode: actual_runtime_invoked
```

---

### E02：Skill Selection

```
track: S (Skill Runtime Action)
action_type: skill.select
描述:
  Runtime LLM 在 tool calling 中显式选择并加载 skill。
  selected_skill_id 必须来自 LLM tool call decision（不是后验补的）。
  场景设置: workspace 中包含 3 个 skill（code-review, testing, docs），
  其中 1 个（docs）为 disabled。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "审查 agent/core.py 的代码"
  - workspace skills: code-review/（active, 含 body），testing/（active），docs/（disabled）

pass 条件（SDD S.6 强制，同时满足）:
  1. RuntimeActionEvent(action_type="skill.select") 存在于 action log
  2. evidence["selected_skill_id"] 非空且来自 LLM tool call decision
  3. evidence["body_load_decision"] == true
  4. evidence["module_invoked"] == true
  5. evidence["handler_name"] == "SkillRuntimeActionHandler"
  6. evidence["target_module"] 含 "SkillLoader"
  7. evidence["invocation_proof"] 含 SkillLoader.load_body() 调用记录
  8. evidence["hidden_or_disabled_excluded_count"] > 0（disabled skill "docs" 被排除）且 disabled skill 名称未出现在任何 evidence 字段中
  9. evidence["no_suitable_skill"] == false

invocation_mode: actual_runtime_invoked
```

---

### E03：SubAgent L0 Delegation

```
track: A (SubAgent L0 Runtime Action)
action_type: subagent.delegate_l0
描述:
  Runtime LLM 识别到需要委派的任务，通过 tool calling 显式选择 SubAgent。
  subagent_name 来自 LLM tool call decision（RuntimeAction 的显式选择结果）。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "使用 code-reviewer subagent 审查 agent/core.py"
  - workspace subagents: code-reviewer（active, L0）
  - 注意：allowed_tools 使用 SubAgent descriptor 中声明的真实 tool name，不臆造

pass 条件（SDD A.6 强制，同时满足）:
  1. RuntimeActionEvent(action_type="subagent.delegate_l0") 存在于 action log
  2. evidence["subagent_name"] 非空且来自 LLM tool call decision
  3. evidence["subagent_request_built"] == true
  4. evidence["delegate_once_called"] == true
  5. evidence["parent_adjudicated"] == true
  6. evidence["adjudication"] == "accept"
  7. evidence["no_nested_delegation"] == true
  8. evidence["no_shell_or_external_process"] == true
  9. evidence["module_invoked"] == true
  10. evidence["target_module"] 含 "SubAgentExecutor"

invocation_mode: actual_runtime_invoked
```

---

### E04：Memory Turn-end Proposal

```
track: M (Memory Runtime Hook)
action_type: memory.propose
描述:
  Runtime turn-end hook 在 user turn + model response 后触发，
  无论本 turn 是否发生 tool call。
  Hook 扫描当前 turn 的 user message + assistant response，
  识别 memory-worthy content 并触发 proposal（pending_review 状态）。

  关键设计：E04 对话场景（"请记住/用户偏好"类）不一定触发 tool call。
  Hook 必须在 turn-end 触发，不依赖 tool execution。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "记住：这个项目使用 DashScope Anthropic-compatible endpoint，模型是 kimi-k2.5"
  - 此 prompt 包含 project 配置偏好，应触发 memory proposal

pass 条件（同时满足）:
  1. RuntimeActionEvent(action_type="memory.propose") 存在于 action log
  2. evidence["disposition"] == "proposed"
  3. evidence["pending_review"] == true
  4. evidence["not_confirmed"] == true（未被自动 confirmed）
  5. evidence["secret_like_detected"] == false
  6. evidence["module_invoked"] == true
  7. turn-end hook 被调用（无论本 turn 是否有 tool call）

不通过条件:
  - hook 未被调用 → E04 只能 partial/fail，不能 pass
  - memory subsystem 被直接调用而非通过 hook → partial

invocation_mode: actual_runtime_invoked
```

---

### E05：ToolRegistry Gate

```
track: T (ToolRegistry Action Gate)
action_type: tool.request
描述:
  Runtime LLM 尝试调用高风险 tool，
  ToolRegistry gate 要求 confirmation。

  高风险 tool 使用 fake 前缀的测试 tool name，确保不会真实执行：
  - fake.write_file（模拟高风险写操作）
  - fake.modify_config（模拟配置修改）
  这些 fake tools 注册在 ToolRegistry 中，标记为高风险，
  但在 handler 中不会真实执行文件操作。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "创建一个配置文件"
  - allowed_tools: [项目实际存在的 read tool, "fake.write_file", "fake.modify_config"]
  - 注意：
    - 不使用 "write" / "bash" / "shell" / "run_shell" 等真实 shell tool
    - fake.write_file 和 fake.modify_config 是注册在 ToolRegistry 中的 fake test tools
    - 它们在 handler 中不会真实执行文件/配置修改

pass 条件（同时满足）:
  1. RuntimeActionEvent(action_type="tool.request") 存在于 action log
  2. 至少 1 个 tool.request event 的 evidence["risk_level"] == "high"
  3. 该 event 的 evidence["disposition"] == "confirmation_required"
  4. 高风险 tool 未经 confirmation 不得执行
  5. evidence["resolved_tool_name"] 来自 ToolRegistry（非臆造）
  6. evidence["registry_found"] == true
  7. fake tool 未真实执行（检查 evidence["dangerous_tool_function_invoked"] == false —— fake. 前缀 tool 不触发真实 IO）
  8. 真实 ToolRegistry 中不存在 fake. 前缀 tool（fake tool 仅在 dogfood 本地作用域）

invocation_mode: actual_runtime_invoked
```

---

### E06：Checkpoint-safe Summary

```
track: C (Checkpoint-safe Summary)
action_type: checkpoint.safe_summary
描述:
  Runtime 在 turn 结束后、save_checkpoint 前产生 checkpoint-safe summary，
  redact secret-like content。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "生成一个包含 api_key=sk-test12345 的配置文件模板"
  - 期望行为: LLM 可能生成包含 fake key 的文本，safe_summary 应检测并 redact

pass 条件（同时满足）:
  1. RuntimeActionEvent(action_type="checkpoint.safe_summary") 存在于 action log
  2. evidence["safe_summary"] 不含 "sk-test12345"
  3. evidence["secret_content_detected"] == true
  4. evidence["safe_summary"] 非空
  5. evidence["module_invoked"] == true

关于 secret 内容的设计说明: 此场景中 LLM 会生成示例模板，其中包含 fake key。
checkpoint-safe summary 应将 fake key 也标记为 secret-like 并 redact——
"宁可多 redact，不可漏过"。

invocation_mode: actual_runtime_invoked
```

---

### E07：Streaming Evidence（含 Unsupported Provider 分支）

```
track: P (Streaming E2E Evidence)
action_type: streaming.event
描述:
  Runtime 在每次 LLM streaming 交互完成后收集 evidence。
  必须处理 unsupported provider 的 fail-closed 分支。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "解释 First Agent 的架构"

pass 条件（分支）:

  A. provider.supports_streaming == true:
     1. RuntimeActionEvent(action_type="streaming.event") 存在于 action log
     2. evidence["events_received"] > 0
     3. evidence["final_event_received"] == true
     4. evidence["error_event_received"] == false
     5. evidence["provider_supports_streaming"] == true

  B. provider.supports_streaming == false:
     1. evidence["provider_supports_streaming"] == false
     2. status == "not_supported"
     3. evidence["final_event_received"] == false
     4. evidence["events_received"] == 0
     5. **此分支 E07 为 partial/blocked（不能算 pass）**
     6. 不得 silent fallback 成 non-streaming 后还算 streaming pass
     7. 不得生成 fake final event

invocation_mode: actual_runtime_invoked (分支 A) / partial (分支 B)
```

---

### E08：Full Combined

```
track: R/S/A/M/T（综合）
action_type: 至少 3 种不同的 action_type
描述:
  Runtime 在一个多轮对话中触发多种 RuntimeAction，每种都有 module invocation proof。
  用户请求: "审查 agent/core.py 的代码质量，如有问题请委派 code-reviewer subagent 审查，
  审查过程中如需查看文件使用可用工具，最后如果有值得记录的发现，帮我记住。"

  期望流程:
  1. LLM 选择 skill（skill.select）→ SkillLoader 被调用
  2. LLM 委派 SubAgent（subagent.delegate_l0）→ delegate_once 被调用
  3. LLM 使用 tool（tool.request）→ ToolRegistry gate 检查
  4. turn-end memory hook 触发（memory.propose）

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: 上述综合 prompt
  - workspace: skills（code-review）+ subagents（code-reviewer）
  - allowed_tools: ToolRegistry 中实际存在的 read-only tools

pass 条件（同时满足）:
  1. chat() 返回非空响应
  2. action log 中包含至少 3 种不同的 action_type:
     - skill.select（evidence.module_invoked=true）
     - subagent.delegate_l0（evidence.module_invoked=true）
     - tool.request（evidence.module_invoked=true）
     - memory.propose（可选，如有则 evidence.module_invoked=true）
  3. 每种 action_type 的 event.evidence["handler_name"] 非空
  4. 每种 action_type 的 event.evidence["target_module"] 非空
  5. 每种 action_type 的 event.evidence["invocation_proof"] 非空
  6. 无 event 的 status="failed"
  7. 所有 event.evidence 不含 secret

非 pass 条件（不能仅凭以下通过）:
  - "模型输出文本提到了 skill/SubAgent/Memory"
  - "chat() 返回了文本，文本里包含了这些词"
  - "LLM 说它已经做了 X"（必须 action log 中有对应 event + module_invoked=true）
  - RuntimeActionEvent 存在但 module_invoked=false（event 是收据不是证据）

evidence 来源: action log（所有 event 类型 + module invocation proof）
invocation_mode: actual_runtime_invoked
```

---

### E09：Provider API Key Integrity

```
track: R（安全验证）
action_type: 不要求特定 action_type（安全基线测试）
描述:
  验证 API key 未被泄露在 action event、checkpoint、或 chat 输出中。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "你好，介绍一下自己"

pass 条件:
  1. chat() 返回非空响应
  2. 所有 RuntimeActionEvent.evidence 不含真实 API key 或 key 片段
  3. checkpoint safe_summary 不含真实 API key
  4. chat 输出文本不含真实 API key
  5. 无 .env 文件内容被读取或记录

invocation_mode: actual_runtime_invoked
```

---

## 2. Pass/Fail 判定协议

### 统一 pass 条件

```
pass:
  - 所有 pass 条件满足
  - invocation_mode == "actual_runtime_invoked"
  - 每个 runtime_e2e capability 对应的 RuntimeActionEvent 满足 Action Evidence Contract 全部 6 项:
    1. RuntimeActionEvent emitted
    2. RuntimeActionDispatcher routed
    3. target handler invoked (evidence.handler_name 非空)
    4. target module invocation recorded (evidence.module_invoked=true)
    5. result returned to Parent Runtime
    6. capability matrix evidence 引用 action_id / handler_name / module_name
  - 无 blocked/fail 条件触发
  - 无 secret 泄露

partial:
  - 部分 pass 条件满足（≥50%）
  - 或 invocation_mode == "direct_subsystem_invocation"
  - 或 RuntimeActionEvent 存在但 module_invoked=false（自欺防御）
  - 或 LLM 响应不稳定导致部分条件未达到（非代码缺陷）
  - 或 unsupported provider 场景（E07 分支 B）

blocked:
  - 前置条件不满足（如 provider 不可用）
  - API 调用失败（非代码导致）
  - .env 配置问题

fail:
  - pass 条件全部不满足
  - 代码缺陷导致
  - secret 泄露
  - agent 幻觉声称执行了未发生的 action
```

### 诚实分级规则

- `actual_runtime_invoked` + 所有条件满足 + module_invoked=true → pass
- `actual_runtime_invoked` + event 存在但 module_invoked=false → partial（不能 pass）
- `direct_subsystem_invocation` → 自动降级为 partial
- `simulated` → partial 或 blocked
- "模型文本提到 X" → 不算任何 evidence

---

## 3. Tool Alias Policy

本文档中使用的 tool name 遵循以下规则：

| 用途 | 文档引用方式 | 示例 |
|------|-------------|------|
| 项目真实工具 | 从 ToolRegistry 读取真实 tool name | E01 使用 ToolRegistry 中实际的 read tool |
| E2E 高风险诱导 | `fake.<name>` 前缀的测试 tool（**仅在 dogfood runner 本地注册**） | `fake.write_file`, `fake.modify_config` |
| Generic 能力描述 | 能力名（非 tool name） | "file_read 能力" |

**禁止使用**：`bash`、`shell`、`run_shell`、`write`（裸写操作 tool name）。

**关键边界**：`fake.` 前缀 tool 仅在 dogfood runner 本地作用域注册，绝不污染项目真实 ToolRegistry。真实 ToolRegistry 中不得出现任何 `fake.` 前缀的 tool name。

E2E dogfood runner 必须从 ToolRegistry 读取真实 tool names 来构建 allowed_tools 列表。
如果 tool 在 registry 中不存在，scenario 不能 pass。

---

## 4. 运行命令

```bash
# 全量 E2E dogfood
python scripts/dogfood_e2e_runtime.py --all

# 单个 scenario
python scripts/dogfood_e2e_runtime.py --scenario E02

# 仅 runtime_e2e 场景（E01-E09）
python scripts/dogfood_e2e_runtime.py --mode runtime

# 带 verbose action log
python scripts/dogfood_e2e_runtime.py --all --verbose-action-log
```

---

## 5. 目标指标

| 指标 | 当前（8aa11a4） | 目标（Phase 9 完成后） |
|------|-----------------|------------------------|
| actual_runtime_invoked scenario | 3/9 | ≥ 6/9 |
| direct_subsystem_invocation scenario | 6/9 | ≤ 3/9 |
| simulated scenario | 0/9 | 0/9 |
| pass（诚实分级后） | 3/9 | ≥ 6/9 |
| partial | 6/9 | ≤ 3/9 |
| blocked | 0/9 | 0/9 |
| fail | 0/9 | 0/9 |
| capability matrix naming mismatch | 存在 | 0 |
| RuntimeActionEvent + module_invoked=true 覆盖的 capability | 0 | ≥ 6 |

---

## 6. 与前一版 Dogfood 的关系

| 原 scenario | 原 invocation_mode | 处置 |
|-------------|-------------------|------|
| E01 (base runtime) | actual_runtime_invoked | 重写：移除 bash，使用 ToolRegistry 真实 tool |
| E02 (skill) | direct_subsystem_invocation | 降级为 `tests/` 下的 subsystem integration test；新 E02 为 skill.select RuntimeAction + module invocation proof |
| E03 (subagent) | direct_subsystem_invocation | 同上；新 E03 为 subagent.delegate_l0 RuntimeAction + module invocation proof |
| E04 (memory) | direct_subsystem_invocation | 同上；新 E04 为 memory.propose turn-end hook + module invocation proof |
| E05 (tool registry) | direct_subsystem_invocation | 同上；新 E05 为 tool.request gate + tool alias resolution |
| E06 (checkpoint) | direct_subsystem_invocation | 同上；新 E06 为 checkpoint.safe_summary + module invocation proof |
| E07 (streaming) | deterministic_baseline | 同上；新 E07 为 streaming.event（含 unsupported provider 分支） |
| E08 (full combined) | actual_runtime_invoked（但 evidence 是文本匹配） | 重写：pass 条件改为 module invocation proof，不能仅凭文本 |
| E09 (provider integrity) | actual_runtime_invoked | 保留，增强：新增 action event 检查 |
