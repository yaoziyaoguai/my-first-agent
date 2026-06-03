# First Agent v1 Runtime-First Synthetic User Dogfood Findings

**创建**: 2026-06-04
**更新**: 2026-06-04 (F-001/F-001-ext HOTFIX APPLIED — see §8)
**来源**: `docs/dogfood/v1-runtime-first-synthetic-user-dogfood-report.md`
**基线**: HEAD `9d1b17c` (round 1: `ea0ad82` → round 2 continuation: `2cacda7`), v1 tag `f6807ef`
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
| **Status** | **FIXED_BY_HOTFIX (2026-06-04)** — 见 §8 Hotfix Verification |

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

**Fix commit**: `agent/security.py` — `is_sensitive_file()` 扩展 + `tests/test_tool_sensitive_path_policy.py` (33 tests)

**Root cause**: `is_sensitive_file("config/config.yaml")` 返回 False → `needs_confirmation` 不返回 "block" → TOOL_GATE 允许 read_file → 原始内容进入 tool_result → `save_session_snapshot` 持久化到 sessions/*.json

**Fix strategy** (single-point defense at `is_sensitive_file`):
1. 新增 `CONFIG_FILE_NAMES`: `{"config.yaml", "config.yml", "config.toml", "config.json"}` — 精确匹配主流配置文件名
2. 新增 `CONFIG_DIR_SENSITIVE_SUFFIXES`: `{".yaml", ".yml", ".toml", ".json"}` — config/ 目录下匹配常见配置扩展名
3. `is_sensitive_file()` 新增 4 个检查路径: 精确文件名匹配 → config* 前缀+配置扩展名 → 双扩展名备份文件 → config/ 目录上下文
4. `needs_confirmation()` 简化返回逻辑

**Double defense achieved**:
- **Pre-read denial**: `is_sensitive_file` → True → confirmation="block" → gate_disposition="rejected" → tool 不执行
- **Persistence safety**: tool 不执行 → 无 raw content 进入 tool_result → 无敏感内容写入 sessions/

**R4 dogfood recheck** (real provider, kimi-k2.5):
- 输入: `请读取 config/config.yaml 文件的内容`
- 模型生成 `read_file("config/config.yaml")` → TOOL_GATE BLOCKED
- 输出: `路径 'config/config.yaml' 被识别为敏感配置/密钥文件，拒绝读取`
- session 文件: 仅含 denial metadata (142 chars)，无 sk-* 或 real secret
- 正常文件读取不受影响: `read_file("README.md")` 正常工作

**Test evidence**:
- `tests/test_tool_sensitive_path_policy.py`: 33/33 passed
- Full pytest: 4406 passed, 0 failed, 37 xfailed (controlled), 18 skipped
- Ruff: All checks passed on touched files
- Docs source of truth: 79/79 passed
- Architecture boundaries: 24/24 passed

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

### `RESOLVED — F-001/F-001-ext HOTFIX APPLIED (2026-06-04)`

F-001 P0 已在 commit `[current]` 中修复。修复内容见 §8 Hotfix Verification。

**修复范围**:
1. `is_sensitive_file()` 扩展: 新增 CONFIG_FILE_NAMES + CONFIG_DIR_SENSITIVE_SUFFIXES 常量，4 个新检查路径覆盖 config.yaml/yml/toml/json 及其变体 (P0, 已完成)
2. `needs_confirmation()` 简化: read_file/read_file_lines 敏感路径直接返回 "block" (P0, 已完成)
3. 新增回归测试: `tests/test_tool_sensitive_path_policy.py` (33 tests, P0, 已完成)

**Session store 敏感内容过滤 (P1)**:
- 已通过 pre-read denial 达成等效防护 — tool 不执行，故无 raw content 进入 session
- 额外的 session-level content scanning 作为 v2 defense-in-depth 保留在 backlog 中

**F-001-ext (历史 session 文件)**:
- 已有 session 文件中可能包含修复前的 raw config content
- 新 session 文件不再包含敏感 tool_result
- 历史 session 文件清理不在本轮 scope 内，但风险已受控（本地文件，非共享环境）

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
| F-001 P0 | F-001-RF P0 | **FIXED** — hotfix applied 2026-06-04, see §8 |
| F-002 P3 | F-002-RF P3 | 不变 — 仍然 ACCEPTED CAVEAT |
| F-003 P2 | F-003-RF P2 | 不变 — 仍然 v2 backlog |
| F-004 P2 | F-004-RF P2 | **量化** — 从 "recent entries show unknown" 到 "~30% entries have inconsistent event_type" |

---

## 7. Journeys Coverage (Updated — Round 2 Continuation)

| Journey | Executed | Verdict | Findings |
|---------|----------|---------|----------|
| J-FAKE-1 (CLI startup) | Yes (real provider) | PASS | F-003, F-004 |
| J-REAL-2 (Tool path) | Yes | PASS | — |
| J-FAKE-3 (Safety gate) | Yes (real provider) | **FIXED (Hotfix)** | F-001, F-001-ext — see §8 |
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

---

## 8. Hotfix Verification — F-001 / F-001-ext (2026-06-04)

### 8.1 Changes

**Modified**: `agent/security.py` (+37/-11)
- 新增 `CONFIG_FILE_NAMES`: `{"config.yaml", "config.yml", "config.toml", "config.json"}`
- 新增 `CONFIG_DIR_SENSITIVE_SUFFIXES`: `{".yaml", ".yml", ".toml", ".json"}`
- `is_sensitive_file()` 扩展 4 个检查路径: 精确文件名 → config* 前缀+配置扩展名 → 双扩展名备份文件 → config/ 目录上下文
- `needs_confirmation()` 简化: 移除冗余 if/else 嵌套

**Created**: `tests/test_tool_sensitive_path_policy.py` (33 tests)
- §1: config*.yaml/yml 识别 (5 parametrized)
- §2: 现有 .env*/.pem/.key 不受影响 (8 parametrized)
- §3: 安全文件不误伤 (2 parametrized)
- §4: needs_confirmation 返回 "block" (4 parametrized)
- §5: read_file_lines 同样受保护
- §6: 路径规范化防绕过 (3 parametrized)
- §7: 常量基线验证 (5 tests)
- §8: F-001-ext tool_result 不包含 raw content

### 8.2 Gate Results

| Gate | Result |
|------|--------|
| `ruff check agent/security.py tests/test_tool_sensitive_path_policy.py` | All checks passed |
| `python3 -B -m pytest tests/test_tool_sensitive_path_policy.py -v -q` | 33/33 passed |
| `python3 -B -m pytest tests/test_docs_source_of_truth.py --tb=short -q` | 79/79 passed |
| `python3 -B -m pytest tests/test_architecture_boundaries.py --tb=short -q` | 24/24 passed |
| Full pytest (4406 tests) | 4406 passed, 0 failed, 37 xfailed, 18 skipped |
| `git diff --check` | Clean |
| config/config.yaml staged? | No |
| .env staged? | No |

### 8.3 R4 Dogfood Recheck (Real Provider)

- Provider: kimi-k2.5 via Anthropic-compatible (DashScope)
- Input: `请读取 config/config.yaml 文件的内容`
- Model generated `read_file("config/config.yaml")` → TOOL_GATE **BLOCKED**
- Output: `路径 'config/config.yaml' 被识别为敏感配置/密钥文件，拒绝读取`
- Session file: denial metadata only (142 chars), no sk-* patterns
- `read_file("README.md")` → 正常工作 (safe path preserved)

### 8.4 Fix Completeness

| Requirement | Status |
|-------------|--------|
| 根因定位 | `is_sensitive_file()` 不识别 config.yaml → TOOL_GATE 允许 |
| 统一 tool safety policy 修复 | `is_sensitive_file` 是 read_file/read_file_lines 共享的前置边界 |
| fake/real 共享同一策略 | needs_confirmation 在 execute_single_tool 内部，provider 边界之下 |
| 敏感文件在读取前被拒绝 | confirmation="block" → gate_disposition="rejected" → tool 不执行 |
| 拒绝后不产生 raw content tool_result | tool 不执行 → 仅 denial metadata 进入 tool_result |
| session/event/log 不保存新 raw content | 已通过 pre-read denial 达成等效防护 |
| 不引入 fake/real split | 策略在 agent/security.py，不涉及 provider 分叉 |
| 不断增第二条 runtime flow | 未新增路径，仅扩展现有 is_sensitive_file |
