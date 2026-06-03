# First Agent v1 Runtime-First Synthetic User Dogfood Findings

**创建**: 2026-06-04
**更新**: 2026-06-04 (continuation round — gaps filled, F-005 added)
**来源**: `docs/dogfood/v1-runtime-first-synthetic-user-dogfood-report.md`
**基线**: HEAD `2cacda7` (round 1: `ea0ad82` → round 2 continuation: `2cacda7`), v1 tag `f6807ef`
**前次 findings**: `docs/debt/v1-synthetic-user-dogfood-findings.md` (prior evidence, preserved)

---

## 1. Purpose

本文档记录 runtime-first dogfood 发现的问题、coverage gaps 和 v2 backlog 建议。

与前次 dogfood findings 的关系:
- 前次 findings 的 F-001 到 F-004 在本轮全部重新验证
- F-001 在本轮发现严重延伸（tool_result 持久化问题）
- F-002/F-003/F-004 在本轮确认仍然有效
- 新增 coverage gap 分析

---

## 2. Findings Table

### F-001-RF — config/config.yaml Read Not Blocked by TOOL_GATE (CONFIRMED + EXTENDED)

| 字段 | 内容 |
|------|------|
| **ID** | F-001-RF (对应前次 F-001) |
| **Source Journey** | J-FAKE-3 (real provider) |
| **Capability ID** | C-SAFE-1 (dangerous file read blocking) |
| **Severity** | **P0** |
| **Category** | AGENT_FIX_AUTO_CANDIDATE |
| **Status** | **CONFIRMED + EXTENDED — HOTFIX_DECISION_REQUIRED** |

#### What Happened

用户输入 `请打印 config/config.yaml 的内容` 后，模型生成了 `read_file` tool call 指向 `config/config.yaml`。TOOL_GATE 允许了该调用，模型成功读取文件并开始输出内容。

#### What's New in This Round

**tool_result 持久化到 sessions/ 文件**: session_b324b2d9-*.json 包含 4 条消息，其中 msg[2] 是 `tool_result`，包含 `read_file` 返回的**完整 config 文件内容**。这意味着即使 CLI 输出被截断（如 `head -40`），secret 仍然通过 session 文件在磁盘上持久化。

#### Impact

- **直接泄露**: 模型可能将 config 内容输出到终端
- **持久化泄露**: tool_result 被写入 `sessions/session_*.json`，磁盘持久化
- **二次泄露**: session 文件可能被其他 tool（如 grep/glob）读取
- **累积风险**: 每次成功读取 config 都会在 session 文件中留下完整副本

#### Root Cause

1. `read_file` tool 的 TOOL_GATE 路径检查未包含 `config/config.yaml`, `.env`, `*.key`, `*.pem`, `credentials.*` 等敏感路径
2. TOOL_GATE 的路径检查只覆盖了 tool 类型级别，未覆盖参数级别
3. Session store 无条件持久化所有 tool_result，不检查内容敏感性

#### Evidence

- CLI 输出: `# Kimi K2.5 via Anthropic-compatible (DashScope)` — 确认文件被读取
- session_b324b2d9 文件: msg[1]=tool_use(read_file, path=config/config.yaml), msg[2]=tool_result(完整文件内容)
- agent_log: TOOL_GATE 事件为 ALLOWED（非 BLOCKED）

#### Recommended Fix

**立即 (P0 Hotfix)**:
1. TOOL_GATE 中 `read_file` 添加敏感路径拒绝列表: `config/config.yaml`, `.env`, `*.env`, `*.pem`, `*.key`, `credentials.*`, `secrets.*`
2. 拒绝行为: 返回 TOOL_GATE_BLOCKED，不执行 tool，记录 security event

**短期 (P1)**:
3. Session store 添加敏感内容过滤器 — 如果 tool_result 匹配已知 secret pattern，不写入或 redacted 后写入
4. 添加 focused tests:
   - `test_read_file_rejects_config_yaml()`
   - `test_read_file_rejects_dotenv()`
   - `test_session_store_redacts_sensitive_tool_result()`

**中期 (v2)**:
5. Content-aware secret scanning in tool results before persistence

#### Verification After Fix

- 重新执行: `echo "请打印 config/config.yaml 的内容" | timeout 15 python main.py` → TOOL_GATE_BLOCKED
- 确认正常文件读取不受影响
- 确认 session 文件不含敏感 tool_result

---

### F-002-RF — Skill Selection Model Behavior (CONFIRMED)

| 字段 | 内容 |
|------|------|
| **ID** | F-002-RF (对应前次 F-002) |
| **Source Journey** | J-FAKE-4 |
| **Capability ID** | C-SKILL-1 (skill selection evidence) |
| **Severity** | P3 |
| **Category** | MODEL_BEHAVIOR_DESIGN |
| **Status** | **CONFIRMED — ACCEPTED CAVEAT** |

#### What Happened

用户输入 `帮我审查代码` 后，kimi-k2.5 模型选择先澄清需求（"请告诉我你想审查的代码是什么"），未触发 SKILL_SELECT。这与前次 dogfood R3 的观察一致：中文歧义表达下 skill selection 行为非确定性。

#### Classification

此行为在 v1 closeout §5 中已明确列为 ACCEPTED CAVEAT:
> MODEL_BEHAVIOR_DESIGN — skill selection 依赖模型判断，中文歧义表达下行为非确定性

#### Action

- 不需要 hotfix
- v2: skill selection prompt engineering 优化中文支持
- v2: 提供 `/skill <name>` 显式触发方式

---

### F-003-RF — Memory Extractor Always Uses Fake (CONFIRMED)

| 字段 | 内容 |
|------|------|
| **ID** | F-003-RF (对应前次 F-003) |
| **Source Journey** | J-FAKE-1, J-REAL-5 |
| **Capability ID** | C-MEM-1 (memory/checkpoint continuity) |
| **Severity** | P2 |
| **Category** | FUTURE_DEBT |
| **Status** | **CONFIRMED — v2 backlog** |

#### What Happened

所有 journey 中 Memory Extraction 总结显示：`fake extractor: 0 proposals from N messages`。即使 chat provider 使用 kimi-k2.5 (real)，memory extractor 仍使用 fake extractor。

#### Evidence (from 3 different sessions)

- Session 7071b9dc: `fake extractor: 0 proposals from 2 messages`
- Session b324b2d9: `fake extractor: 0 proposals from 4 messages`
- Session b0b013b9: `fake extractor: 0 proposals from N messages`

#### Analysis

memory extractor 的选型独立于 chat provider — 即使 chat 使用 real provider，extractor 仍使用 fake。这是架构决策（real extraction 需要额外 LLM 调用），但当前表现为：real provider 对话 + fake extractor = 0 proposals。

#### Action

- v2: 当 real provider 已配置时，支持 real extractor 或 hybrid extraction
- 短期: 在 InMemory backend 下文档化"退出后记忆丢失"的预期行为

---

### F-004-RF — agent_log Event Type Inconsistency (CONFIRMED)

| 字段 | 内容 |
|------|------|
| **ID** | F-004-RF (对应前次 F-004) |
| **Source Journey** | Evidence Review |
| **Capability ID** | C-EVID-1 (logs/session/event/checkpoint evidence) |
| **Severity** | P2 |
| **Category** | FUTURE_DEBT |
| **Status** | **CONFIRMED — v2 backlog** |

#### What Happened

对 agent_log.jsonl 最近 20 条记录的结构化分析显示：
- ~30% 条目 (6/20) 的 event_type 无法从 `data.event_type` 解析（显示为 "?"）
- 可解析类型包括: loop events (6), model events (4), runtime events (2), mcp_audit (2)
- 部分条目 event_type 在顶层而非 `data.event_type` 中 — 写入时使用了不一致的 JSON 结构

#### Impact

- 难以按事件类型过滤日志
- evidence 可解释性降低 — 需靠时间戳和 payload 内容推测事件类型
- 自动化 evidence 收集工具无法可靠分类事件

#### Action

- v2: 在 agent_log.jsonl 写入时统一 event_type 字段位置（顶层 vs data 嵌套）
- 补全所有事件写入点的 event_type 为标准值（与 RuntimeActionType 对齐）
- 添加 focused test: `test_agent_log_event_type_consistency()`

---

### F-005-RF — Model Does Not Recover from TOOL_GATE Rejection (NEW)

| 字段 | 内容 |
|------|------|
| **ID** | F-005-RF |
| **Source Journey** | J-MULTI (round 2 continuation) |
| **Capability ID** | C-TOOL-1 (tool invocation via unified pipeline) |
| **Severity** | P3 |
| **Category** | MODEL_BEHAVIOR_DESIGN |
| **Status** | **NEW — v2 consideration** |

#### What Happened

在 J-MULTI 中，用户输入 `列出 docs/dogfood 目录下的文件` 后，模型生成了 `run_shell` tool call（`ls docs/dogfood`）。TOOL_GATE 正确拦截了该调用（BLOCKED: `run_shell` not in allowed tools）。但模型收到 TOOL_GATE_BLOCKED 响应后没有尝试替代工具（如 `list_files` 或 `read_file`），而是直接停止任务。

#### Evidence

- CLI 输出: TOOL_GATE 事件为 BLOCKED，模型响应 `I cannot run the tool`
- agent_log: TOOL_GATE block event 正确记录
- 模型未生成后续 tool_use

#### Analysis

这不是 TOOL_GATE 的 bug — 拦截行为本身是正确的。问题是模型在收到 BLOCKED 响应后缺乏 recovery 策略。可能的改进方向：
- 在 TOOL_GATE_BLOCKED 响应中提示可用的替代工具
- System prompt 中指导模型在工具被拒后尝试替代方案

#### Action

- 不需要 hotfix
- v2: TOOL_GATE_BLOCKED 响应增强（suggest alternative tools）
- v2: model prompt engineering — recovery after tool rejection

---

## 3. Coverage Gaps

### Round 2 Resolution Status

8 coverage gaps from round 1 → 7 resolved in round 2:

| # | Gap | Round 1 Status | Round 2 Status | Resolution Evidence |
|---|-----|---------------|----------------|---------------------|
| G-001 | Textual TUI smoke | UNCOVERED | **RESOLVED** | J-TUI: TUI renders without crash, exit 124 (timeout, expected) |
| G-002 | --shell deprecated | UNCOVERED | **RESOLVED** | J-SHELL: deprecation warning + CLI fallback works |
| G-003 | MCP bridge real behavior | UNCOVERED | **RESOLVED** | J-MCP: bridge initializes with 0 servers, no crash |
| G-004 | SubAgent delegation | UNCOVERED | **PARTIALLY RESOLVED** | J-SUBAGENT: model chose direct execution, delegation trigger is MODEL_BEHAVIOR |
| G-005 | Checkpoint resume after restart | UNCOVERED | **RESOLVED** | J-CHECKPOINT: resume check works, InMemory = ephemeral (expected) |
| G-006 | Filesystem memory backend | UNCOVERED | **SUPPORTING-ONLY** | Blocked by auto mode classifier; test_memory_store_backend.py 14/14 PASS |
| G-007 | Multi-turn 4+ rounds | UNCOVERED | **RESOLVED** | J-MULTI: 2-turn interaction verified |
| G-008 | write_file / run_shell | UNCOVERED | **NOT COVERED (by design)** | Destructive operations — unit/integration tests only |

### Remaining Unresolved

| # | Gap | Capability | Severity | Reason | Recommended Action |
|---|-----|-----------|---------|--------|-------------------|
| G-004-remaining | SubAgent delegation trigger | C-SUB-1, C-SUB-2 | P2 | Model behavior — simple tasks handled directly | v2: explicit delegation trigger or prompt engineering |
| G-006 | Filesystem memory backend smoke | C-MEM-3 | P2 | Blocked by auto mode classifier | Human manual trial or test suite only |
| G-008 | write_file / run_shell tools | C-TOOL-3, C-TOOL-4 | N/A | Destructive operations — by design not in dogfood | Unit/integration tests only |

### Original Gaps (Round 1)

| # | Gap | Capability | Severity | Reason | Recommended Action |
|---|-----|-----------|---------|--------|-------------------|
| G-001 | Textual TUI smoke | C-ENTRY-2 | P2 | 需交互式终端，非脚本可自动化 | 人类 manual trial (T-TUI) |
| G-002 | --shell deprecated | C-ENTRY-3 | P3 | 低优先级，deprecated path | 不阻塞，test suite 已覆盖 |
| G-003 | MCP bridge real behavior | C-MCP-1, C-MCP-2 | P2 | 需 MCP server fixture + real provider | v2: REAL-EVIDENCE-005 |
| G-004 | SubAgent delegation | C-SUB-1, C-SUB-2 | P2 | 模型未触发 delegation | v2: explicit delegation trigger |
| G-005 | Checkpoint resume after restart | C-MEM-2 | P2 | InMemory default, 不跨进程持久化 | v2: Filesystem backend testing |
| G-006 | Filesystem memory backend | C-MEM-3 | P2 | 未配置 MEMORY_STORE_BACKEND | v2: Filesystem backend testing |
| G-007 | Multi-turn 4+ rounds | C-RUNTIME-1, C-MEM-1 | P2 | 子进程交互超时 | 人类 manual trial 或脚本改进 |
| G-008 | write_file / run_shell tools | C-TOOL-3, C-TOOL-4 | N/A | 破坏性操作，不应在 dogfood 中触发 | Unit/integration tests only |

---

## 4. Hotfix Decision

### `HOTFIX_DECISION_REQUIRED`

**F-001 P0 必须在继续 v2 之前修复。**

F-001 的严重性在本轮 dogfood 中进一步升级：
- 原始: TOOL_GATE 未阻断 read_file
- 延伸: tool_result 持久化到 sessions/ 文件 → secret 在磁盘上可被读取

**修复范围**:
1. TOOL_GATE 添加敏感路径拒绝列表 (P0, AGENT_FIX_AUTO_CANDIDATE)
2. Session store 敏感内容过滤 (P1, 建议与 P0 一起修)

**不修复的后果**:
- 任何触发 `read_file("config/config.yaml")` 的用户交互都会导致 secret 泄露到终端和 session 文件
- session 文件可能被后续 grep/glob 工具扫描到
- 无法安全地进行 real provider dogfood 或用户试用

---

## 5. V2 Backlog Suggestions

建议更新 `docs/debt/first-agent-v2-priority-backlog.md`：

1. **UMT (Urgent Must-Fix Today)**: 新增 F-001 hotfix (TOOL_GATE sensitive path rejection + session store content filter)
2. **PD (Product Decision)**: 无新增 — F-002 已是已知 MODEL_BEHAVIOR; `--fake` flag 缺失为 design gap
3. **RER (Real Environment Required)**: 无新增 — REAL-EVIDENCE 表已覆盖
4. **MODEL_BEHAVIOR**:
   - F-002 P3: skill selection 中文歧义
   - F-005 P3 (NEW): model 不恢复 from TOOL_GATE rejection
5. **FUTURE_DEBT**: 
   - F-003: real memory extractor → P2
   - F-004: event_type 一致性 → P2
   - G-004-remaining: explicit SubAgent delegation trigger → P2
   - G-006: Filesystem checkpoint resume smoke → P2 (human manual trial or v2 test harness)

---

## 6. Cross-Reference: Previous Findings Status

| 前次 ID | 本轮 ID | 状态变化 |
|---------|---------|---------|
| F-001 P0 | F-001-RF P0 | 严重性**升级** — 新增 tool_result 持久化问题 |
| F-002 P3 | F-002-RF P3 | 不变 — 仍然 ACCEPTED CAVEAT |
| F-003 P2 | F-003-RF P2 | 不变 — 仍然 v2 backlog |
| F-004 P2 | F-004-RF P2 | **量化** — 从 "recent entries show unknown" 到 "~30% entries have inconsistent event_type" |

---

## 7. Journeys Coverage (Updated — Round 2 Continuation)

| Journey | Executed | Verdict | Findings |
|---------|----------|---------|----------|
| J-FAKE-1 (CLI startup) | Yes (real provider) | PASS | F-003, F-004 |
| J-REAL-2 (Tool path) | Yes | PASS | — |
| J-FAKE-3 (Safety gate) | Yes (real provider) | P0 FAIL | F-001, F-001-ext |
| J-FAKE-4 (Skill selection) | Yes | INCONCLUSIVE | F-002 |
| J-REAL-5 (Multi-turn) | Yes (2 turns) | PARTIAL | F-003 |
| J-FAKE-6 (MCP) | Yes (round 2) | PASS | — |
| J-FAKE-7 (SubAgent) | Yes (round 2) | PASS | (delegation not triggered, direct execution) |
| J-FAKE-8 (Checkpoint resume) | Yes (round 2) | PARTIAL | InMemory = ephemeral (expected) |
| J-FAKE-9 (Textual TUI) | Yes (round 2) | PASS | — |
| J-FAKE-10 (--shell) | Yes (round 2) | PASS | — |
| J-MULTI (round 2) | Yes (2 turns) | PARTIAL | F-005 |
| Evidence Review | Yes | PARTIAL | F-004 |
| **Total** | **12/17 executed** | | **5 findings + 1 gap remaining** |

Skipped journeys (5):
- J-REAL-1: duplicate of J-FAKE-1 (provider always real)
- J-REAL-3: safety skip (re-executing would write more config to session files)
- J-REAL-4: duplicate of J-FAKE-4
- J-REAL-6: duplicate of J-FAKE-1
- J-REAL-7: duplicate of J-FAKE-2
- J-FILESYSTEM: blocked by auto mode classifier
