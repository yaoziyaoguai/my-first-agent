# Runtime Integration / Runtime Action Harness — RFC

> 状态：需求规格（不包含实现代码）
> 关联文档：SDD、TDD、Implementation Loop、E2E Dogfood Plan、Audit Checklist
> 语言：简体中文为主，英文术语括注

---

## 1. 背景

### 1.1 当前架构现状

First Agent v0.9.x 已具备以下子系统（subsystem）：

- **Skill System**：`SkillRegistry` / `SkillSelector` / `SkillLoader` / `SkillToolBinding`
- **SubAgent System**：`SubAgentRegistry` / `SubAgentRequest` / `delegate_once` / L0 executor（确定性，非 LLM）
- **Memory System**：`FilesystemMemoryStore` / `load_episodic_evidence` / `run_consolidation_pipeline` / proposal→pending_review 链路
- **ToolRegistry**：工具注册、可见性过滤、风险分级（`needs_tool_confirmation`）
- **Checkpoint**：`save_checkpoint` / `load_checkpoint` / 截断配置、resume 安全
- **Streaming**：`ProviderStreamEvent` / `collect_stream_response` / `sanitize_stream_text`
- **Provider**：`ModelProvider` / `AgentProviderConfig` / project .env scoped loader
- **Runtime**：`core.chat()` / `_build_loop_context` / plan→confirm→execute 主循环

### 1.2 API 加载已验证

最新 real-api E2E dogfood (commit `0371f68`) 确认：

- `key_source_kind = project_dotenv`，`project_dotenv_loaded = true`
- `auth_status = configured`，`shell_env_fallback_used = false`
- secret 未打印，.env 内容未读取
- `chat(provider=provider)` 直传路径在 3/9 scenario 中验证通过

**结论：真实 API key 已经可以通过 project .env scoped loader 被 E2E runtime path 稳定使用。API 注入不再是 blocker。**

### 1.3 E2E Dogfood 暴露的真实问题

| 问题 | 严重度 | 性质 |
|------|--------|------|
| 只有 3/9 scenario 真正走 `core.chat()` + real LLM | P3 | 覆盖率不足 |
| 6/9 scenario 是 direct subsystem invocation，未经过 Runtime 主循环 | P3 | 测试方法学限制 |
| Skill/SubAgent/Memory/Checkpoint/Streaming 均未通过 Runtime LLM tool calling 触发 | P2 | 架构集成 gap |
| E08（full combined）虽然走了 `chat()`，但仅验证了"模型输出文本"，未验证"模型通过 tool calling 实际触发了子系统" | P2 | 验证不精确 |
| `_capability_evidence_matrix` 中 capability name（`"SubAgent"`）与 `systems_actually_invoked`（`"SubAgentRegistry"`）命名不匹配 | P3 | 展示层 bug |
| 没有 Runtime Action 抽象：当前 `chat()` 的 tool calling 只能调用 tool_registry 中的工具，不能触发 Skill/SubAgent/Memory 等"能力型"操作 | P1 | 架构缺口 |

### 1.4 为什么不能直接进入 SubAgent L1

SubAgent L1 需要 Runtime LLM 在 tool calling 循环中**自主判断**委托需求、构造 `SubAgentRequest`、处理返回结果并进行 parent adjudication。当前状态：

- SubAgent L0 executor 是确定性的（`local_fake`），不经过 LLM reasoning
- 没有 Runtime Action 抽象来在 tool calling 中触发 SubAgent delegation
- 没有任何 E2E 场景验证过 "LLM 自主触发 SubAgent delegation"
- 直接进入 L1 意味着在未经验证的基础上叠加 LLM 推理，不可测试

**前置条件：先完成 Runtime Integration / Runtime Action Harness，使 Runtime LLM 可以通过受控的 action path 触发子系统能力。**

---

## 2. Problem Statement

### 2.1 核心问题

**当前 First Agent 的 Runtime LLM 没有统一的、可审计的 action path 来触发子系统能力。**

具体表现：

1. **Skill selection**：`SkillSelector` 是关键词匹配（非 LLM），`SkillLoader` 是程序化调用。Runtime LLM 无法在 tool calling 中选择/加载 skill——它只能"提到"某个 skill，但实际选择发生在 Runtime 代码中，而非 LLM 推理中。

2. **SubAgent L0 delegation**：`delegate_once` 是确定性执行。Runtime LLM 无法判断"这个任务需要委派给哪个 SubAgent"——当前 delegation 完全由 harness 脚本程序化触发。

3. **Memory proposal/review**：consolidation pipeline 被 E04 harness 直接调用。Runtime LLM 在对话中无法识别 memory-worthy content 并主动触发 proposal——proposal 是由测试脚本程序化触发的。

4. **Checkpoint / Streaming**：E06/E07 直接调用模块 API，未验证 Runtime 上下文中的行为（如 Runtime 在 tool 执行后是否正确保存 checkpoint）。

5. **Capability evidence matrix**：命名 mismatch 导致能力矩阵展示错误。更深层的问题是没有统一的 capability→module→evidence 映射协议。

6. **"模型提到" vs "Runtime 调用"**：E08 中模型输出文本提到了 Skill/SubAgent/Memory，但 E2E harness 没有检查 Runtime 是否实际调用了这些子系统。当前 evidence 是 "文本中包含能力相关关键词"，不是 "Runtime action event 记录显示该能力被触发"。

### 2.2 影响范围

- 无法声称 First Agent 具备"真正的" E2E 能力
- SubAgent L1 无法开始（没有 Runtime-integrated L0 验证基线）
- Memory integration 质量不可知
- 外部审计无法区分 "代码写对了" 和 "Runtime 跑通了"

---

## 3. Goals

### 3.1 必须完成

| Goal | 优先级 | 说明 |
|------|--------|------|
| Runtime Action 抽象 | P0 | `RuntimeActionRequest` / `RuntimeActionResult` / `RuntimeActionDispatcher` |
| Runtime-invoked Skill selection | P0 | LLM 在 tool calling 中选择 skill，Runtime 通过 RuntimeAction 触发加载 |
| Runtime-invoked SubAgent L0 delegation | P0 | LLM 在 tool calling 中触发 delegation，Runtime 通过 RuntimeAction 路由到 L0 executor |
| Runtime Memory proposal/review hook | P0 | Runtime 在对话回合中识别 memory-worthy content，通过 RuntimeAction 触发 proposal |
| Runtime ToolRegistry gate | P1 | 所有 tool call 必须经过 ToolRegistry policy 检查，通过 RuntimeAction 路由 |
| Runtime Checkpoint-safe summary | P1 | Runtime 在 tool 执行后触发 checkpoint-safe summary，通过 RuntimeAction hook |
| Runtime Streaming E2E evidence | P1 | Runtime 消费 provider streaming events，通过 RuntimeAction 收集 evidence |
| Capability evidence matrix fix | P1 | 统一 capability name → module alias mapping，evidence level 分级 |
| E2E dogfood rewrite | P2 | 新场景必须基于 RuntimeAction events 验证，不依赖 direct subsystem invocation |

### 3.2 成功标准

- 所有 P0/P1 goal 的 RuntimeAction 路径在 E2E dogfood 中得到验证
- `actual_runtime_invoked` scenario ≥ 6（当前 3）
- `direct_subsystem_invocation` scenario 降至 ≤ 3
- capability matrix 所有 entry 有明确的 evidence 来源
- 没有 P0/P1 审计问题
- full pytest 通过

---

## 4. Non-goals（明确不做）

| Non-goal | 原因 |
|----------|------|
| SubAgent L1/L2 | 需要 Runtime Integration 完成后再设计 |
| 真实 shell / external process / worktree / bash | 安全边界，由 ToolRegistry gate 保护。E2E dogfood 中禁止使用 bash/shell/run_shell 作为 allowed tool，高风险诱导场景使用 fake. 前缀的测试 tool |
| 扩大 Observability（OpenTelemetry / dashboard / trace viewer / metrics） | 不扩大范围，streaming 仅收集 E2E dogfood 验证所需最小字段 |
| Checkpoint schema change | 保持现有 schema 稳定 |
| Memory governance change | 现有 proposal→pending_review 链路不改变 |
| ToolRegistry authority change | 现有 policy 层级不改变 |
| Skill/SubAgent 拥有主 Agent loop | Parent Runtime 始终是唯一 orchestrator |
| LLM 绕过 ToolRegistry | ToolRegistry 始终是 tool 执行的唯一门禁 |
| Memory 自动 silent retain / auto approve | Memory governance 不变 |

---

## 5. 核心原则

### 5.1 架构原则

1. **Parent Runtime owns orchestration**（父 Runtime 拥有编排权）
   - Runtime 主循环（plan→confirm→execute）是唯一的状态推进者
   - RuntimeAction 不是第二套主循环——它是 Parent Runtime 触发子系统能力的**受控入口**
   - 子系统不得自行推进 Runtime state

2. **Runtime Action 必须可审计**（auditable）
   - 每个 RuntimeAction 产生不可变的 action event；action event 只是 receipt，不是 runtime_e2e evidence
   - action event 包含：source、type、input、output、status、timestamp
   - RFC-level invariant: runtime_e2e = RuntimeActionEvent + RuntimeActionDispatcher route + handler invoked + independently observed target_module_proof + parent result/adjudication where applicable
   - Event-only RuntimeAction audit 不得标 runtime_e2e；RuntimeActionEvent + module_invoked=true、RuntimeActionEvent + handler_name + target_module 也不得标 runtime_e2e
   - runtime_e2e 必须有 target_module_proof，且 target_module_proof 必须 independently observed；handler self-asserted proof、free-text invocation_proof、shaped dict without independent observation 均不得 pass
   - E2E dogfood 通过 action events 记录 receipt，通过 target_module_proof 验证能力覆盖

3. **ToolRegistry remains authority**（工具注册表保持权威）
   - 所有 tool execution 必须经过 ToolRegistry policy 检查
   - 高风险 tool 必须 confirmation
   - RuntimeAction 中的 tool request 同样受 ToolRegistry 管辖

4. **Memory governance remains authority**（记忆治理不变）
   - proposal→pending_review→confirmed/rejected 链路不改变
   - 无 silent retain，无 auto approve
   - secret-like 过滤保留

5. **SubAgent L0 remains bounded**（SubAgent L0 保持受限）
   - 无嵌套 delegation
   - 无 shell/external process
   - 无真实 LLM inside SubAgent（直到 L1 显式 gated）
   - Parent adjudication 必须

6. **Skill progressive disclosure preserved**（渐进式加载保持）
   - 先 metadata only
   - 选中 skill 后才加载 body
   - hidden/disabled skill 不可见

7. **Confirmation required for high-risk actions**（高风险操作必须确认）
   - 任何标记为 high-risk 的 tool 必须经用户确认
   - RuntimeAction 中的高风险操作同样受此约束

8. **No direct subsystem bypass in E2E dogfood**（E2E dogfood 禁止直接调用子系统）
   - 新 E2E 场景必须通过 Runtime Action path 触发子系统
   - 不再接受 direct subsystem invocation 作为 pass 条件

9. **Evidence-driven capability matrix**（证据驱动的能力矩阵）
   - 每个 capability 的 e2e_verified 状态必须有 RuntimeAction event 支撑
   - 不能仅凭 "模型文本提到" 判定为 verified

10. **Behavior-neutral where possible**（尽可能行为中立）
    - RuntimeAction 是路由/证据层，不改变子系统内部行为
    - 只在必要时（如 Runtime hook point）添加显式行为

### 5.2 设计约束

- 不新增 module-level global singleton
- 不引入循环依赖
- RuntimeAction 相关代码放在 `agent/runtime_integration/` 下
- 测试文件放在 `tests/` 下，遵循现有 pytest 约定
- 所有新代码必须加中文学习型注释/docstring

---

## 6. 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|----------|
| RuntimeAction 抽象过度，增加复杂度 | P2 | 最小化 schema，只路由不执行 |
| E2E dogfood 仍无法覆盖所有 RuntimeAction path | P2 | TDD 先定义 pass 条件，不追求 9/9 |
| capability matrix 修复引入新的命名问题 | P3 | 统一 mapping table，单一事实来源 |
| Runtime hook point 破坏现有主循环 | P1 | 在 `chat()` 的 tool calling 循环中添加 hook，不改变循环结构 |

---

## 7. 审批要求

- [ ] RFC 通过 independent docs audit
- [ ] SDD 与 RFC 一致
- [ ] TDD 覆盖所有 Track
- [ ] Implementation Loop 每个 phase 有明确 stop condition
- [ ] Audit Checklist 覆盖 P0/P1/P2/P3
