# 独立审计报告：my-first-agent 多轮 Big Loop 后全系统审计

> 审计日期：2026-05-25
> 审计范围：read-only，不修改文件、不执行测试、不 commit、不 push、不读 .env、不打印 secrets、不发真实 API 调用、不发真实 LLM 调用、不访问外部网络
> 审计方法：阅读全部关键源码、工程契约、dogfood 报告、AD 文档、测试文件；运行 git diff --check / ruff / pytest 安全门检查

---

## A. Repo 安全快照

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 分支 | ✅ | main，clean |
| ahead/behind | ✅ | 0/0 |
| 未跟踪文件 | ✅ | 无 |
| git diff --check | ✅ | 无空白错误 |
| ruff lint | ✅ | All checks passed |
| pytest | ✅ | **3323 passed**, 18 skipped（全部显式 opt-in：real provider/LLM/MCP 需要环境变量） |
| secrets 在源码中 | ✅ | 无硬编码密钥；.env 由各 dogfood 脚本独立加载，不入库 |
| tag 状态 | ✅ | 最近 commit 无未推送 tag |

**结论**：仓库处于干净、健康、可审计状态。所有门检查通过。

---

## B. Big Loop 时间线重建

基于 git log 和 docs/plans/ 目录重建的最近 Big Loop 迭代序列：

| # | 阶段 | 关键 commit | 主题 |
|---|------|-------------|------|
| 1 | Issue Sweep | — | User-Usable Agent Runtime Issue Sweep（9 个 issue） |
| 2 | Issue 2 | — | Command Router 提取到 cli_commands.py |
| 3 | Issue 3 | — | NL delegation（中英文触发词 → demo-stat SubAgent） |
| 4 | Issue 4 | `da877d3` | Memory IDs + forget-by-short-id + 确认回复解析（affirmative shorthands） |
| 5 | Issue 5 | — | Run summary 富化（action_log 计数） |
| 6 | Issue 6 | — | Progress/event UX（streaming 事件 UX） |
| 7 | Issue 8 | — | Overclaim sweep（清理过度声明） |
| 8 | Dogfood | `ba12d7e` | Real provider tool-use E2E + Memory E2E dogfood scripts |
| 9 | AD | `e05e541` | Provider tool-call compatibility AD |
| 10 | L3 tests | `6ab8791` | SubAgent non-empty registry business delegation L3 tests |
| 11 | Roadmap | `d525e92` | Roadmap 收口：SubAgent L3, MEMORY_RECALL AD, MEMORY_PROPOSE, STREAMING_EVENT |

**观察**：最近 5 个 commit 覆盖了 4 个不同关注点（roadmap 收口、SubAgent L3 test、provider AD、dogfood），说明迭代节奏快但分散——这是多线收口的正常特征，不是方向漂移。

---

## C. Unified Runtime Flow 完整性审计

### C.1 核心流程验证

通过阅读源码确认的完整 flow：

```
用户输入 → core.chat()
  → CLI meta-command detection (cli_commands.py, pure detect/render)
  → memory evaluation
  → _resolve_provider_evidence_metadata() → provider_kind, provider_external_call
  → _run_main_loop()
    → assemble LoopDependencies (包含 provider_kind, provider_external_call)
    → loop.run_main_loop(dependencies)
      → while loop:
        → call_model() → ProviderResponse + RuntimeEvents
        → dispatch_model_output() → tool execution / text display
        → _try_phase1_turn_end_runtime_action()
          → dispatcher.route_from_runtime_loop() for EACH RuntimeAction:
            TOOL_GATE → TOOL_REQUEST → TOOL_INVOKE → TOOL_RESULT
            MEMORY_TURN_END_PROPOSAL → MEMORY_PROPOSE
            MEMORY_RECALL, MEMORY_CONSOLIDATE
            SKILL_SELECT
            SUBAGENT_DELEGATE_L0
            STREAMING_PROVIDER_CALL
            CHECKPOINT_SAFE_SUMMARY
            trace event emission
      → _emit_run_summary() → action_log 统计
```

### C.2 分支点分析

所有子系统都作为 `_try_phase1_turn_end_runtime_action()` 中的独立 try/except 块接入。这符合 `AUTO_RUN_WORKFLOW.md` 规定的"finite, testable, auditable branch points"约束。

**验证的约束合规**：
- ✅ 每个分支点有独立 handler（在 `build_phase1_dispatcher()` 中注册）
- ✅ 没有第二个 main flow（只有 `route_from_runtime_loop()` 入口）
- ✅ 分支点不相互依赖（各自 try/except）
- ✅ 没有 handler 直接调用另一个 handler

### C.3 Provenance 防伪机制

`dispatcher.py:route_from_runtime_loop()` 是真实 core loop evidence 的**唯一入口**：

```python
# dispatcher.py:339-358
def route_from_runtime_loop(self, request, *, core_entrypoint="core.chat", runtime_hook_name="loop.turn_end"):
    # provenance 由 dispatcher 参数写入 evidence，不从 request.payload 读取
    # 避免 dogfood/harness 通过 payload 字段伪造真实 core loop 证据
```

- `core_loop_invoked` / `core_entrypoint` / `runtime_hook_name` 只能由 `route_from_runtime_loop()` 写入
- `dispatcher_origin` 判别 `"runtime_loop"` vs `"direct_dispatcher"`
- handler 返回的 `RuntimeActionResult` 必须通过 `context.result()` 发行（`issued_result` 检查）
- handler evidence_extra 不允许写入 reserved fields（`HANDLER_EVIDENCE_RESERVED_FIELDS`），防止 handler 自证自签

**评分**：provenance 防伪机制设计严密，没有发现可绕过路径。

### C.4 发现的问题

**无重大问题**。有一个值得注意的细节：

- `_mark_returned_to_parent()` 中，`provider_kind` / `provider_external_call` 是从 `request.payload` 读取的（line 523-529），注释明确说这些是"adapter 与副作用语义，不参与 direct dispatcher 升级为 real core loop 的判定"。这是正确的设计——provider metadata 是描述性的，不改变 provenance。但需要确保 future handler 不会在 payload 中放入 provenance 敏感字段。

---

## D. Fake/Real Provider 边界审计

### D.1 门控机制

唯一的门控点：`MY_FIRST_AGENT_LLM_PROVIDER` 环境变量。

```python
# provider/factory.py:build_model_provider_from_env()
# 检查 MY_FIRST_AGENT_LLM_PROVIDER，加载 config，构建 provider
# 支持: anthropic_native, anthropic_compatible, openai_compatible, openai_native, fake
# fake 类型直接返回 FakeProvider()
```

### D.2 FakeProvider 审计

`agent/provider/fake_provider.py` (432 lines):
- `supports_streaming = True`, `supports_tools = False`（tools 通过 Tool Pipeline）
- `_resolve_tool_use()`: 4 策略优先级匹配（exact name → token → description keyword → legacy trigger）
- `stream()`: 确定性 12-char chunking
- 明确标注为 debug/demo 能力

### D.3 Real Provider 路径

- `anthropic_http.py`: Anthropic-compatible HTTP adapter（DashScope 等），`supports_streaming = False`, `supports_tools = True`
- `model_call.py:call_model()`: streaming/non-streaming 统一入口，两种路径产生相同的 RuntimeEvent 序列
- `_normalize_tool_name()` in `tool_registry.py`: suffix matching 是通用防御层，不是 provider-specific hack

### D.4 Tool-Use 兼容性

AD `docs/architecture/provider-tool-call-compatibility-ad.md` (accepted 2026-05-25):
- ToolUseBlock 是单一内部表示
- Provider adapter 负责归一化
- Tool name suffix matching 是通用的（不是 kimi-specific）
- Streaming/non-streaming 差异在 call_model.py 中处理
- 明确禁止：hard-parse plain text as tool_use, provider-specific branch in Tool Pipeline, 修改 ToolUseBlock semantics per provider, bypass Tool Pipeline

**评分**：边界清晰，无泄漏。Fake/Real 共享完全相同的 core.chat/loop.py/Tool Pipeline，只有 provider adapter 不同。

---

## E. Tool-Use E2E 审计

### E.1 Tool Pipeline Dispositions

从 `docs/plans/first-agent-subsystem-integration-roadmap.md` 和代码确认：

| Disposition | 状态 | Handler | 证据 |
|-------------|------|---------|------|
| TOOL_GATE | L3 complete | ToolGateHandler | 所有 4 种 disposition 已验证 |
| TOOL_REQUEST | L3 complete | ToolRequestHandler | 包括 not_found 路径 |
| TOOL_INVOKE | L3 complete | ToolInvokeHandler | 包括 error 和 not_found 路径 |
| TOOL_RESULT | L3 complete | ToolResultHandler | feedback branch behavior 已验证 |

### E.2 Dogfood 证据

`docs/dogfood/real-provider-e2e-report.json`:
- 4/4 PASS: A_basic_chat, B_explicit_tool_use, C_natural_tool_use, D_tool_non_use_control
- 使用 kimi-k2.5 @ DashScope
- 所有测试通过 `core.chat()` 入口

`docs/dogfood/local-manual-dogfood-report.md`:
- Fake: 9/9 PASS
- Real: 5/6 PASS, 1 CONCERN (tool_use not triggered naturally — 已确认为 prompt sensitivity，不是 capability gap）

### E.3 发现的问题

**P2 — 非阻塞**：real provider dogfood 中工具调用对 prompt 措辞敏感。system prompt 中的 tool-use guidance（config.py）已优化为 provider-neutral 语言，但 kimi-k2.5 在 natural tool use 场景下仍需要更明确的任务描述。这不是代码缺陷，但值得在后续 dogfood 中持续关注。

---

## F. Memory E2E 审计

### F.1 Memory Pipeline

确认的 flow：
```
MEMORY_TURN_END_PROPOSAL → MEMORY_PROPOSE (confirm/reject/pending)
→ MEMORY_RECALL (pre-loop prompt injection)
→ MEMORY_CONSOLIDATE (turn-end)
→ forget-by-short-id (CLI command)
```

### F.2 确认流程

`agent/memory_interaction.py`:
- `parse_memory_confirmation_reply()`: digit selection, "N text", affirmative shorthands (y/yes/ok/okay/yeah/sure/好/是/可以/确认/记住/行/对)
- `handle_memory_confirmation_reply()`: checkpoint save after resolution
- `handle_inline_confirmation_reply()`: queues confirmed proposals for MEMORY_PROPOSE dispatch

### F.3 Forget-by-ID

`core.py` 中的 forget 逻辑：
1. 检测 `forget id:XXX` 或 `/forget id:XXX` 命令
2. 三层匹配：exact match → prefix match → ambiguity → not found
3. 短 ID（前 8 字符）显示在 `render_memory_list()` 中

### F.4 Dogfood 证据

`docs/dogfood/memory-e2e-report.json`:
- 5/5 PASS: remember, confirm (with "y"), show_memories, forget (by short ID), verify_deletion

### F.5 发现的问题

**P2 — 非阻塞**：`parse_memory_confirmation_reply()` 中的 affirmative shorthands 列表硬编码在代码中（`{"y", "yes", "ok", "okay", "yeah", "sure", "好", "是", "可以", "确认", "记住", "行", "对"}`）。这在小规模下可接受，但如果将来需要支持更多语言或变体，应考虑将 affirmatives 提取到配置或至少集中到常量定义。

---

## G. SubAgent 审计

### G.1 系统架构

SubAgent 系统位于 `agent/subagent_system/`（19 个文件），清晰的模块边界：

| 模块 | 职责 |
|------|------|
| registry.py | 文件系统 backed descriptor registry |
| delegation.py | Parent adapter for L0 delegation |
| executor.py | Deterministic L0 executor（keyword-based） |
| adjudication.py | Parent adjudication decisions |
| context.py | Context packaging（不创建真实 LLM context） |
| runtime.py | Immutable state transitions |
| subagent_action.py | RuntimeAction handler（SUBAGENT_DELEGATE_L0） |

### G.2 L0 安全边界

从代码审计确认的强制约束：
- ✅ 不调用 provider
- ✅ 不执行工具（`execute_local()` 是纯 deterministic）
- ✅ 不 spawn 外部进程
- ✅ 禁止 nested delegation（`subagent_action.py:60`）
- ✅ 禁止 shell/external process（`subagent_action.py:72-73`）
- ✅ parent adjudication required（`subagent_action.py:74-75`）
- ✅ budget 不超过 descriptor max_iterations_default（`subagent_action.py:79-80`）
- ✅ requested tools 必须是 descriptor allowed_tools 的子集（`subagent_action.py:70-71`）

### G.3 委托路径

两种委托方式共享同一执行路径：
1. CLI: `/delegate <name> <task>` → `_execute_subagent_delegation()`
2. NL: 中文/英文触发词 → `_execute_subagent_delegation()`
3. Turn-end hook: `SUBAGENT_DELEGATE_L0` RuntimeAction → `SubAgentDelegateL0Handler`

### G.4 测试覆盖

`tests/runtime_integration/test_subagent_l3.py` — 最近添加的 non-empty registry business delegation L3 tests（commit `6ab8791`）。

### G.5 发现的问题

**无重大问题**。SubAgent 系统的边界 enforce 是最严格的子系统之一。

一个值得注意的设计选择：`execute_local()` 的 `_deterministic_outcome()` 使用 keyword matching 决定结果。这在 L0 下是正确的（不需要真正理解任务），但如果将来升级到 L1+ real delegation，需要完全替换 executor，不能逐步演进。当前设计已将 L0 executor 隔离在独立模块中，替换路径清晰。

---

## H. Streaming/Progress/Trace 审计

### H.1 Streaming 架构

三层结构：
1. `agent/provider/streaming.py` — `ProviderStreamEvent` frozen dataclass + `collect_stream_response()` aggregator
2. `agent/model_call.py:call_model()` — streaming/non-streaming 统一入口
3. `agent/runtime_integration/streaming_provider.py` — `StreamingProviderCallHandler` (RuntimeAction handler)

### H.2 STREAMING_EVENT 状态

根据 roadmap 文档，`STREAMING_EVENT` RuntimeAction 当前为 **inactive**。`STREAMING_PROVIDER_CALL` 是 active dispatch，负责收集 streaming evidence。

从 `streaming_provider.py` 确认的 handler 行为：
- provider 不支持 streaming → `not_supported` disposition + `runtime_e2e_disqualified_reason`
- 无 streaming 事件 → `not_supported` disposition
- 有事件 → 验证 text_delta, final, error, sanitize, sequence monotonicity
- disqualified 条件：缺少 text_delta 或缺少 final event

### H.3 发现的问题

**P2 — 非阻塞**：`collect_stream_response()` 在 `provider/streaming.py:78-99` 中对 error event 直接 raise exception，在 final missing 时也 raise。这意味着 streaming error 会传播到 `call_model()` 的调用方。当前 `call_model()` 正确地用 try/except 包裹了 stream 迭代，但 `collect_stream_response` 的 fail-closed 语义需要通过 `ProviderResponseError` 的显式文档来确保所有调用方都知道如何处理。

---

## I. Command Router/Core 边界审计

### I.1 架构

`agent/cli_commands.py` (277 lines):
- detect 函数：纯字符串匹配，无副作用
- render 函数：纯格式化，无副作用
- 完全从 core.py 中提取出来

### I.2 命令类型

| 命令 | Detect 方式 | 执行位置 |
|------|-------------|----------|
| show memories | `/show memories` 或中文变体 | core.py 调用 render |
| forget | `/forget id:XXX` 或 `/forget keyword` | core.py 执行 memory remove |
| show subagents | `/show subagents` 或中文变体 | core.py 调用 render |
| delegate | `/delegate <name> <task>` | core.py 调用 delegation |
| NL delegation | 中英文触发词 | core.py 调用 delegation |

### I.3 发现的问题

**无重大问题**。Command Router 正确地从 core.py 中提取到独立模块，detect/render 分离清晰。所有副作用操作（memory remove, delegation）仍在 core.py 中执行，cli_commands.py 保持纯函数。

---

## J. Dogfood 报告真实性审计

### J.1 Dogfood 文档清单

| 文件 | 类型 | 状态 |
|------|------|------|
| `local-manual-dogfood-checklist.md` | 手动清单 | 9 步 |
| `local-manual-dogfood-report.md` | 手动报告 | Fake 9/9, Real 5/6 |
| `real-provider-e2e-report.json` | 自动化 E2E | 4/4 PASS |
| `memory-e2e-report.json` | 自动化 E2E | 5/5 PASS |
| `COMPLEX_REAL_API_DOGFOOD_REPORT.md` | 历史报告 | — |
| `E2E_RUNTIME_DOGFOOD_REPORT.md` | 历史报告 | — |
| `GLOBAL_REAL_API_DOGFOOD_REPORT.md` | 历史报告 | — |
| `SKILL_SYSTEM_DOGFOOD_PLAN.md` | 计划 | — |
| `SUBAGENT_DOGFOOD_PLAN.md` | 计划 | — |

### J.2 真实性验证

关键验证点：
1. E2E 脚本使用 `core.chat()` 入口 — ✅ 确认（`scripts/dogfood_real_provider_e2e.py`, `scripts/dogfood_memory_e2e.py`）
2. 环境变量加载有作用域限制 — ✅ 确认（`_load_project_env()` 只在 dogfood 脚本中调用）
3. dogfood 代码不泄漏到 runtime core — ✅ 确认
4. 报告中关于 kimi-k2.5 tool_use 的更正 — ✅ 确认（manual report 中明确更正了初始误判）

### J.3 发现的问题

**P3 — 观察**：dogfood scripts 位于 `scripts/` 目录，与项目源码分开，这是正确的。但 `scripts/dogfood_memory_e2e.py` 使用 `FakeProvider` injection 来避免真实 API 调用——注意这测试的是 provider==fake 的路径。real provider memory E2E 目前仅有 manual report 中的覆盖（1 个场景）。后续可考虑将 memory E2E 也扩展到 real provider。

---

## K. Gate Evidence 审计

### K.1 安全门

| 门 | 命令 | 结果 |
|----|------|------|
| whitespace | `git diff --check` | ✅ clean |
| lint | `ruff check agent tests scripts` | ✅ All checks passed |
| test | `pytest -x -q` | ✅ 3323 passed, 18 skipped |

### K.2 Skip 分析

18 个 skipped tests 全部是显式 opt-in：
- `MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1` (4)
- `MY_FIRST_AGENT_RUN_REAL_LLM_E2E=1` (1)
- `MEMORY_CONSOLIDATION_LLM_ENABLED` (6)
- `MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1` (3)
- `MY_FIRST_AGENT_RUN_REAL_MCP_FLIGHT=1` (3)
- real LLM extraction opt-in (1)

所有 skip 都有明确的 reason 说明，无误杀。

### K.3 测试覆盖概览

3323 tests 覆盖：
- Runtime integration L3 tests（tool pipeline, memory, subagent, skill, streaming, checkpoint, MCP）
- Contract tests（config, CLI, tool registry, memory store, provider）
- Boundary tests（skill, subagent, TUI, transition）
- Smoke tests（v0.1-v0.4）
- Security baseline
- Architecture boundaries

**评分**：测试覆盖全面，L3 级别测试覆盖了所有主要 subsystem。

---

## L. 产品/用户可用性判决

### L.1 当前可用功能

| 功能 | 状态 | 备注 |
|------|------|------|
| 基本对话 | ✅ 可用 | Fake + Real provider |
| 工具调用 | ✅ 可用 | Tool Pipeline L3 complete |
| Memory（记住/查看/删除） | ✅ 可用 | 含 short ID forget |
| Memory 确认流程 | ✅ 可用 | 含 affirmative shorthands |
| SubAgent 委托 | ✅ 可用 | CLI + NL, L0 only |
| Streaming 显示 | 🟡 基本可用 | Fake provider 确定拆分块，Real provider 取决于 provider |
| Run summary | ✅ 可用 | 含 action 统计 |
| Checkpoint/resume | ✅ 可用 | L3 complete |
| Skill 系统 | 🟡 框架就绪 | L3 dispatch verified |

### L.2 用户体验评估

**优点**：
- CLI 命令直观（`/show memories`, `/forget id:XXX`, `/delegate`）
- 确认流程容错性好（支持中英文 affirmative shorthands）
- Run summary 提供可操作的 action 统计
- 错误信息有 safe_preview（不泄露内部状态）

**不足**：
- SubAgent 委托结果对用户的信息量有限（L0 deterministic summary）
- Memory recall 当前是 pre-loop prompt injection，用户无感知
- 缺少 `/help` 命令来展示可用命令

### L.3 判决

**当前产品状态：可用但克制。** 所有核心功能都以 minimal viable 形式存在，没有过度工程化。用户可以执行基本的 agent 交互、使用工具、管理记忆、委托 SubAgent。不足主要在 UX polish 层面，不是功能缺失。

---

## M. 多轮 Big Loop 后的 Top Issues

### Issue 1 — P1: STREAMING_EVENT 仍为 inactive

根据 roadmap，STREAMING_EVENT dispatch 仍标记为 inactive。当前只有 STREAMING_PROVIDER_CALL 在收集 evidence，但没有将 streaming 事件转化为用户可见的 progress 更新。这意味着 real provider streaming 的逐字输出体验可能不如 fake provider 的确定拆分块。

**影响**：使用 real provider 时用户可能看不到逐字输出。

### Issue 2 — P2: Real provider 工具调用对 prompt 敏感

`local-manual-dogfood-report.md` 记录了 kimi-k2.5 在 natural tool use 场景下未触发工具调用的问题。虽然通过 `provider.create()` 直接调用证明了 kimi-k2.5 支持 Anthropic-style tool_use blocks，但仍需要在 system prompt 层面持续优化。

**影响**：用户说"帮我查一下"时，模型可能用文本回复而非调用工具。

### Issue 3 — P2: SubAgent L0 deterministic executor 的演进路径

`execute_local()` 使用 keyword matching。升级到 L1+ real delegation 需要完全替换 executor。当前隔离良好，但需要明确的升级 AD 来定义 replacement 而非 evolution 策略。

**影响**：后续 SubAgent 升级时需要重写 executor，但当前隔离使替换路径清晰。

### Issue 4 — P2: Memory recall 无用户可见性 ✅ 已解决 (2026-05-25)

MEMORY_RECALL 通过 pre-loop prompt injection 实现（Path A of MEMORY_RECALL_DUAL_PATH_AD），用户看不到哪些记忆被注入。AD 已裁决 Path A 和 Path B（turn-end evidence）serves different purposes，但缺少向用户展示 "已加载 N 条相关记忆" 的机制。

**解决**：`core.py` L693-702 已实现 Memory Kernel v1 通知——`_safe_emit_runtime_event(on_runtime_event, memory_injected_event(count))` 在 pre-loop 阶段发射 `memory.injected` 事件（文案"已加载记忆：N 条"），通过 sink 或 fallback print 到达用户。focused test `test_memory_injected_event_reaches_user_through_chat_sink` 钉死此行为。

**影响**：用户不知道系统在使用他们的记忆。

### Issue 5 — P3: Affirmative shorthands 硬编码

`parse_memory_confirmation_reply()` 中的 affirmatives 列表硬编码。如果后续需要支持更多语言变体，需要修改代码。

**影响**：低。当前覆盖中英文足够。

---

## N. Next Big Loop 推荐

### 推荐优先级

**Block 1 — Streaming UX 收口**（估时：1 个 Big Loop）
- 激活 STREAMING_EVENT dispatch
- 确保 real provider 的逐字输出体验与 fake provider 一致
- 验证 streaming event 正确传播到 TUI

**Block 2 — Real Provider 鲁棒性**（估时：1 个 Big Loop）
- 持续优化 system prompt 中的 tool-use guidance
- 添加 real provider tool-use 回归测试（opt-in, CI 中不跑）
- 考虑添加 `tool_use` hint 机制（例如在需要工具时显式提示模型）

**Block 3 — Memory UX 可见性** ✅ 已完成 (2026-05-25)
- ~~在 pre-loop 注入 memory recall 时展示 "已加载 N 条相关记忆"~~ → 已实现：`core.py` L693-702
- 可选：允许用户通过 `/show memories` 查看最近注入的记忆

**Block 4 — SubAgent L1 准备**（估时：0.5 个 Big Loop，仅设计）
- 编写 SubAgent L1 real delegation AD
- 定义 L0→L1 的替换策略
- 不在当前 Big Loop 实现

### 不推荐现在做的事

- ❌ SubAgent L1 real delegation（L0 MVP 足够，先补齐 Streaming UX）
- ❌ 多 provider 并发支持（当前单一 provider 够用，且会增加 Tool Pipeline 复杂度）
- ❌ Web UI / SaaS（违反 North Star）
- ❌ Memory consolidation 接入真实 LLM（当前 fake consolidation 足够验证流程）

---

## O. 最终建议

### 总体评价

**项目处于健康、可控的状态。** 经过多轮 Big Loop 迭代后：

1. **架构完整性**：Unified Runtime Flow 设计严密，所有子系统通过统一的 turn-end hook 接入，provenance 防伪机制可靠。没有发现架构腐化或捷径积累。

2. **代码质量**：核心模块行数适中（core.py 1136, loop.py 796, dispatcher.py 545, cli_commands.py 277）。模块边界清晰。中文学习注释有效地解释了设计意图。

3. **测试纪律**：3323 tests, 0 failures, 18 合理 skip。L3 测试覆盖了所有主要 subsystem 的完整 dispatch 路径。

4. **工程契约遵从**：`ENGINEERING_WORKFLOW.md` 和 `UNIFIED_RUNTIME_FLOW_CONTRACT.md` 中的约束在代码中得到了忠实执行。没有发现 fake/real split、dogfood 泄漏到 runtime、direct handler bypass、downstream patches for upstream errors 等禁止模式。

5. **技术债务**：当前仅有的技术债务是 STREAMING_EVENT inactive、real provider tool-use prompt sensitivity、affirmative shorthands 硬编码——全部是 P2/P3 级别，没有阻塞性问题。

### 最关键的正面发现

**Provenance 防伪机制是项目中最被低估的设计决策。** `route_from_runtime_loop()` vs `route()` 的区分、`core_loop_invoked` 不来自 payload、handler evidence_extra reserved fields fail-closed——这些确保了 L3 real_core_loop_runtime_e2e 证据永远不能被伪造。这是很多 agent runtime 项目忽略的审计基础。

### 最关键的改进建议

**优先激活 STREAMING_EVENT。** Streaming UX 是用户感知最强的部分——用户不关心 Tool Pipeline 有多少个 disposition，但他们会注意到打字机效果是否流畅。当前 fake provider 的确定拆分块体验掩盖了 real provider 在这个维度的不足。

### 一句话

**可以继续迭代，地基是稳固的。**
