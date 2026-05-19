# Runtime Integration / Runtime Action Harness — E2E Dogfood Plan

> 状态：验证计划（不包含实现代码）
> 关联文档：RFC、SDD、TDD、Implementation Loop、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 0. 核心变更：从 "模型文本提到" 到 "Runtime Action Event 证据"

### 前一版 E2E Dogfood 的问题

| 问题 | 影响 |
|------|------|
| 6/9 scenario 是 direct subsystem invocation，未经过 `core.chat()` | 验证的是 API 正确性，不是 runtime 集成 |
| E08（full combined）的 pass 条件仅检查 "模型输出文本是否提到了能力关键词" | "提到" ≠ "触发"，无法区分 LLM 的 text generation 和 actual system invocation |
| capability matrix 命名 mismatch | 展示层 bug，掩盖了真实的 coverage gap |
| 没有 RuntimeAction event 抽象 | 无法精确验证"哪个能力被触发、结果如何" |

### 本轮的解决方法

- **所有 pass 条件基于 RuntimeActionEvent**：场景必须证明 RuntimeActionDispatcher 实际路由了 action 并产生了 event
- **"模型文本提到 X" 不再作为 pass 条件**：必须检查 action log 中是否有对应的 action_type event
- **Direct subsystem invocation 降级**：原 E02-E07 的子系统直接调用改为 `tests/` 下的 integration test，不再作为 E2E dogfood scenario
- **新版 E02-E07 必须通过 `chat()` + real LLM**：每个场景验证一个 Track 的 RuntimeAction path

---

## 1. Scenario 设计

### 设计原则

1. 每个 scenario 对应一个 Track 的 RuntimeAction path
2. 每个 scenario 通过 `core.chat()` + real LLM 执行
3. 每个 scenario 的 pass 条件包含至少一个特定 action_type 的 RuntimeActionEvent
4. E08 是 full combined scenario，要求多个 action_type 在同一对话中触发
5. E01 是 base runtime，确保基础设施正常

---

### E01：Base Runtime + Provider

```
track: R (Runtime Action Harness)
action_type: tool.request（至少）
描述:
  Runtime 通过 chat() 启动，LLM 产生 tool call，
  RuntimeActionDispatcher 将 tool call 包装为 tool.request action，
  返回 disposition="allowed" 并执行 tool。

输入:
  - provider: 真实 LLM provider（kimi-k2.5 via DashScope Anthropic-compatible）
  - 用户 prompt: "列出当前目录的文件"
  - allowed_tools: ["bash"]

pass 条件（所有必须满足）:
  1. chat() 返回非空响应
  2. RuntimeActionEvent(action_type="tool.request") 存在于 action log
  3. 至少 1 个 tool.request event 的 evidence["disposition"] == "allowed"
  4. 无 secret 泄露在 event.evidence 中

evidence 来源:
  - action log（dispatcher 内存中的 event 列表）
  - 不是 "模型文本中提到 tool.request"

invocation_mode: actual_runtime_invoked
```

---

### E02：Skill Selection

```
track: S (Skill Runtime Action)
action_type: skill.select
描述:
  Runtime LLM 在 tool calling 中选择并加载 skill。
  场景设置: workspace 中包含 3 个 skill（code-review, testing, docs），
  其中 1 个（docs）为 disabled。
  LLM 需要在 tool calling 中选择合适的 skill 并加载。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "审查 agent/core.py 的代码"
  - workspace skills: code-review/（active, 含 body），testing/（active），docs/（disabled）

pass 条件:
  1. RuntimeActionEvent(action_type="skill.select") 存在于 action log
  2. event.evidence["selected_skill_id"] == "code-review"
  3. event.evidence["body_loaded"] == true
  4. event.evidence["no_suitable_skill"] == false
  5. disabled skill "docs" 未出现在 available_skills 中

evidence 来源: action log (skill.select event)
非 evidence: "模型输出文本提到 code-review skill"

invocation_mode: actual_runtime_invoked
```

---

### E03：SubAgent L0 Delegation

```
track: A (SubAgent L0 Runtime Action)
action_type: subagent.delegate_l0
描述:
  Runtime LLM 识别到需要委派的任务，通过 tool calling 触发
  subagent.delegate_l0 action，L0 executor 确定性执行，
  parent adjudication 返回 "accept"。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "使用 code-reviewer subagent 审查 agent/core.py"
  - workspace subagents: code-reviewer（active, L0, allowed_tools=["read", "grep"]）

pass 条件:
  1. RuntimeActionEvent(action_type="subagent.delegate_l0") 存在于 action log
  2. event.evidence["subagent_name"] == "code-reviewer"
  3. event.evidence["adjudication"] == "accept"
  4. event.evidence["execution_result"] 非空
  5. 未发生嵌套 delegation（action log 中只有 1 个 subagent.delegate_l0 event）

evidence 来源: action log (subagent.delegate_l0 event)
非 evidence: "模型输出文本提到委派"

invocation_mode: actual_runtime_invoked
```

---

### E04：Memory Proposal

```
track: M (Memory Runtime Hook)
action_type: memory.propose
描述:
  Runtime 在对话回合中识别到 memory-worthy content，
  通过 memory.propose hook 触发 proposal（pending_review 状态）。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "记住：这个项目使用 DashScope Anthropic-compatible endpoint，模型是 kimi-k2.5"
  - 此 prompt 包含 project 配置偏好，应触发 memory proposal

pass 条件:
  1. RuntimeActionEvent(action_type="memory.propose") 存在于 action log
  2. event.evidence["disposition"] == "proposed"
  3. event.evidence["secret_like_detected"] == false（上述 prompt 不含 secret）
  4. proposal 状态为 "pending_review"（非 "confirmed"）

evidence 来源: action log (memory.propose event)
非 evidence: "模型输出文本提到 memory"

invocation_mode: actual_runtime_invoked
```

---

### E05：ToolRegistry Gate

```
track: T (ToolRegistry Action Gate)
action_type: tool.request
描述:
  Runtime LLM 尝试调用高风险 tool（如 write），
  ToolRegistry gate 要求 confirmation。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "创建新文件 /tmp/test.txt，内容为 'hello'"
  - allowed_tools: ["read", "write"]（write 为高风险）

pass 条件:
  1. RuntimeActionEvent(action_type="tool.request") 存在于 action log
  2. 至少 1 个 tool.request event（tool_name="write"）的 evidence["risk_level"] == "high"
  3. 该 event 的 evidence["disposition"] == "confirmation_required"
  4. 高风险 tool 未经 confirmation 不得执行（检查 action log 中无 write tool 的 allowed 记录）

evidence 来源: action log (tool.request events)
非 evidence: "模型输出文本提到 risk"

invocation_mode: actual_runtime_invoked
```

---

### E06：Checkpoint-safe Summary

```
track: C (Checkpoint-safe Summary)
action_type: checkpoint.safe_summary
描述:
  Runtime 在 tool 执行后产生 checkpoint-safe summary，
  redact secret-like content，标记 huge prompt。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "生成一个包含 api_key=sk-test12345 的配置文件模板"
  - 期望行为: LLM 可能生成包含 fake key 的文本，safe_summary 应检测并 redact

pass 条件:
  1. RuntimeActionEvent(action_type="checkpoint.safe_summary") 存在于 action log
  2. event.evidence["safe_summary"] 不含 "sk-test12345"
  3. event.evidence["secret_content_detected"] == true
  4. event.evidence["safe_summary"] 非空

evidence 来源: action log (checkpoint.safe_summary event)
非 evidence: "模型输出文本提到 checkpoint"
```

**关于 secret 内容的设计说明**：此场景中 LLM 会生成一个**示例模板**，其中包含 fake key。checkpoint-safe summary 应将 fake key 也标记为 secret-like 并 redact，因为模式匹配不区分 "真实 secret" 和 "看起来像 secret 的文本"——这正是 checkpoint safety 的预期行为（宁可多 redact，不可漏过）。

```
invocation_mode: actual_runtime_invoked
```

---

### E07：Streaming Evidence

```
track: P (Streaming E2E Evidence)
action_type: streaming.event
描述:
  Runtime 在每次 LLM streaming 交互完成后收集 evidence。

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: "解释 First Agent 的架构"

pass 条件:
  1. RuntimeActionEvent(action_type="streaming.event") 存在于 action log
  2. event.evidence["events_received"] > 0
  3. event.evidence["final_event_received"] == true
  4. event.evidence["error_event_received"] == false

evidence 来源: action log (streaming.event)
非 evidence: "模型输出文本提到 streaming"

invocation_mode: actual_runtime_invoked
```

---

### E08：Full Combined

```
track: R/S/A/M/T（综合）
action_type: 至少 3 种不同的 action_type
描述:
  Runtime 在一个多轮对话中触发多种 RuntimeAction。
  用户请求: "审查 agent/core.py 的代码质量，如有问题请委派 code-reviewer subagent 审查，
  审查过程中如需查看文件使用 grep，最后如果有值得记录的发现，帮我记住。"
  
  期望流程:
  1. LLM 选择 skill（skill.select）
  2. LLM 委派 SubAgent（subagent.delegate_l0）
  3. LLM 使用 tool（tool.request，可能是 grep）
  4. 对话结束后 memory hook 触发（memory.propose）

输入:
  - provider: 真实 LLM provider
  - 用户 prompt: 上述综合 prompt
  - workspace: skills（code-review）+ subagents（code-reviewer）+ tools（read, grep）

pass 条件:
  1. chat() 返回非空响应
  2. action log 中包含至少 3 种不同的 action_type:
     - skill.select
     - subagent.delegate_l0
     - tool.request
     - memory.propose（可选）
  3. 每种 action_type 的 event ≥ 1
  4. 无 event 的 status="failed"
  5. 所有 event.evidence 不含 secret

非 pass 条件（不能仅凭以下通过）:
  - "模型输出文本提到了 skill/SubAgent/Memory"
  - "chat() 返回了文本，文本里包含了这些词"
  - "LLM 说它已经做了 X"（必须 action log 中有对应 event）

evidence 来源: action log（所有 event 类型）
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

evidence 来源: E09 preflight scan（key_source_kind, auth_status 等）
invocation_mode: actual_runtime_invoked
```

---

## 2. Pass/Fail 判定协议

### 统一 pass 条件

一个 scenario 的最终状态判定：

```
pass:
  - 所有 pass 条件满足
  - invocation_mode == "actual_runtime_invoked"
  - 无 blocked/fail 条件触发
  - 无 secret 泄露

partial:
  - 部分 pass 条件满足（≥50%）
  - 或 invocation_mode == "direct_subsystem_invocation"
  - 或 LLM 响应不稳定导致部分条件未达到（非代码缺陷）

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

与前一版一致：
- `actual_runtime_invoked` + 所有条件满足 → pass
- `direct_subsystem_invocation` → 自动降级为 partial
- `simulated` → partial 或 blocked（取决于是否预期）

---

## 3. 运行命令

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

## 4. 目标指标

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
| RuntimeActionEvent 覆盖的 capability | 0 | ≥ 6 |

---

## 5. 与前一版 Dogfood 的关系

| 原 scenario | 原 invocation_mode | 处置 |
|-------------|-------------------|------|
| E01 (base runtime) | actual_runtime_invoked | 保留，增强：新增 action event 验证 |
| E02 (skill) | direct_subsystem_invocation | 降级为 `tests/` 下的 subsystem integration test；新 E02 为 skill.select RuntimeAction |
| E03 (subagent) | direct_subsystem_invocation | 同上；新 E03 为 subagent.delegate_l0 RuntimeAction |
| E04 (memory) | direct_subsystem_invocation | 同上；新 E04 为 memory.propose RuntimeAction |
| E05 (tool registry) | direct_subsystem_invocation | 同上；新 E05 为 tool.request gate |
| E06 (checkpoint) | direct_subsystem_invocation | 同上；新 E06 为 checkpoint.safe_summary |
| E07 (streaming) | deterministic_baseline | 同上；新 E07 为 streaming.event |
| E08 (full combined) | actual_runtime_invoked（但 evidence 是文本匹配） | 重写：pass 条件改为 action event 证据 |
| E09 (provider integrity) | actual_runtime_invoked | 保留，增强：新增 action event 检查 |
