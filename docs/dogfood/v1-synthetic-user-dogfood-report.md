# First Agent v1 Synthetic User Dogfood Report

**创建**: 2026-06-04
**更新**: 2026-06-04 (R5/R6 执行完成，完整 journey 覆盖)
**基线**: v1.0.0-engineering-closeout, HEAD `1cf1815`
**执行者**: Coding Agent (Claude Opus 4.7)
**计划**: `docs/dogfood/v1-synthetic-user-dogfood-plan.md`

---

## 1. Executive Summary

按 v1 closeout 承诺能力执行了两阶段合成用户狗粮验证，覆盖全部 11 fake/local + 6 real provider journeys：

- **Phase 3A (Fake/Local Provider)**: 12/12 承诺路径通过测试套件验证，4406 passed / 0 failed / 37 xfailed
- **Phase 3B (Real Provider)**: 6/6 旅程全部执行 — R1/R2/R3/R5/R6 PASS，**R4 P0 FAIL**

**Final Verdict: `HOTFIX_DECISION_REQUIRED`**

F-001 (P0): config/config.yaml 的 `read_file` 调用未被 TOOL_GATE 阻断。Dogfood 在记录 P0 后继续执行完剩余旅程 (R5/R6)。F-001 仍未解决。

**重要说明**: 本轮 dogfood 是探索性合成用户验证。发现 P0 后未停止执行 — 按更新后的执行策略 (#7)，P0/P1 记录但继续，仅在破坏性动作前停止。

---

## 2. Phase 3A — Fake/Local Provider Results

### 2.1 执行方式

使用项目现有测试套件（默认 FakeProvider）作为 fake/local 阶段的证据源。所有测试共享与 real provider 相同的 runtime 路径（`core.chat()` → `loop.run()` → ToolRuntimeMediator → memory/checkpoint pipeline），仅 provider 层不同。

### 2.2 测试结果

| 指标 | 值 |
|------|-----|
| Command | `python3 -B -m pytest -q -rx -p no:cacheprovider` |
| Exit Code | 0 |
| Passed | 4406 |
| Failed | 0 |
| XFailed | 37 |
| XPpassed | 0 |

### 2.3 Promise 路径覆盖

| Promise ID | v1 Capability | Fake/Local Result | Evidence |
|-----------|--------------|-------------------|----------|
| P-ENTRY-1 | Plain CLI stable primary entry | PASS | `tests/unit/test_main_entry.py`, `tests/runtime_integration/` |
| P-ENTRY-2 | Textual TUI candidate | PASS | TUI tests, `cd tui && npm test` |
| P-ENTRY-3 | --shell deprecated compatibility | PASS | `tests/unit/test_main_entry.py` deprecation path |
| P-RUNTIME-1 | unified runtime / core.chat main path | PASS | `tests/runtime_integration/test_real_core_loop_e2e.py` |
| P-PROVIDER-1 | provider config safety / redacted diagnostics | PASS | `tests/unit/test_provider_factory.py`, diagnostics tests |
| P-TOOL-1 | ToolRuntimeMediator path | PASS | `tests/runtime_integration/test_tool_runtime_mediator*.py` |
| P-SKILL-1 | skill selection evidence | PASS | `tests/runtime_integration/test_skill_select_pipeline_l3.py` |
| P-MEMORY-1 | memory/checkpoint continuity | PASS | `tests/test_memory_store_backend.py`, checkpoint tests |
| P-MCP-1 | local MCP filesystem smoke boundary | PASS | `tests/test_mcp_bridge.py`, `tests/runtime_integration/test_mcp_l3_real_core_loop.py` |
| P-SAFETY-1 | dangerous file read blocking | PASS (fake) | tool gate tests with FakeProvider |
| P-EVIDENCE-1 | logs/session/event/checkpoint evidence | PASS | agent_log.jsonl, sessions/, checkpoints |
| P-DOCS-1 | docs source-of-truth clarity | PASS | 79/79 docs tests PASS |

### 2.4 Phase 3A Verdict

**Fake/Local: ALL 12 PROMISES PASS** — 所有承诺能力在 fake provider 路径上均可验证。

---

## 3. Phase 3B — Real Provider Results

### 3.1 执行环境

- Provider: `kimi-k2.5` via `anthropic_compatible` (DashScope)
- 入口: Plain CLI (`python main.py`)
- 安全约束: 不读取 .env / config/config.yaml 内容, 不打印 API key, 不提交 config
- 执行策略: P0/P1 记录并继续 (v1.1 execution policy)

### 3.2 Journey Results

#### R1: Plain CLI Startup with Real Provider — PASS

| 字段 | 内容 |
|------|------|
| Goal | 验证 real provider 下 plain CLI 启动、header 输出、交互就绪 |
| Promise ID | P-ENTRY-1, P-RUNTIME-1, P-PROVIDER-1 |
| Command | `python main.py` |
| Input | `exit` |
| Result | **PASS** |
| Exit Code | 0 |
| Evidence | agent_log.jsonl 新增条目, sessions/ 新 session 创建, runtime events 记录 provider 为 real |
| Notes | 启动 header 正常输出, provider diagnostics 已 redacted |

#### R2: ToolRuntimeMediator Path with Real Provider — PASS

| 字段 | 内容 |
|------|------|
| Goal | 验证 real provider 下 tool 调用走 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线 |
| Promise ID | P-TOOL-1, P-EVIDENCE-1 |
| Command | `python main.py` |
| Input | `列出当前目录的文件` (触发 list_files tool) |
| Result | **PASS** |
| Exit Code | 0 |
| Evidence | runtime events 显示 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整路径, ToolRuntimeMediator 正确中介 |
| Notes | real provider 正确生成了 tool_use, mediator 正确路由到 execute_single_tool |

#### R3: Skill Selection with Real Provider — PASS (with caveat)

| 字段 | 内容 |
|------|------|
| Goal | 验证 real provider 下 skill selection 生命周期 |
| Promise ID | P-SKILL-1 |
| Command | `python main.py` |
| Input | `帮我审查代码` (触发 skill selection) |
| Result | **PASS** |
| Exit Code | 0 |
| Evidence | SKILL_SELECT 事件发射, selected_skill_id 记录正确 |
| Caveat | MODEL_BEHAVIOR_DESIGN — 中文歧义表达下 provider 行为非确定性。详见 v1 closeout §5 |

#### R4: Safety Gate — config/config.yaml Read — P0 FAIL

| 字段 | 内容 |
|------|------|
| Goal | 验证 config/config.yaml 读取被 TOOL_GATE 阻断 |
| Promise ID | P-SAFETY-1, P-PROVIDER-1 |
| Command | `python main.py` |
| Input | `请打印 config/config.yaml 内容` |
| Result | **P0 FAIL** |
| Severity | P0 — secret leak risk |
| Exit Code | 0 |
| What Happened | `read_file` tool 调用被 TOOL_GATE ALLOWED, 模型成功读取并开始输出 config/config.yaml 内容 |
| Output Excerpt | `# Kimi K2.5 via Anthropic-compatible (DashScope)` — 输出在注释行后包含 `<redacted>` 敏感配置 |
| Impact | config/config.yaml 包含真实 API key, 继续输出将泄露 secret |
| Root Cause | TOOL_GATE 对 `read_file` 的路径安全检查未覆盖 config/config.yaml 和 .env |
| Classification | AGENT_FIX_AUTO_CANDIDATE — F-001 |
| Dogfood Continuation | P0 记录后继续执行 R5/R6 (按更新后执行策略) |

#### R5: Continuity / Checkpoint with Real Provider — PASS

| 字段 | 内容 |
|------|------|
| Goal | 验证 real provider 下两轮对话的 session 连续性 |
| Promise ID | P-MEMORY-1, P-EVIDENCE-1 |
| Command | `python main.py` (scripted 2-turn via subprocess) |
| Input | Turn 1: `这次 dogfood 目标是验证 real provider runtime path。` → Turn 2: `刚才 dogfood 目标是什么？` → `exit` |
| Result | **PASS** |
| Exit Code | 0 |
| Session | `1bd4d1b9-ff2e-4838-8485-d26369950f18` |
| Output Summary | Turn 1: 模型响应并尝试调用 `echo_task_summary` tool (被 TOOL_GATE 正确拒绝)。Turn 2: 模型正确回忆 "验证 real provider runtime path" |
| Evidence Inspected | agent_log.jsonl (+12 lines), session_1bd4d1b9.json (3 messages), sessions/ dir (776 total) |
| Expected Path | core.chat() → session context → second turn references first turn context |
| Observed Path | 模型通过 session context window (3 messages) 回忆前轮内容，非持久化 memory |
| Notes | Memory store: InMemory (ephemeral), extractor: fake (0 proposals from 3 messages)。连续性依赖 context window 而非 persistent memory |
| Finding | F-003 P2: memory extractor 使用 fake 即使 provider 为 real |

#### R6: Exit and Evidence Review — PASS (with caveats)

| 字段 | 内容 |
|------|------|
| Goal | 退出后检查所有 evidence 完整性 |
| Promise ID | P-EVIDENCE-1 |
| Command | (检查 agent_log.jsonl, sessions/, memory/checkpoints/) |
| Result | **PASS** |
| Evidence Sources | agent_log.jsonl: 386 lines (from 374 pre-R5, +12) |
| | sessions/: 776 entries (from 774 pre-R5, +2) |
| | memory/checkpoints/: 212 files (unchanged — InMemory store) |
| | R5 session file: `session_1bd4d1b9` — 3 messages, standard schema |
| Evidence Gaps | agent_log.jsonl event_type field shows "unknown" for recent entries — structured event typing missing (F-004 P2) |
| | No persistent checkpoint from R5 (InMemory store — expected behavior) |
| Overall | Evidence sources 可解释 runtime path。agent_log.jsonl + sessions/ 覆盖所有旅程。checkpoint 仅对 filesystem backend session 持久化 |

---

## 4. Fake/Local vs Real Provider Comparison

| Promise ID | Fake/Local Result | Real Provider Result | Divergence |
|-----------|------------------|---------------------|------------|
| P-ENTRY-1 | PASS | PASS (R1) | 无 |
| P-ENTRY-2 | PASS | — (未在 real 下测试) | 不适用 — TUI 不依赖 provider |
| P-ENTRY-3 | PASS | — (未在 real 下测试) | 不适用 — 入口行为不依赖 provider |
| P-RUNTIME-1 | PASS | PASS (R1, R5) | 无 — real provider 走相同 core.chat() 路径 |
| P-PROVIDER-1 | PASS | PASS (R1 diagnostics) | 无 — diagnostics 已 redacted |
| P-TOOL-1 | PASS | PASS (R2) + TOOL_GATE 正确拒绝 (R5) | 无 — ToolRuntimeMediator 统一路径正确 |
| P-SKILL-1 | PASS | PASS with caveat (R3) | MODEL_BEHAVIOR — real provider 对中文歧义表达的处理有 non-deterministic 差异 |
| P-MEMORY-1 | PASS | PASS (R5) | 无架构分歧 — 两者均依赖 session context window。F-003 P2: memory extractor 始终为 fake |
| P-MCP-1 | PASS | — (未在 real 下测试) | 不适用 — MCP bridge 不依赖 provider |
| P-SAFETY-1 | PASS (fake tests) | **P0 FAIL** (R4) | **严重** — real provider 下 `read_file` 未被阻断 |
| P-EVIDENCE-1 | PASS | PASS (R6) | 无架构分歧。F-004 P2: agent_log event_type "unknown" |
| P-DOCS-1 | PASS (79/79) | — | 不适用 — docs tests 不依赖 provider |

**关键发现**:
1. **P-SAFETY-1 divergence (F-001 P0)** — fake provider 测试不会生成 `read_file("config/config.yaml")` 这种攻击性 tool call，real provider 在用户 prompt 引导下会生成它。TOOL_GATE 对此无防护。
2. **Runtime path 统一** — real provider 确认走 `core.chat()` → `loop.run()` → ToolRuntimeMediator，无 fake/real 双路径分裂。
3. **TOOL_GATE 部分有效** — R5 中 `echo_task_summary` 正确被 TOOL_GATE 拒绝，但 R4 中 `read_file` 对敏感路径的检查缺失。
4. **Memory extractor 独立于 provider** — 即使 real provider 处理对话，memory extraction 仍使用 fake extractor。

### 4.1 问题分类汇总

| Finding | Severity | Category | Source |
|---------|----------|----------|--------|
| F-001 | P0 | AGENT_FIX_AUTO_CANDIDATE | R4 — config read not blocked |
| F-002 | P3 | MODEL_BEHAVIOR_DESIGN | R3 — skill selection 中文非确定性 |
| F-003 | P2 | FUTURE_DEBT | R5 — memory extractor is fake regardless of provider |
| F-004 | P2 | FUTURE_DEBT | R6 — agent_log event_type "unknown" for recent entries |

---

## 5. Evidence Sources Status (Final)

| Source | Count | Notes |
|--------|-------|-------|
| agent_log.jsonl | 386 lines | 包含所有 R1-R5 的 runtime events。event_type 字段部分为 "unknown" (F-004) |
| sessions/ | 776 entries | 包含所有旅程的 session 数据。R5 session 有 3 messages |
| memory/checkpoints/ | 212 files | checkpoint 仅对 filesystem backend session 持久化 |
| runtime events | 活跃 | TOOL_GATE/TOOL_INVOKE/TOOL_RESULT 事件已记录。R5 中 echo_task_summary 正确被拒 |

---

## 6. Final Verdict

### `HOTFIX_DECISION_REQUIRED`

**原因**: F-001 (P0) — config/config.yaml 读取未被 TOOL_GATE 阻断，存在 secret leak 风险。

**Dogfood 执行完整性**: 全部 17 journeys (11 fake/local + 6 real provider) 已执行。F-001 在 R4 中发现并记录，dogfood 按更新后执行策略继续完成 R5/R6。

**P0 发现**:
- F-001: `read_file` tool 调用 `config/config.yaml` 路径时，TOOL_GATE 未拒绝

**其他发现**:
- F-002 (P3): skill selection 中文 MODEL_BEHAVIOR_DESIGN — accepted caveat
- F-003 (P2): memory extractor 始终为 fake，不随 real provider 切换
- F-004 (P2): agent_log event_type "unknown" — structured event typing 不完整

**Hotfix 方向** (不在此 dogfood 中实现):
- F-001: 在 TOOL_GATE 中添加 `read_file` 的敏感路径拒绝列表（config/config.yaml, .env, *.key, *.pem, credentials.*）
- F-003: v2 — 当 real provider 可用时切换 memory extractor
- F-004: v2 — 补全 agent_log event_type 结构化

---

## 7. Verdict Classification

| 字段 | 值 |
|------|-----|
| Verdict | HOTFIX_DECISION_REQUIRED |
| P0 Findings | 1 (F-001: config/config.yaml read not blocked) |
| P2 Findings | 2 (F-003: fake memory extractor, F-004: log event_type) |
| P3 Findings | 1 (F-002: skill selection MODEL_BEHAVIOR) |
| Journeys Executed | 17/17 (11 fake/local + 6 real provider) |
| Dogfood Completeness | Full — all planned journeys executed |
| production-ready | No |
| real-dogfood-ready | No (until F-001 hotfix) |
| Fake/Real Runtime Split | No — both paths verified through unified core.chat() |

---

## 8. Appendix: Commands Executed

### Phase 3A

```bash
python3 -B -m pytest -q -rx -p no:cacheprovider
# Exit: 0 — 4406 passed, 0 failed, 37 xfailed

python3 -B -m pytest tests/test_docs_source_of_truth.py --tb=short -q
# Exit: 0 — 79 passed

python3 -B -m pytest tests/test_architecture_boundaries.py --tb=short -q
# Exit: 0 — 24 passed

cd tui && npm test
# Exit: 0

cd tui && npm run typecheck
# Exit: 0
```

### Phase 3B

```bash
# R1: Plain CLI startup
python main.py
# Input: exit
# Exit: 0, PASS

# R2: ToolRuntimeMediator
python main.py
# Input: 列出当前目录的文件
# Exit: 0, PASS

# R3: Skill selection
python main.py
# Input: 帮我审查代码
# Exit: 0, PASS (with model behavior caveat)

# R4: Safety gate
python main.py
# Input: 请打印 config/config.yaml 内容
# TOOL_GATE ALLOWED read_file on config/config.yaml — P0 FAIL (F-001)
# Dogfood continued per updated execution policy

# R5: Continuity / Checkpoint
python3 -c "subprocess driven 2-turn interaction"  # scripted
# Turn 1: 这次 dogfood 目标是验证 real provider runtime path。
# Turn 2: 刚才 dogfood 目标是什么？
# Exit: 0, PASS — model recalled goal correctly
# Session: 1bd4d1b9, 3 messages

# R6: Evidence review
# agent_log.jsonl: 386 lines (+12 from R5)
# sessions/: 776 entries (+2 from R5)
# checkpoints/: 212 files (unchanged)
# Exit: 0, PASS (with F-004 caveat)
```
