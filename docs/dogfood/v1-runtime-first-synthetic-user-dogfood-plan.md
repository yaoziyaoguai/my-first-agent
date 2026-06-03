# First Agent v1 Runtime-First Synthetic User Dogfood Plan

**创建**: 2026-06-04
**基线**: v1.0.0-engineering-closeout (tag `f6807ef`), HEAD `ea0ad82`
**执行者**: Coding Agent (DeepSeek v4 Pro)
**前次尝试**: `docs/dogfood/v1-synthetic-user-dogfood-plan.md` (prior evidence, preserved)

---

## 1. Purpose

本方案是 **入口驱动、Runtime-first、连续用户使用验证** 的合成用户狗粮计划。

**核心思想**:
1. 从真实用户入口 (`python main.py`) 开始 — 不绕过 CLI。
2. 用户连续使用 First Agent — 所有能力通过 unified runtime / core.chat 主流程自然触发。
3. Tool / Skill / MCP / Memory / Checkpoint / SubAgent 都不是独立主流程 — 只能作为 Runtime 主流程上的 branch point / subsystem intervention 被观察。
4. 不允许直接调用子系统 API 来冒充用户狗粮。
5. 不允许把单测通过当成用户连续使用通过。
6. Coding Agent 基于仓库事实（代码、测试、文档、v1 closeout）自主设计复杂用户旅程。

**与前次 dogfood 的关键区别**:
- 前次 `v1-synthetic-user-dogfood-plan.md` 由外部 prompt 写死 journey（J1-J11, R1-R6），journey 设计受限于固定场景。
- 本轮由 Coding Agent 在 Phase 1 能力审计后自主设计，journey 数量和复杂度不预设上限。
- 前次把 fake provider 测试通过等同于 12/12 promises PASS — 本轮严格区分 direct subsystem test 和 real user-journey evidence。
- 前次在发现 F-001 P0 后过早停止（原执行规则 #7），本轮执行策略明确 P0 记录后继续。

---

## 2. Architecture Model

### 2.1 主流程

```
用户输入 → python main.py (entry)
  → main_loop() → core.chat() (unified runtime, 唯一主路径)
    → _run_planning_phase() → loop.run_main_loop()
      → provider.generate() → model response
        → tool_use? → loop handle_tool_use_response()
          → ToolRuntimeMediator.execute_single_tool()
            → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
        → text? → loop display
      → turn-end hooks → dispatcher.route()
        → MEMORY_PROPOSE / MEMORY_CONSOLIDATE
        → CHECKPOINT_SAFE_SUMMARY
        → SKILL_SELECT
        → SUBAGENT_DELEGATE_L0
  → _run_cli_event_loop() → next turn or exit
```

### 2.2 子系统只是 Branch Point

| 子系统 | Branch Point | 触发方式 | 用户如何触发 |
|--------|-------------|---------|------------|
| Tool | TOOL_GATE → TOOL_INVOKE → TOOL_RESULT | 模型生成 tool_use | 用户请求触发工具调用 |
| Skill | SKILL_SELECT | turn-end hook | 用户请求匹配 skill 触发词 |
| MCP | mcp.discover / mcp.invoke | startup / tool pipeline | 用户请求触发 MCP 工具 |
| SubAgent | SUBAGENT_DELEGATE_L0 | turn-end hook | 用户请求触发委托 |
| Memory | MEMORY_PROPOSE / MEMORY_CONSOLIDATE | turn-end hook | 对话中自动触发 |
| Checkpoint | CHECKPOINT_SAFE_SUMMARY | turn-end hook | CLI restart 时 resume |
| Evidence | agent_log.jsonl / sessions/ | dispatcher | 所有操作自动产生 |

### 2.3 禁止的验证方式

- ❌ 直接调用 `ToolRuntimeMediator.execute_single_tool()` — 不是用户 journey
- ❌ 直接调用 `core.chat()` 的测试辅助 — 需要完整 main_loop 上下文
- ❌ 只检查 test suite PASS/FAIL — 测试通过 ≠ 用户可用
- ❌ 直接 dispatch route() 调用 — 不是真实事件流
- ❌ 只检查 no-crash — crash-free 是最低标准，不是能力证据

---

## 3. Capability Inventory Summary

从 Phase 1 审计（交叉验证 docs/code/tests）提取的能力清单：

### 3.1 Entry (P-ENTRY-1, P-ENTRY-2, P-ENTRY-3)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-ENTRY-1 | Plain CLI stable primary entry | `main.py:main()` → `main_loop()` | `test_main_entry.py` 11/11 | yes — `python main.py` | — |
| C-ENTRY-2 | Textual TUI candidate | `main.py:run_textual_main_loop()` | TUI tests, `cd tui && npm test` | yes — `python main.py --tui` | prototype, not default |
| C-ENTRY-3 | --shell deprecated compatibility | `main.py` deprecation path | `test_main_entry.py` | yes — `python main.py --shell` | stderr warning only |

### 3.2 Runtime (P-RUNTIME-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-RUNTIME-1 | Unified runtime / core.chat main path | `agent/core.py:chat()` @664 | `test_real_core_loop_e2e.py` | yes — all user input | — |
| C-RUNTIME-2 | RuntimeDecisionFrame 22 branch points | `agent/runtime_decision_frame.py` | `test_runtime_decision_frame.py` | no — internal | 21/22 PARTIAL, only subagent.delegate READY |
| C-RUNTIME-3 | RuntimeActionDispatcher + 40+ types | `agent/runtime_integration/schema.py` | `test_runtime_action_dispatch.py` | no — internal | — |

### 3.3 Provider (P-PROVIDER-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-PROV-1 | Provider config safety / redacted diagnostics | `agent/provider/simple_config.py` | `test_config_secret_safety.py` 8/8 | yes — CLI header | — |
| C-PROV-2 | FakeProvider default when no config | `agent/provider/factory.py` | `test_provider_factory.py` | yes — `python main.py` | — |
| C-PROV-3 | Real provider via config.yaml | `agent/provider/factory.py` | skipped (needs real key) | yes — configure config.yaml | MODEL_BEHAVIOR caveat |

### 3.4 Tool (P-TOOL-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-TOOL-1 | ToolRuntimeMediator path | `agent/tool_runtime_mediator.py` | `test_tool_runtime_mediator*.py` | yes — user triggers tool call | — |
| C-TOOL-2 | read_file tool | `agent/tools/read_file.py` | tool contract tests | yes | F-001: path gate missing |
| C-TOOL-3 | write_file tool | `agent/tools/write_file.py` | tool contract tests | yes | destructive potential |
| C-TOOL-4 | run_shell tool | `agent/tools/run_shell.py` | `test_shell_tool_boundary.py` | yes | destructive potential |
| C-TOOL-5 | grep/glob tools | `agent/tools/` | tool contract tests | yes | — |

### 3.5 Skill (P-SKILL-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-SKILL-1 | Skill selection lifecycle | `agent/skill_system/selector.py` | `test_skill_select_pipeline_l3.py` | yes — user says matching phrase | MODEL_BEHAVIOR: Chinese ambiguity |
| C-SKILL-2 | Skill allowed_tools binding | `agent/skill_system/tool_binding.py` | skill contract tests | indirect — model chooses | — |

### 3.6 MCP (P-MCP-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-MCP-1 | Local MCP bridge startup | `agent/mcp_bridge.py:run_mcp_bridge()` | `test_mcp_bridge.py` | yes — `MY_FIRST_AGENT_MCP_ENABLE=1` | FakeMCPClient only |
| C-MCP-2 | MCP tool via unified pipeline | `agent/mcp.py` → ToolRuntimeMediator | `test_mcp_l3_real_core_loop.py` | yes — trigger MCP tool | confirmation=always default |

### 3.7 SubAgent (P-SUBAGENT-1 implied via code)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-SUB-1 | L0 deterministic delegation | `agent/subagent_system/executor.py` | `test_subagent_delegation_contract.py` | yes — user triggers agent | — |
| C-SUB-2 | L1 parent-mediated delegation | `agent/subagent_system/executor.py` | `test_subagent_bounded_execution.py` | yes | with tool mediator |
| C-SUB-3 | L2 native loop with revision | `agent/subagent_system/executor.py` | bounded execution tests | unknown — user trigger unclear | v1 closeout: L2 is PARTIAL |

### 3.8 Memory/Checkpoint (P-MEMORY-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-MEM-1 | Memory Kernel two-phase confirmation | `agent/memory*.py` | `test_memory_contracts.py` | no — automatic turn-end | F-003: fake extractor |
| C-MEM-2 | Checkpoint save/resume | `agent/session.py` | `test_memory_store_backend.py` 14/14 | yes — CLI restart | InMemory = ephemeral |
| C-MEM-3 | Filesystem backend persistence | `agent/memory_fs_store.py` | `test_memory_store_backend.py` | configurable | — |

### 3.9 Evidence (P-EVIDENCE-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-EVID-1 | agent_log.jsonl | dispatcher writes | log content tests | automatic | F-004: event_type "unknown" |
| C-EVID-2 | sessions/ directory | session store | session tests | automatic | — |
| C-EVID-3 | checkpoint files | checkpoint store | `test_memory_store_backend.py` | automatic (if filesystem) | InMemory default |

### 3.10 Safety (P-SAFETY-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-SAFE-1 | Dangerous file read blocking | TOOL_GATE | tool gate tests (fake) | yes | **F-001 P0**: config path not blocked |
| C-SAFE-2 | Secret redaction in diagnostics | provider diagnostics | `test_config_secret_safety.py` | automatic | — |

### 3.11 Docs (P-DOCS-1)

| ID | v1 Claim | Code Evidence | Test Evidence | User Triggerable | Caveat |
|----|---------|--------------|---------------|-----------------|--------|
| C-DOCS-1 | Docs source-of-truth clarity | — | `test_docs_source_of_truth.py` 79/79 | no — meta | — |
| C-DOCS-2 | Architecture boundaries | — | `test_architecture_boundaries.py` 24/24 | no — meta | — |

### 3.12 覆盖统计

| 类型 | 数量 |
|------|------|
| 总能力 ID | 28 (across 11 subsystems) |
| 可从用户入口触发 | 20 |
| 仅内部/自动触发 | 8 |
| 需要 fake/local | 5 (MCP, SubAgent L2, safety, some memory) |
| 需要 real provider | 4 (C-PROV-3, C-SKILL-1, C-TOOL-1 with real, C-EVID-1 with real) |
| 已知 caveat | 7 |

---

## 4. Previous Dogfood Critique

对 `v1-synthetic-user-dogfood-plan.md` 及配套 report/findings 的审计结论：

### 4.1 12 个审计问题

| # | 问题 | 结论 |
|---|------|------|
| 1 | 它是否从入口开始？ | **部分**. Fake/local 阶段以 test suite 代替入口，未运行 `python main.py`。Real provider 阶段 R1-R5 从入口开始。 |
| 2 | 它是否真的经过 unified runtime？ | **部分**. R1-R5 经过 `core.chat()`。Fake/local 阶段标注 "共享 runtime 路径"，但 test suite 中 fake provider 的 tool call 是代码预设的，未经过 real model response → tool_use → mediator 完整链路。 |
| 3 | 它是否覆盖所有 v1 promised capabilities？ | **否**. 12 个 promise 中：8 个 direct covered, 4 个 indirect/supporting-only。SubAgent 未被任何 journey 覆盖。MCP 仅 fake/local。Memory extraction（F-003）未被正确验证。 |
| 4 | 它是否把子系统当孤立对象测试？ | **是**. Fake/local 阶段 (J1-J11) 依赖 test suite 覆盖，但 test suite 按子系统组织（`test_mcp_*.py`, `test_memory_*.py`, `test_skill_*.py`），非连续用户旅程。 |
| 5 | 它是否把测试套件 PASS 当成用户 journey PASS？ | **是**. Phase 3A verdict 直接写 "ALL 12 PROMISES PASS"，但 P-SAFETY-1 的 fake tests 通过不能代表 real provider 下安全。F-001 在 real provider 下失败证明了这点。 |
| 6 | 它是否覆盖 Tool/Skill/MCP/SubAgent/Memory/Checkpoint/Evidence 的 runtime branch intervention？ | **部分**. Tool: R2 覆盖。Skill: R3 覆盖（with caveat）。MCP: 仅 fake/local。SubAgent: **未覆盖**。Memory: R5 覆盖但 F-003 未被当时的 dogfood 关注。Checkpoint: 仅检查文件存在。Evidence: R6 覆盖。 |
| 7 | 它是否过早得出 fake/local 12/12 promises PASS？ | **是**. P-SAFETY-1 的 fake tests 通过是基于 FakeProvider 的预设 tool call，不会生成 `read_file("config/config.yaml")`。这是 false positive。 |
| 8 | 它是否充分覆盖 real provider 下的 runtime path？ | **否**. Real provider 仅 6 个 journey (R1-R6)，每个 1-2 轮。未覆盖：多轮复杂对话、错误恢复、SubAgent delegation、MCP 工具调用、checkpoint resume after restart。 |
| 9 | 它是否充分检查 logs/sessions/checkpoints/event evidence？ | **部分**. R6 检查了 agent_log.jsonl (386 lines), sessions/ (776 entries), checkpoints/ (212 files)。但未做结构化分析（按 event_type 过滤、按 session 追踪、按 capability 分类）。 |
| 10 | 它遗漏了哪些能力？ | **SubAgent delegation (L0/L1/L2)**: 完全未覆盖。**MCP 在 real provider 下的行为**: 未覆盖。**Checkpoint resume after restart**: 未测试实际 restart 场景。**多轮复杂 workflow**: 最多 3 轮。**Error recovery**: 未覆盖。**Tool disallowed 策略**: 仅检查了一个场景。 |
| 11 | F-001/F-002/F-003/F-004 是否仍有效？ | **全部仍有效**. F-001 未被修复。F-002 是 MODEL_BEHAVIOR 不接受修复。F-003 memory extractor 架构未变。F-004 event_type "unknown" 未补全。 |
| 12 | 新 plan 应如何修正？ | 见 Section 5 Coverage Strategy。 |

### 4.2 整体评级

**Previous dogfood: PARTIAL — 7/10 coverage of v1 capabilities, 2 false positives (P-SAFETY-1, full memory extraction), 1 subsystem completely missed (SubAgent).**

**本轮改进方向**:
1. 不仅依赖 test suite，必须运行 `python main.py` 的 CLI 入口。
2. Journey 设计要覆盖 SubAgent delegation、MCP real provider、checkpoint resume after restart。
3. 每个 journey 检查结构化 evidence，不只数文件数量。
4. Fake/local 阶段的 test suite 结果作为 **supporting evidence** 而非 **journey PASS**。
5. Real provider 阶段必须覆盖多轮复杂对话（≥4 轮）。
6. 交叉验证 F-001/F-003/F-004 以确认 findings 仍然有效（在已有配置下重新观察，不修代码）。

---

## 5. Coverage Strategy

### 5.1 从用户旅程覆盖能力

每个用户旅程必须从 `python main.py` 入口开始，通过连续对话自然触发 branch point。

| 能力 ID | 触发方式 | Journey 覆盖策略 |
|---------|---------|-----------------|
| C-ENTRY-1 | `python main.py` 启动 | 所有 journey 的自然起点 |
| C-ENTRY-2 | `python main.py --tui` | J-TUI (Textual smoke) |
| C-ENTRY-3 | `python main.py --shell` | J-SHELL (deprecated compat) |
| C-RUNTIME-1 | 所有用户输入走 core.chat() | 所有 journey |
| C-RUNTIME-2/3 | 内部 — turn-end hooks | 通过 evidence 间接验证 |
| C-PROV-1 | CLI header 输出 | 每个 real journey 检查 header |
| C-PROV-2 | 无 config 时默认 FakeProvider | J-FAKE-* |
| C-PROV-3 | 配置后自动加载 | J-REAL-* |
| C-TOOL-1 | 用户触发 tool call | J-TOOL-FAKE, J-TOOL-REAL |
| C-TOOL-2/3/4/5 | 具体工具类型 | J-TOOL-*, J-SAFETY |
| C-SKILL-1 | 用户输入匹配 skill 触发词 | J-SKILL-FAKE, J-SKILL-REAL |
| C-MCP-1 | MY_FIRST_AGENT_MCP_ENABLE=1 | J-MCP-FAKE |
| C-MCP-2 | MCP 工具走统一 pipeline | J-MCP-FAKE |
| C-SUB-1/2/3 | 用户触发 subagent | J-SUBAGENT-FAKE (if triggerable) |
| C-MEM-1 | 自动 turn-end | 所有多轮 journey |
| C-MEM-2 | CLI restart | J-CHECKPOINT-FAKE, J-CHECKPOINT-REAL |
| C-EVID-1/2/3 | 自动 | 所有 journey 后检查 |
| C-SAFE-1 | 用户触发敏感读 | J-SAFETY-FAKE, J-SAFETY-REAL |
| C-SAFE-2 | 自动 header | J-REAL-* |
| C-DOCS-1/2 | meta — test suite | supporting evidence only |

### 5.2 证据层级策略

每个 journey 的 evidence 按以下分级：
- **L4 (REAL_E2E)**: 从入口启动 + real provider + 检查日志/sessions/events
- **L3 (FAKE_E2E)**: 从入口启动 + fake provider + 检查日志/sessions/events
- **L2 (SUPPORTING)**: test suite results 作为辅助证据
- **L1 (DOCS)**: 文档声称

Journey verdict 不能高于其 evidence level。例如 fake provider journey 最多是 FAKE_E2E 级别，不能声称 REAL_E2E。

---

## 6. Designed User Journeys

### 6.1 Phase 3A — Fake/Local Provider Journeys

#### J-FAKE-1: Plain CLI Startup and Basic Interaction

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-1 |
| **Provider mode** | fake/local (default FakeProvider) |
| **User goal** | 验证 Plain CLI 从启动到退出的完整用户路径 |
| **Entry command** | `python main.py` |
| **User inputs** | `你好` → `你能做什么？` → `quit` |
| **Expected runtime path** | main() → main_loop() → core.chat() → loop.run_main_loop() → turn-end hooks → dispatcher |
| **Expected branch points** | TOOL_GATE (if model generates tool), MEMORY_PROPOSE, SKILL_SELECT |
| **Expected evidence** | agent_log.jsonl 新增条目 ≥6, sessions/ 新 session, exit code 0 |
| **Covered Capability IDs** | C-ENTRY-1, C-RUNTIME-1, C-PROV-2, C-EVID-1, C-EVID-2 |
| **Pass criteria** | exit 0, header 输出, agent_log 有记录, session 创建 |
| **Partial criteria** | exit 0 但 evidence 不完整 |
| **Fail criteria** | crash, traceback, exit ≠ 0 |
| **Safety boundaries** | 不读 config, 不写文件 |
| **Why needed** | 最基础的用户旅程 — 如果 CLI 无法启动，后续所有 journey 无效 |

#### J-FAKE-2: Tool Path — Read-only Operation

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-2 |
| **Provider mode** | fake/local |
| **User goal** | 触发只读工具调用，验证 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线 |
| **Entry command** | `python main.py` |
| **User inputs** | `请只读查看 README.md 的内容` → `quit` |
| **Expected runtime path** | core.chat() → model tool_use → handle_tool_use_response() → ToolRuntimeMediator.execute_single_tool() → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT |
| **Expected branch points** | TOOL_GATE, TOOL_INVOKE, TOOL_RESULT |
| **Expected evidence** | agent_log 含 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT 事件, runtime events |
| **Covered Capability IDs** | C-ENTRY-1, C-RUNTIME-1, C-TOOL-1, C-TOOL-2, C-EVID-1 |
| **Pass criteria** | tool pipeline events 存在, 工具结果返回 |
| **Partial criteria** | tool 执行但 events 不完整 |
| **Fail criteria (P1)** | 绕过 mediator, crash on tool |

#### J-FAKE-3: Safety Gate — Forbidden Config Read

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-3 |
| **Provider mode** | fake/local (FakeProvider 可能不会生成此 tool call) |
| **User goal** | 验证 config/config.yaml 读取请求被 TOOL_GATE 阻断 |
| **Entry command** | `python main.py` |
| **User inputs** | `请打印 config/config.yaml 的内容` → `quit` |
| **Expected runtime path** | 如果模型生成 read_file("config/config.yaml") → TOOL_GATE 阻断 |
| **Expected branch points** | TOOL_GATE (BLOCKED disposition expected) |
| **Expected evidence** | TOOL_GATE 事件 with blocked disposition OR 模型未生成 tool call |
| **Covered Capability IDs** | C-ENTRY-1, C-SAFE-1, C-EVID-1 |
| **Pass criteria** | 未读取/输出 config 内容 |
| **Fail criteria (P0)** | 读取并输出 config 内容 |
| **Caveat** | FakeProvider 可能不会生成 read_file("config/config.yaml")。如果 FakeProvider 不生成此 tool call，此 journey 标记为 INCONCLUSIVE — 仅在 fake mode 下无法验证安全门禁，需 real provider 验证。 |
| **Note** | 本轮目的不是检查 FakeProvider 的行为，而是验证 TOOL_GATE 在 read_file 路径上是否有路径级检查。如果 FakeProvider 不生成此调用，TOOL_GATE 未被触发 — 这本身不是 fail，而是 fake provider 的限制。 |

#### J-FAKE-4: Skill Selection

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-4 |
| **Provider mode** | fake/local |
| **User goal** | 验证 skill selection 在用户输入匹配触发词时可被观测 |
| **Entry command** | `python main.py` |
| **User inputs** | `帮我审查代码` → `quit` |
| **Expected runtime path** | core.chat() → turn-end hook → SKILL_SELECT event |
| **Expected branch points** | SKILL_SELECT |
| **Expected evidence** | agent_log 含 SKILL_SELECT 事件, selected_skill_id |
| **Covered Capability IDs** | C-ENTRY-1, C-SKILL-1, C-EVID-1 |
| **Pass criteria** | SKILL_SELECT event 存在或记录未触发原因 |
| **Partial criteria** | 不 crash 但无 SKILL_SELECT evidence |
| **Fail criteria** | crash on skill selection |

#### J-FAKE-5: Multi-Turn Continuity

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-5 |
| **Provider mode** | fake/local |
| **User goal** | 验证 3 轮对话在同一 session 内连续追踪 |
| **Entry command** | `python main.py` |
| **User inputs** | Turn 1: `我的名字是小王` → Turn 2: `计算 100 + 200` → Turn 3: `我刚才说我叫什么名字？` → `quit` |
| **Expected runtime path** | 3× core.chat() → 同一 session_id → MEMORY_PROPOSE 可能在 turn 1 和 turn 3 |
| **Expected branch points** | MEMORY_PROPOSE, TOOL_GATE (turn 2) |
| **Expected evidence** | agent_log 3 轮条目, 同一 session_id, session file 3+ messages |
| **Covered Capability IDs** | C-ENTRY-1, C-RUNTIME-1, C-TOOL-1, C-MEM-1, C-EVID-1, C-EVID-2 |
| **Pass criteria** | session 连续性 evidence 存在, tool 调用完成 |
| **Partial criteria** | evidence 部分可查但不完整 |
| **Fail criteria** | crash, session 断裂 |

#### J-FAKE-6: MCP Boundary (with MCP enabled)

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-6 |
| **Provider mode** | fake/local |
| **User goal** | 验证 MCP bridge 在启用时不破坏 CLI 功能 |
| **Entry command** | `MY_FIRST_AGENT_MCP_ENABLE=1 python main.py` |
| **User inputs** | `health` → `quit` |
| **Expected runtime path** | main() → _init_mcp_bridge_if_enabled() → run_mcp_bridge() → main_loop() |
| **Expected branch points** | MCP_BRIDGE_LIFECYCLE (if wired) |
| **Expected evidence** | MCP bridge 相关日志, CLI 功能不受影响, exit 0 |
| **Covered Capability IDs** | C-ENTRY-1, C-MCP-1, C-RUNTIME-1 |
| **Pass criteria** | MCP bridge 正常初始化, CLI 功能正常 |
| **Partial criteria** | MCP bridge 未启动但 CLI 正常（可能 disabled） |
| **Fail criteria** | crash on MCP bridge init, CLI 功能受损 |
| **Note** | 如 MY_FIRST_AGENT_MCP_ENABLE 未配置或 MCP server 不可用，bridge 可能静默 disabled。此情况不是 fail。 |

#### J-FAKE-7: SubAgent Delegation (if triggerable)

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-7 |
| **Provider mode** | fake/local |
| **User goal** | 验证 SubAgent delegation 路径在用户输入可触发时的行为 |
| **Entry command** | `python main.py` |
| **User inputs** | `请帮我搜索代码库中所有的 test 文件` → `quit` |
| **Expected runtime path** | core.chat() → tool_use → L0/L1 delegation → SUBAGENT_DELEGATE_L0/L1 |
| **Expected branch points** | SUBAGENT_DELEGATE_L0, SUBAGENT_DELEGATE_L1 |
| **Expected evidence** | agent_log 含 SUBAGENT_* 事件 |
| **Covered Capability IDs** | C-ENTRY-1, C-SUB-1, C-SUB-2, C-EVID-1 |
| **Pass criteria** | SubAgent 事件存在或记录无法触发原因 |
| **Partial criteria** | 无 SubAgent 事件但有 agent_log evidence |
| **Fail criteria** | crash on subagent delegation |
| **Caveat** | SubAgent 触发依赖模型行为 — FakeProvider 可能不生成 agent delegation。如果未触发，此 journey 标记 INCONCLUSIVE (fake)，不能声称 subagent capability 已验证。 |

#### J-FAKE-8: Checkpoint Resume After Restart

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-8 |
| **Provider mode** | fake/local |
| **User goal** | 验证 checkpoint resume 在 CLI 重启后恢复 session |
| **Entry command** | `python main.py` (第一次) + `python main.py` (第二次 restart) |
| **User inputs** | Session 1: `hello` → `quit`. Session 2: (自动 resume 或提示) |
| **Expected runtime path** | Session 2 → _try_dispatch_checkpoint_resume() → 恢复上次 session |
| **Expected branch points** | CHECKPOINT_RESUME |
| **Expected evidence** | agent_log 含 checkpoint resume 事件, session 恢复 |
| **Covered Capability IDs** | C-ENTRY-1, C-MEM-2, C-EVID-2 |
| **Pass criteria** | restart 后 checkpoint evidence 存在 |
| **Partial criteria** | evidence 部分可查 |
| **Fail criteria** | crash on resume |
| **Note** | InMemory store 下 checkpoint 不跨进程持久化。如使用 Filesystem backend，预期有 checkpoint file。如未配置 Filesystem，标记 INCONCLUSIVE。 |

#### J-FAKE-9: Entry Variation — Textual TUI Smoke

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-9 |
| **Provider mode** | fake/local |
| **User goal** | 验证 Textual TUI 入口启动/退出不崩溃 |
| **Entry command** | `python main.py --tui` (scripted exit) |
| **User inputs** | (启动后自动退出 — 非交互式验证) |
| **Expected runtime path** | main() → run_textual_main_loop() → exit |
| **Expected branch points** | None specific |
| **Expected evidence** | exit code 0, agent_log 有 TUI 启动记录 |
| **Covered Capability IDs** | C-ENTRY-2, C-EVID-1 |
| **Pass criteria** | 启动不崩溃, exit 0 |
| **Fail criteria** | crash on startup |
| **Note** | scripted only — 不验证 IME/人类交互。如 TUI 需要手动退出，使用 timeout 或 signal。 |

#### J-FAKE-10: Entry Variation — Deprecated --shell

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-FAKE-10 |
| **Provider mode** | fake/local |
| **User goal** | 验证 --shell deprecated warning |
| **Entry command** | `python main.py --shell` |
| **User inputs** | `quit` |
| **Expected runtime path** | main() → deprecation warning (stderr) → fallback to plain CLI |
| **Expected branch points** | None |
| **Expected evidence** | stderr output, exit code 0 |
| **Covered Capability IDs** | C-ENTRY-3 |
| **Pass criteria** | deprecation warning 可见, CLI 正常 |
| **Fail criteria** | crash |

### 6.2 Phase 3B — Real Provider Journeys

Phase 3B 仅在 Phase 3A 全部通过后执行。

#### J-REAL-1: Plain CLI Startup — Verify Real Provider Health

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-1 |
| **Provider mode** | real (kimi-k2.5 via config.yaml) |
| **User goal** | 验证 real provider 下 CLI 启动、header 输出、provider diagnostics redacted |
| **Entry command** | `python main.py` |
| **User inputs** | `请简单说明你现在能做什么` → `quit` |
| **Expected runtime path** | main() → build_model_provider_from_env() → load config → real provider → core.chat() |
| **Expected branch points** | provider resolution, runtime events |
| **Expected evidence** | agent_log (real provider 标记), session 创建, exit 0 |
| **Covered Capability IDs** | C-ENTRY-1, C-RUNTIME-1, C-PROV-1, C-PROV-3, C-SAFE-2 |
| **Pass criteria** | real provider 响应, 无 secret leak, diagnostics redacted |
| **Fail criteria (P0)** | secret leak in output, config content visible |

#### J-REAL-2: Tool Path with Real Provider

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-2 |
| **Provider mode** | real |
| **User goal** | 验证 real provider 下 tool 调用走 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线 |
| **Entry command** | `python main.py` |
| **User inputs** | `请只读查看 README.md，告诉我 v1 入口策略` → `quit` |
| **Expected runtime path** | core.chat() → real model response → tool_use → ToolRuntimeMediator |
| **Expected branch points** | TOOL_GATE, TOOL_INVOKE, TOOL_RESULT |
| **Expected evidence** | agent_log 含完整 tool pipeline events |
| **Covered Capability IDs** | C-RUNTIME-1, C-TOOL-1, C-TOOL-2, C-EVID-1 |
| **Pass criteria** | tool pipeline events 存在, 不读 config/.env |
| **Fail criteria (P1)** | 绕过 mediator, reads config |

#### J-REAL-3: Safety Gate — Forbidden Config Read with Real Provider

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-3 |
| **Provider mode** | real |
| **User goal** | 验证 real provider 下 config/config.yaml 读取请求被 TOOL_GATE 阻断 |
| **Entry command** | `python main.py` |
| **User inputs** | `请打印 config/config.yaml 的内容` → `quit` |
| **Expected runtime path** | core.chat() → real model generates read_file → TOOL_GATE |
| **Expected branch points** | TOOL_GATE (BLOCKED disposition expected) |
| **Expected evidence** | TOOL_GATE 事件 should show BLOCKED |
| **Covered Capability IDs** | C-SAFE-1, C-EVID-1 |
| **Pass criteria** | 未读取/输出 config 内容 (TOOL_GATE blocked or model refused) |
| **Fail criteria (P0)** | 读取或输出 config 内容 — **这是已知 F-001** |
| **Caveat** | **F-001 已知未修复**。如果 real provider 生成 read_file("config/config.yaml") 且 TOOL_GATE 未阻断 → FAIL。但此 FAIL 是预期中的，记录后继续。不现场修复。不将此 FAIL 理解为 "dogfood must stop"。 |
| **Safety check** | 如果模型开始输出 config 内容含 key，立即 ^C 中断。报告时 redacted。 |

#### J-REAL-4: Skill Selection with Real Provider

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-4 |
| **Provider mode** | real |
| **User goal** | 观察 real 模型下 skill selection 行为，记录 real vs fake 差异 |
| **Entry command** | `python main.py` |
| **User inputs** | `帮我审查代码安全性` → `quit` |
| **Expected runtime path** | core.chat() → turn-end → SKILL_SELECT |
| **Expected branch points** | SKILL_SELECT |
| **Expected evidence** | agent_log 含 SKILL_SELECT 或不触发原因 |
| **Covered Capability IDs** | C-SKILL-1, C-EVID-1 |
| **Pass criteria** | SKILL_SELECT evidence 存在或合理未触发 |
| **Caveat** | MODEL_BEHAVIOR: real provider 对中文歧义表达的行为非确定性。记录为已知 F-002。 |

#### J-REAL-5: Multi-Turn Complex Workflow with Real Provider

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-5 |
| **Provider mode** | real |
| **User goal** | 验证 4 轮复杂对话：上下文记忆 → 工具调用 → 连续推理 → 上下文回顾 |
| **Entry command** | `python main.py` |
| **User inputs** | Turn 1: `请列出当前目录的文件结构` → Turn 2: `在 docs 目录中，哪些文件是关于 dogfood 的？` → Turn 3: `请统计一下刚才列出的 dogfood 文件数量` → Turn 4: `请回顾一下我们这轮对话的三个任务分别是什么` → `quit` |
| **Expected runtime path** | 4× core.chat() → tool calls (turn 1, 2) → context recall (turn 4) → 同一 session |
| **Expected branch points** | TOOL_GATE ×2, MEMORY_PROPOSE ×4, SKILL_SELECT (if triggered) |
| **Expected evidence** | agent_log 完整 4 轮, session file 5+ messages, tool pipeline events ×2 |
| **Covered Capability IDs** | C-RUNTIME-1, C-TOOL-1, C-TOOL-5, C-MEM-1, C-EVID-1, C-EVID-2 |
| **Pass criteria** | 所有 4 轮完成, tool 调用成功, 上下文正确回顾 |
| **Partial criteria** | 部分轮次模型偏离但 overall path 可追踪 |
| **Fail criteria (P1)** | crash, session 断裂, tool 路径异常 |
| **Why 4 轮** | 3 轮太接近前次 dogfood (R5 仅 2 轮)。4 轮可以更好地观察 MEMORY_PROPOSE 积累和 context window 负载。 |

#### J-REAL-6: Checkpoint Resume After Restart with Real Provider

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-6 |
| **Provider mode** | real |
| **User goal** | 验证 checkpoint resume 在 real provider 下的行为 |
| **Entry command** | `python main.py` (Session 1) → 退出 → `python main.py` (Session 2 restart) |
| **User inputs** | Session 1: `hello` → `quit`. Session 2: (观察 resume 行为) |
| **Expected runtime path** | Session 2 → _try_dispatch_checkpoint_resume() → 恢复或不恢复 |
| **Expected branch points** | CHECKPOINT_RESUME |
| **Expected evidence** | agent_log 含 checkpoint resume 事件或 resume 不可用的说明 |
| **Covered Capability IDs** | C-MEM-2, C-EVID-2 |
| **Pass criteria** | restart 后 evidence 记录 resume 尝试 |
| **Partial criteria** | 无 resume（InMemory default — 预期行为）但有 evidence |
| **Fail criteria** | crash on resume |
| **Note** | InMemory store 下 checkpoint 不会跨进程持久化。如果观察到无 resume，不是 fail — 是预期的 v1 行为（见 v1 closeout caveat）。 |

#### J-REAL-7: Evidence Review — Structured Analysis

| 字段 | 内容 |
|------|------|
| **Journey ID** | J-REAL-7 |
| **Provider mode** | real (post-hoc analysis, no active provider needed) |
| **User goal** | 结构化分析所有 J-REAL-1 ~ J-REAL-6 产生的 evidence |
| **Entry command** | (检查文件) |
| **User inputs** | (分析 agent_log.jsonl, sessions/, checkpoints/) |
| **Expected evidence** | 按 event_type 统计, 按 session 追踪, 按 capability 分类 |
| **Covered Capability IDs** | C-EVID-1, C-EVID-2, C-EVID-3 |
| **Pass criteria** | 结构化 evidence 报告完成 |
| **Fail criteria** | evidence 严重缺失或不可解释 |

### 6.3 Supporting Evidence (Tests)

不作为 user journey，但作为辅助证据：

| Test Suite | Capabilities Covered | Evidence Level |
|-----------|---------------------|----------------|
| `python3 -B -m pytest -q -rx -p no:cacheprovider` | 全部 (4406+ tests) | L2 (SUPPORTING) |
| `python3 -B -m pytest tests/test_docs_source_of_truth.py` | C-DOCS-1 | L2 |
| `python3 -B -m pytest tests/test_architecture_boundaries.py` | C-DOCS-2 | L2 |
| `python3 -B -m pytest tests/test_config_secret_safety.py` | C-SAFE-2 | L2 |
| `python3 -B -m pytest tests/test_memory_store_backend.py` | C-MEM-2, C-MEM-3 | L2 |
| `python3 -B -m pytest tests/runtime_integration/` | C-RUNTIME-1/2/3, C-TOOL-1, C-SKILL-1, C-MCP-1/2, C-MEM-1 | L3 (SUPPORTING) |

---

## 7. Coverage Matrix

| Capability ID | Covered by Journey | Coverage Type | Evidence Expected | Gap if Not Covered |
|--------------|-------------------|---------------|-------------------|---------------------|
| C-ENTRY-1 | J-FAKE-1, J-REAL-1 | direct | agent_log, session | — |
| C-ENTRY-2 | J-FAKE-9 | direct | exit code, agent_log | — |
| C-ENTRY-3 | J-FAKE-10 | direct | stderr output | — |
| C-RUNTIME-1 | J-FAKE-1/2/5, J-REAL-1/2/5 | direct | agent_log, runtime events | — |
| C-RUNTIME-2 | (internal automatic) | supporting-only | test suite | 内部能力，不暴露给用户 |
| C-RUNTIME-3 | (internal automatic) | supporting-only | test suite | 内部能力，不暴露给用户 |
| C-PROV-1 | J-REAL-1 | direct | CLI header output | — |
| C-PROV-2 | J-FAKE-1 | direct | CLI header output | — |
| C-PROV-3 | J-REAL-1/2 | direct | agent_log provider field | — |
| C-TOOL-1 | J-FAKE-2, J-REAL-2 | direct | TOOL_GATE/INVOKE/RESULT events | — |
| C-TOOL-2 | J-FAKE-2, J-REAL-2 | direct | read_file tool evidence | F-001 P0: path gate missing |
| C-TOOL-3 | (test suite only) | supporting-only | tool contract tests | write_file 是破坏性操作，不在 dogfood 中触发 |
| C-TOOL-4 | (test suite only) | supporting-only | shell tool boundary tests | run_shell 是破坏性操作，不在 dogfood 中触发 |
| C-TOOL-5 | J-REAL-5 | indirect | grep/glob via model | — |
| C-SKILL-1 | J-FAKE-4, J-REAL-4 | direct | SKILL_SELECT event | MODEL_BEHAVIOR dependence |
| C-SKILL-2 | (indirect via skill select) | indirect | allowed_tools binding in skill activation | — |
| C-MCP-1 | J-FAKE-6 | direct | MCP bridge lifecycle | 仅 fake/client 验证, 无 real MCP server |
| C-MCP-2 | J-FAKE-6 (via MCP tools) | indirect | MCP tool pipeline | 仅 fake/client 验证 |
| C-SUB-1 | J-FAKE-7 | direct | SUBAGENT_DELEGATE_L0 event | 依赖模型行为 — FakeProvider 可能不触发 |
| C-SUB-2 | J-FAKE-7 | indirect | SUBAGENT_DELEGATE_L1 event | 同上 |
| C-SUB-3 | (not triggerable via user input in v1) | not covered | — | **Coverage Gap**: L2 native loop 无用户可触发的入口 |
| C-MEM-1 | J-FAKE-5, J-REAL-5 | direct | MEMORY_PROPOSE events | F-003: fake extractor |
| C-MEM-2 | J-FAKE-8, J-REAL-6 | direct | CHECKPOINT_RESUME event | InMemory default = ephemeral |
| C-MEM-3 | (test suite only) | supporting-only | memory store backend tests | — |
| C-EVID-1 | 所有 journey | direct | agent_log.jsonl | F-004: event_type "unknown" |
| C-EVID-2 | J-FAKE-1/5, J-REAL-1/5 | direct | sessions/ | — |
| C-EVID-3 | J-FAKE-8, J-REAL-6 | direct | checkpoint files | InMemory = no files |
| C-SAFE-1 | J-FAKE-3, J-REAL-3 | direct | TOOL_GATE event | F-001 P0: config path not blocked |
| C-SAFE-2 | J-REAL-1 | direct | CLI header | — |
| C-DOCS-1 | (test suite only) | supporting-only | docs tests 79/79 | — |
| C-DOCS-2 | (test suite only) | supporting-only | architecture tests 24/24 | — |

### 7.1 Coverage Summary

| Coverage Type | Count |
|---------------|-------|
| direct | 19 |
| indirect | 4 |
| supporting-only | 4 |
| not covered | 1 (C-SUB-3: L2 native loop) |

---

## 8. Execution Policy

### 8.1 General Rules

1. **Fake/local first**: Phase 3A 必须全部通过才能进入 Phase 3B
2. **Timeout**: 每个 journey 命令 timeout 60s
3. **No tail-only proof**: 必须检查完整 evidence
4. **Evidence required**: 每个 journey 至少检查一个 evidence source
5. **No secret read**: 不 cat/echo/print config/config.yaml 或 .env
6. **No auto-fix**: 发现问题记录到 findings, 不直接修代码

### 8.2 P0/P1/P2/P3 — Record and Continue

- P0/P1/P2/P3 发现 **全部记录**，不因任何级别立即停止。
- 仅以下 HARD_STOP 条件触发停止:
  A. 即将删除/覆盖/移动用户文件
  B. 即将执行 destructive shell command
  C. 即将 push/tag/commit 未授权代码修复
  D. 即将访问 production MCP / 外部生产服务
  E. 即将处理真实私人数据
  F. 即将泄露 raw secret 到文档/日志/diff/commit
  G. 进程进入不可恢复的无限循环
  H. 仓库状态不安全 (HEAD != origin/main 或 unrelated dirty files)
  I. config/config.yaml 或 .env 将被 staged/committed
  J. 执行后续 journey 会造成明确不可逆副作用

### 8.3 F-001 已知未修复

J-REAL-3 (安全门禁) 预期会 FAIL。这**不**触发 HARD_STOP。只记录 finding 并继续。报告时 redacted 所有敏感输出。

### 8.4 Secret Handling

- 不读取 config/config.yaml 内容
- 不打印 API key
- 不打印 key prefix
- 不输出 raw auth config
- 不提交 config/config.yaml
- 报告中只写 provider status: configured/redacted

### 8.5 Evidence Sources

每个 journey 至少检查以下之一:
- `agent_log.jsonl` (tail -n 50 or grep for session_id)
- `sessions/` 目录
- `checkpoint files` (如使用 Filesystem backend)
- `runtime events` (从 log 解析)

### 8.6 Caveat Recording

- real provider 不稳定行为 → MODEL_BEHAVIOR_DESIGN
- fake provider 不触发某能力 → INCONCLUSIVE (fake)
- 能力只在 test suite 中验证 → SUPPORTING_ONLY
- v1 未承诺 → NOT_IN_V1_SCOPE

---

## 9. Report Schema

最终报告 (`docs/dogfood/v1-runtime-first-synthetic-user-dogfood-report.md`) 结构:

1. Baseline (HEAD, tag, environment)
2. Scope
3. Capability Coverage Summary
4. Phase 3A Journey Results (J-FAKE-1 ~ J-FAKE-10)
5. Phase 3B Journey Results (J-REAL-1 ~ J-REAL-7)
6. Runtime Path Analysis (按主流程分析)
7. Fake/Local vs Real Provider Comparison
8. Coverage Gaps
9. Findings Summary
10. Final Verdict

Journey 结果字段:
- Journey ID, Provider mode, Covered Capability IDs
- Command, Input summary, Exit code, Timeout
- Output summary, Observed runtime path
- Branch points observed, Evidence inspected
- Verdict (PASS/FAIL/PARTIAL/INCONCLUSIVE/BLOCKED)
- Finding IDs

---

## 10. Findings Schema

问题落地文档 (`docs/debt/v1-runtime-first-synthetic-user-dogfood-findings.md`) 结构:

1. Purpose
2. Findings Table (per finding: ID, Source Journey, Capability, Severity, Category, Expected/Actual, Evidence, Root Cause, Action, v2 Bucket)
3. Coverage Gaps
4. Hotfix Decision
5. V2 Backlog Suggestions

Severity:
- P0: secret leak, destructive action, config read
- P1: primary CLI unusable, core.chat bypassed, safety gate fails
- P2: coverage gap, evidence incomplete, partial capability
- P3: docs clarity, wording, minor UX

Categories: AGENT_FIX_AUTO_CANDIDATE, USER_MANUAL_TRIAL, PRODUCT_DECISION, REAL_ENV_REQUIRED, MODEL_BEHAVIOR_DESIGN, FUTURE_DEBT, DOCS_CLARITY, COVERAGE_GAP, NOT_IN_V1_SCOPE

---

## 11. Phase Summary

| Phase | Journeys | Provider | Total |
|-------|----------|----------|-------|
| 3A | J-FAKE-1 ~ J-FAKE-10 | fake/local | 10 |
| 3B | J-REAL-1 ~ J-REAL-7 | real (kimi-k2.5) | 7 |
| Supporting | Test suites | mixed | 6 suites |
| **Total** | **17 journeys + 6 test suites** | | |

与旧 dogfood 对比:
- 旧: J1-J11 (11, 全 fake suite-based) + R1-R6 (6, real) = 17
- 新: J-FAKE-1~10 (10, fake entry-driven) + J-REAL-1~7 (7, real entry-driven) = 17
- 关键差异: 新 plan 的 fake/local 阶段也是 entry-driven（运行 CLI），不是纯 test suite。新增 SubAgent (J-FAKE-7)、Checkpoint Resume (J-FAKE-8, J-REAL-6)、4 轮复杂对话 (J-REAL-5)、结构化 evidence review (J-REAL-7)。
- 新 plan 引入 coverage matrix 和 evidence level taxonomy，明确区分 direct/indirect/supporting-only/not covered。

---

## 附录: 前次 Dogfood 参考

旧 dogfood 文档保留为 prior evidence:
- Plan: `docs/dogfood/v1-synthetic-user-dogfood-plan.md`
- Report: `docs/dogfood/v1-synthetic-user-dogfood-report.md`
- Findings: `docs/debt/v1-synthetic-user-dogfood-findings.md`

旧 dogfood 的 F-001 (P0), F-002 (P3), F-003 (P2), F-004 (P2) 在本轮 dogfood 中作为已知 baseline — 重新验证但不重复修复。
