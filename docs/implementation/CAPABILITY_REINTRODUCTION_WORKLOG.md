# Capability Reintroduction Worklog

持续执行 `docs/architecture/CAPABILITY_REINTRODUCTION_ROADMAP.md` 与计划 `002—007`。
本文件记录实现过程中的阶段/Unit、Red/Green、设计决定、偏差和当时的测试证据；它不是当前 capability acceptance 状态的权威来源。

> 2026-07-20 closure correction：下文的“Green/完成/Product gate”只表示实现者当时观察到的 dirty-worktree 自动结果，不是当前 capability claim。follow-up audit 证明 008 的 content/control gate 未实现，manifest 还纳入 runtime state，多项 named test 没覆盖实际 preview、receipt、durability、identity、keyboard journey 或 lifecycle。当前状态见 `docs/architecture/CURRENT_CAPABILITY_STATUS.md`，证据见 `docs/audits/2026-07-20-capability-evidence-closure-audit.md`，当前实施计划见 `docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md`。008 artifacts 与下文阶段记录均为只读历史，不能用于晋级。

## graphify 说明

`graphify-out/graph.json` 存在但图谱基于 HEAD（旧 `agent/core.py`、`agent/loop.py`、`runtime_integration/` 等已删除文件），与工作树（新最小内核）矛盾。本 worklog 期间按实际源码推进；图谱陈旧，待 cutover 完成且可证明不摄入 ignored/private 路径后再 refresh。

## Baseline（开始时记录）

- `git status --short`：大量 `D`（HEAD 旧架构文件在工作树删除）+ `M`（AGENTS/README/agent.__init__ 等）+ 未列出的新文件（agent/runtime/* 等）。属用户既有改动，不 reset、不回滚。
- `git diff --check`：通过。
- `.venv/bin/ruff check .`：All checks passed。
- `.venv/bin/python -m pytest -q -rx`：**133 passed** in 4.53s。
- 当前工作树已是重构完成的新最小 Kernel；尚无 `agent/composition.py` 与 `agent/skill/`。

## 阶段 002 Skill — 进行中

### U1 — Freeze shared Tool composition and outcome contracts（进行中）

**reducer 安全缺口定位**（`agent/runtime/state.py` `_action_is_legal`）：

- `Resume` 分支允许 `AWAITING_RECOVERY`（应拒绝：recovery 只接受 exact `ResolveUnknownToolOutcome`）。
- `CancelRun` 分支允许所有 active 状态，包括 `RUNNABLE/EXECUTING`（effect 可能已发生）与 `AWAITING_RECOVERY`。

**合约层级判断（关键设计决定）**：

任务提示「三」与计划 R5 的 gating 措辞精确为 **`RUNNABLE/EXECUTING`**（RUNNABLE + EXECUTING phase）的 `CancelRun` 返回 unchanged CONFLICT，以及 `AWAITING_RECOVERY` 上 Resume/Cancel 均 unchanged。001 的 R27 另有更宽泛的「still-owned RUNNABLE 拒绝 cancel」字面读法，但与 State/Action 表（"after owner loss: other phases Resume/CancelRun"）及现有测试 `test_completion_..._cancel_is_state_scoped`（owner-set RUNNABLE/MODEL cancel ACCEPTED）冲突。

采取最小、无歧义、且不破坏现有语义的修法：

- `CancelRun`：`AWAITING_RECOVERY` 或 `RUNNABLE+EXECUTING` → CONFLICT；其余（RUNNABLE 非 EXECUTING、AWAITING_APPROVAL、PAUSED_*）ACCEPTED。
- `Resume`：`AWAITING_RECOVERY` → CONFLICT；其余 ACCEPTED。
- 「活跃占用」由 lease（`conversation_busy`）在 loop 层保护，reducer 只对真正危险的 EXECUTING/recovery 收口。这与 R5/任务提示一致；R27 的「still-owned」字面未采纳，理由记录于此。

**未解决风险**：无。后续 composition 部分（per-registration policy、intent-aware executor、`build_file_tool_registrations()`、`agent/composition.py`）按 U1 继续串行推进。

**下一个动作**：写 U1 reducer Red 测试（CancelRun on EXECUTING、CancelRun/Resume on AWAITING_RECOVERY 均 unchanged conflict），确认因目标行为缺失而 Red，再 Green 修改 `_action_is_legal`。

#### U1 reducer 安全修复 — Green ✓

- Red（`tests/kernel/test_action_legality.py` 追加 4 用例）：CancelRun on RUNNABLE/EXECUTING、CancelRun on AWAITING_RECOVERY、Resume on AWAITING_RECOVERY 均 unchanged conflict；Resume on EXECUTING 保持 ACCEPTED（进入 recovery 的唯一入口）。3 个按预期 Red（ACCEPTED 而非 CONFLICT），1 锚点 pass。
- Green（`agent/runtime/state.py` `_action_is_legal`）：`Resume` 移除 `AWAITING_RECOVERY`；`CancelRun` 对 `AWAITING_RECOVERY` 与 `RUNNABLE+EXECUTING` 返回 CONFLICT。
- 验证：test_action_legality 10 passed；kernel+architecture 72 passed 无回归。

#### U1 composition foundation — Green ✓

合同变更（vocabulary 先行，再 Red-Green 行为）：

- `agent/runtime/contracts.py`：新增 `KnownNotExecuted(code, message)`；`ToolResult` 增 `executed: bool = True`。
- `agent/runtime/tools.py`：`RegisteredTool` 增 `policy: ToolPolicy | None`（per-registration policy，runtime 用 `_policy_for(reg)` 解析，不按工具名路由）；executor 改为接收 frozen `ExecutionIntent`（`func(intent)`，使后续 MCP/Memory/SubAgent 可用 idempotency identity）；`invoke` 处理 `KnownNotExecuted` → `executed=False` 的普通 tool result（推进游标，不进 recovery）；WRITE/EXTERNAL 异常仍 raise → recovery。
- `agent/runtime/loop.py`：`_tool_result_fact` 在 fact content 暴露 `executed`。
- `agent/tools/file_ops.py`：新增 `build_file_tool_registrations(...) -> tuple[RegisteredTool, ...]`（每项绑 `_WorkspaceFilePolicy`）；`build_file_tool_runtime` 退化为薄封装（保留给 test_file_tools）。
- `agent/composition.py`（新）：`Composition{runtime, tool_runtime, context_manager}` + `build_composition(...)`，只构造一个 ToolRuntime/ContextManager/AgentRuntime；无 sources tuple、无 close stack、无 global getter。
- `main.py`：改用 `build_composition` + `build_file_tool_registrations`。
- 测试 fixtures 同步 `func(intent)`：test_tool_runtime、test_tool_policy、test_effect_ordering、test_runtime_turn、test_runtime_approval、test_runtime_limits。

Red→Green 证据（`tests/kernel/test_tool_registration_composition.py` + `tests/kernel/test_tool_outcomes.py`）：

- 两个 registration 不同 policy identity；duplicate 名原子失败；executor 收到 frozen intent；`executed=false` 推进游标无 recovery；unknown WRITE 异常进 recovery；composition 无 sources/close_stack。
- existing file tools approve/execute once（test_file_tools 全绿）。

最终门：`pytest -q` 143 passed；`ruff check .` clean；`git diff --check` clean；architecture effect-owners 仍唯一（仅 loop.py 调 invoke/generate/compare_and_swap，composition.py 只构造不驱动）。

### U2 — strict immutable Skill catalog（进行中）

读取 `pyproject.toml`（Python >=3.11 基线、可选 `skill=PyYAML`），随后按 U2 Red 清单实现 `agent/skill/catalog.py`。

**下一个动作**：写 U2 Red 测试（valid metadata、name/dir mismatch、duplicate、symlink/traversal、YAML bomb、limits、per-resource digest），再 Green 实现 immutable catalog + 严格 SafeLoader 子类。

#### U2 — Green ✓

- `agent/skill/catalog.py`（+ 空 `agent/skill/__init__.py`）：`SkillLimits`、`FileIdentity`、`SkillResourceDescriptor`、`SkillDescriptor`（含 `identity_digest`，不含路径）、`ActivationResult`、`SkillCatalog`（`read_activation`/`read_resource` 做 no-follow + digest 漂移检测）、`build_skill_catalog(roots)`。
- 严格 SafeLoader 子类：compose 前 `peek_event` 拦截 `AliasEvent`（PyYAML 在 compose 期就解析 alias，按事件类型才稳定）；`construct_mapping` 拒绝 duplicate key；SafeLoader 默认拒绝 custom tag（`!python/object/apply` 等 → ConstructorError → SkillSchemaError）；node depth/count/scalar bytes 上限。
- 校验：name `^[a-z0-9]+(-[a-z0-9]+)*$` 且 == 父目录名；description/license/compatibility/metadata 长度；allowed-tools 仅校验形状后丢弃。
- 安全：no-follow `os.open`/`os.stat`；拒绝 symlinked skill dir 与 symlinked resource；资源只允许 `references/`/`assets/` 直接 regular file；非 UTF-8 fail closed；错误信息不含绝对路径。
- 可选依赖：`_require_yaml()` 懒导入；未配置 root 不导入 yaml；配置 root 但缺失 → `SkillDependencyError`（subprocess 屏蔽 yaml 验证）。
- pyproject：`requires-python>=3.11`、ruff `py311`、可选 `skill=["PyYAML>=6,<7"]`；12 个 `(str,Enum)` 迁移到 `StrEnum`（checkpoint 序列化显式 `.value`，迁移安全，无回归）。
- 测试：`tests/skill/test_catalog.py` 15 passed（tmp_path 动态 fixtures，不读项目/用户目录）。
- 最终门：全量 158 passed；ruff clean；architecture allowlist 加入 `agent/skill/`；diff --check clean。

### U3 — governed activation/resource tools（进行中）

实现 `agent/skill/tools.py`：`build_skill_tool_registrations(catalog, *, max_tool_result_chars)` 产出每个 Skill 一个 `skill__<name>` activation registration + 一个共享 `skill__read_resource` registration。body drift → `KnownNotExecuted`（READ_ONLY，不进 recovery）；完整 activation result 不超过 `max_tool_result_chars` 且不静默截断。

#### U3 — Green ✓

- `agent/skill/tools.py`：`build_skill_tool_registrations(catalog, *, max_tool_result_chars)` → 每 Skill 一个 `skill__<name>`（empty schema, LOW/READ_ONLY/NEVER）+ 共享 `skill__read_resource`。activation callable 调 `catalog.read_activation`，漂移/超限 → `KnownNotExecuted`；resource callable 调 `catalog.read_resource`，scripts/URL/traversal/漂移 → `KnownNotExecuted`。ToolSpec.identity_digest 经 safety_policy 绑定 skill identity + catalog digest（scan 后改动使旧 intent 失效）。
- skill name 仅允许连字符 → `skill__read_resource`（下划线）不会与 activation 名碰撞。
- 测试 `tests/skill/test_tools.py` 9 passed：namespaced spec、empty schema、完整 body 不截断、超限→KnownNotExecuted、body/resource drift→KnownNotExecuted、resource allowlist、scripts/URL 拒绝、恶意 body 不绕过 write approval、端到端 activation body 进入下一 ContextPack 且不在 clipped_ids。
- 「不可容纳→context limit」由既有 context 测试覆盖（pinned core too large → ContextLimitError，非 skill 特有）。
- 最终门：全量 167 passed；ruff clean；architecture allowlist 加入 `agent/skill/tools.py`；diff --check clean。

### U4 — compose explicit CLI config（进行中）

`composition.py` 增 `build_tool_registrations(workspace, skill_roots, ...)` 拼接 file + skill registrations；`main.py` 加 `--skill-root`（可重复），有 root 才建 catalog（懒 yaml），缺失依赖或非法 root → startup 失败。

#### U4 — Green ✓

- `agent/composition.py`：`build_tool_registrations(*, workspace, skill_roots, protected_paths, private_roots, max_tool_result_chars, skill_limits)` 显式拼接 file registrations +（有 root 时）skill registrations。
- `main.py`：`--skill-root`（action=append，可重复）；`resolve(strict=True)`；context_limits.max_tool_result_chars 同时传给 skill registrations 与 ContextManager；startup except 增加 `SkillCatalogError`。
- 测试：`tests/skill/test_integration.py` 6 passed（no-root=仅文件工具、有 root 加 activation/resource、多 root 合一 catalog、name mismatch/missing root fail closed、composition 无 yaml 可 import）；`tests/cli/test_entrypoint.py` 增 2 用例（valid skill-root 启动、invalid skill-root exit 2 无 traceback）。
- README 加 Skills 章节。

#### U5 — Green ✓

- 架构加固 `tests/architecture/test_cutover_absence.py::test_production_sources_never_import_legacy_capability_paths`：production 不得 import `skill_system/skills/skill_lifecycle/subagent_system/runtime_integration/confirmation`（`agent.skill` 单数是唯一允许的 Skill 产品包，由精确文件集 + 此 import 检查共同保证）。
- `EXTENSION_CONTRACTS.md`：ToolSource 节注明 Skill v1 已按该 seam 实现。
- **Skill reference-task evidence（Product gate）** `tests/skill/test_reference_task.py`：`release-notes` Skill + `references/version.txt`，FakeProvider 脚本化 激活→读资源→终态回答；证明 skill body 与 resource 内容未裁剪进入模型上下文，最终回答包含仅能从 resource 获得的 `1.2.3` 与 skill 规则要求的 `READY` 收尾。

#### 002 Skill 最终门

focused(002) 66 passed；architecture 6 passed；`git diff --check` OK；ruff clean；全量 **177 passed**。无第二套 loop、无 prompt hook、无脚本执行、无默认目录扫描。Skill 能力完成，进入 MCP。

---

## 阶段 003 MCP — 进行中

读取 MCP_DESIGN.md 与 003 计划后，首先验证 pinned SDK 的 public `ClientSession(read_stream, write_stream)` 可行性（public-stream feasibility Red），再实现 stdio fixture、ordered close stack、HIGH+EXTERNAL+ALWAYS_APPROVAL、durable safety latch。

### SDK feasibility 证据（U3 gating，预先静态验证）

- 安装 `.[dev,skill,mcp]`：`mcp==1.28.1`、`jsonschema==4.26.0`、httpx floor `>=0.27.1`。
- `mcp.client.session.ClientSession.__init__(read_stream, write_stream, ...)` 为 public；`read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]`、`write_stream: MemoryObjectSendStream[SessionMessage]`（anyio memory streams）。
- public helper `mcp.shared.memory.create_client_server_memory_streams` / `create_connected_server_and_client_session` 可创建流对；`mcp.types.ClientCapabilities`/`ToolsCapability` 可用。
- 结论：project-owned `McpStdioTransport` 可持有 process group/framing/commit receipt，并通过 public stream contract 把消息流交给 SDK `ClientSession`；SDK 独占 JSON-RPC session lifecycle。无需 private hook 或 SDK-owned spawn。**无 blocker**，按 U1→U6 串行推进。

### U1 catalog + safety — Green ✓

- `agent/mcp/contracts.py`（McpOutcomeClassification/McpBridgeOutcome）、`catalog.py`（显式 JSON catalog → immutable `McpServerConfig`/`McpToolDescriptor`；严格校验：transport/command absolute regular no-follow/safety_generation/pinned protocol revision/env-name/duplicate local name/credential-looking value 扫描（跳过已知合法字段名）/schema size-depth；冻结 executable identity+digest；lazy 无 SDK 依赖）、`safety.py`（owner-only/no-follow durable `McpSafetyLatch`：finite-lock + revision/token/full-binding CAS，CLEAR↔ARMED，unresolved marker 阻止 composition）。测试 17 passed。

### U2 async owner-loop bridge — Green ✓

- `agent/mcp/bridge.py` `McpAsyncBridge`：独占 event-loop thread，startup 无 session；`submit(coro_factory)` 串行化、总 wall-clock cap 超时→quarantine；idempotent close；quarantine 拒绝后续 submit。测试 6 passed。

### U3 stdio session（最难单元）— Green ✓

- project-owned stdio transport 复刻 SDK framing/pump（stdout→`JSONRPCMessage`→`SessionMessage`→read_stream；write_stream→`model_dump_json`+`\n`→stdin），自持 process group（`start_new_session`）/stdin-close 清理/SIGKILL 兜底；`commit.call_may_have_been_sent` 在第一次 `tools/call` OS write 前置位、永不回退。`_drive_session`/`_interact` 用 public `ClientSession` 完成 initialize→list(分页)→descriptor verify(canonical schema 去 title 比较)→`tools/call`→normalize。pre-call 条件在 `async with ClientSession` 内**返回** outcome（raise 会被 session `__aexit__` 包成 ExceptionGroup 绕过分类）；call 后失败传播为 UNKNOWN。latch arm/clear 围绕 spawn/cleanup。fixture `tests/fixtures/mcp/stdio_server.py`（FastMCP echo/broken）。测试 5 passed（echo EXECUTED、broken EXECUTED error、drift/missing/invalid NOT_EXECUTED）。

### U4 tools executor — Green ✓

- `agent/mcp/tools.py` `build_mcp_tool_registrations` → 每 descriptor 一个 HIGH/EXTERNAL/ALWAYS `mcp__<server>__<tool>`，identity 绑 config/descriptor/profile/safety_generation/composition_epoch。intent-aware executor 提交一次 session coroutine 并映射 outcome：EXECUTED→文本、NOT_EXECUTED→`KnownNotExecuted`、UNKNOWN→`McpUnknownOutcomeError`（抛给 recovery）+ bridge quarantine。测试 5 passed（spec/preview、三种 outcome 映射、真实 echo 端到端经 ToolRuntime approval/invoke）。

### U5 composition + close stack + CLI — Green ✓

- `agent/composition.py`：`McpResources`/`build_mcp_resources`/`load_mcp_catalog_file`；`Composition.close_stack`（首个真实 closeable 引入 ordered close stack）；`main.py` 加 `--mcp-catalog`/`--mcp-safety-state`（成对使用），env allowlist 转发，teardown 倒序关闭 close stack。unresolved latch 阻止 MCP composition。测试 4 passed。

### U6 架构 + 文档 — Green ✓

- architecture allowlist 加入 `agent/mcp/{__init__,contracts,catalog,safety,bridge,tools}.py` + `agent.mcp` 包；`EXTENSION_CONTRACTS.md`/`README.md` 增 MCP 说明。
- **MCP Product gate**：plan 明确真实 reference task 需用户另行授权调用真实 server；未授权时保持 product gate 未验收，不伪造。fixture 端到端（echo 经 approval→invoke→EXECUTED）为 wiring 证据。

#### 003 MCP 最终门

focused(mcp+tool_outcomes+cli) 57 passed；architecture 6 passed；`git diff --check` OK；ruff clean；全量 **214 passed**。无第二套 loop、无 startup discovery、无 SDK-owned spawn、无自动重试；call 后未分类结果一律进 human recovery。MCP 完成，进入 Memory。

---

## 阶段 004 Memory — 进行中

读取 MEMORY_DESIGN.md 与 004 计划后实现 ContextSource seam + 显式 create/load store + remember/update/forget approval-bound WRITE tools + conversation A→B recall reference task。

### U1 ContextSource leaf contract — Green ✓

- `contracts.py`：`ContextSourceLimits`/`ContextQuery`/`ContextCandidate`/`ContextSourceSnapshot`（immutable JSON-safe leaf，snapshot 校验 candidate id 唯一）。
- `ports.py`：`ContextSource.snapshot(query)` protocol + `RetryableContextSourceError`。
- `Composition.sources`/`build_composition(sources=, workspace_scope_digest=)`；DAG 测试放宽：context 可依赖 contracts+ports。

### U2 ContextManager source 集成 — Green ✓

- `context.py`：`KernelContextManager(sources=, workspace_scope_digest=, source_item_cap=)`；`build` 取 fresh snapshot → 每候选一个 non-pinned `_ContextGroup`（untrusted context block，永不 system，cap 到 `max_tool_result_chars`），按倒序优先淘汰（Memory 最低优先级，永不挤掉 core）；`BudgetReport.source_digests`；source 暂时不可用 → `RetryableContextSourceError`，loop 映射为 `FAILED_RETRYABLE/context_source_unavailable`（provider call count 为零）；source 损坏 → fatal。空 sources 行为 byte-equivalent 基线。

### U3 secure revisioned store — Green ✓

- `agent/memory/store.py`：`MemoryStore.create`（O_CREAT|O_EXCL|O_NOFOLLOW，0600，revision 0 空）/`load`（owner-only regular no-follow，version/scope/provider-profile 校验，malformed 不覆盖源）；mutation（remember/update/forget）在同一 stable lock（finite deadline）内 revision CAS + 同目录 0600 temp write+fsync+replace+directory fsync；effect 前 lock 超时→`MemoryBusyError`、CAS mismatch→`MemoryCasMismatch`。测试 6 passed（exclusive create、scope/profile 校验、CAS、owner-only、malformed fail closed、persistence reload）。

### U4 source + read tools — Green ✓

- `source.py`：`MemoryContextSource.snapshot` NFKC+casefold lexical 打分（ASCII run token、非 ASCII alnum codepoint token、`2*matched_unique + exact_phrase_bonus`），按 score/recency/ID 排序，cross-scope 排除，空 query 无候选，deterministic digest。
- `tools.py`：`memory_search`/`memory_get`（READ_ONLY/NEVER）。测试 source 4 + tools 覆盖。

### U5 mutation tools — Green ✓

- `memory_remember`/`memory_update`/`memory_forget`（WRITE/ALWAYS_APPROVAL）；prepare_binding 绑 scope + content digest（remember 不绑尚不存在的 record；update/forget 绑 record id+revision+content digest）；func 执行 store CAS，effect 前 busy/cas mismatch → `KnownNotExecuted`，effect 后异常传播 recovery。preview 展示完整 bounded content。测试覆盖 search/get/read + approval/CAS。

### U6 composition + 文档 — Green ✓

- `composition.py`：`MemoryResources`/`build_memory_resources`/`workspace_scope_digest_for`/`provider_trust_profile`；`main.py` 加 `--memory-create`/`--memory-store`（互斥）+`--memory-profile`，路径与 workspace 不重叠，sources + workspace_scope_digest 接入 build_composition；startup except 加 `MemoryStoreError`。architecture allowlist 加入 `agent/memory/*` + `agent.memory` 包。
- **Memory recall reference task（Product gate）** `tests/memory/test_integration.py`：conversation A remember "deploy command is `pyc ship`" → conversation B 独立 load 同 store，source 召回包含 `pyc ship` 的候选（approved provenance）；并验证候选经 ContextManager 进入下一 ContextPack 为 untrusted context block、`BudgetReport.source_digests` 非空；无 Memory 配置时 byte-equivalent 基线。

#### 004 Memory 最终门

focused(context_budgeting+provider+memory+cli) 77 passed；architecture 6 passed；`git diff --check` OK；ruff clean；全量 **230 passed**。无第二套 loop、无 prompt hook、无 session-end 自动写入、conversation checkpoint 不保存 Memory snapshot。Memory 完成，进入 SubAgent。

---

## 阶段 005 SubAgent — 进行中

child 复用同一个 `AgentRuntime.run_turn` 实现；最多一次 model call、零 tools、零 ContextSource、独立临时 state；不继承 parent history/Memory/Skill/MCP/workspace/credential；只允许同信任域 provider profile。reference task：isolated child 独立审查 + 可核对增量。

### U1 架构合同窄化 — Green ✓

- `EXTENSION_CONTRACTS.md` ToolSource 节增 SubAgent 窄化：只有 `subagent__delegate` executor 可调用注入的 `ChildAgentRunner`，其 production impl 只构造同一 `AgentRuntime` 并调用 `run_turn`；executor 不导入 provider/loop。
- 架构 guard `test_subagent_package_does_not_import_provider_or_loop`：SubAgent 包内仅 runner.py 可 import loop，contracts/tools 不得 import provider/loop。

### U2 child runner — Green ✓

- `agent/subagent/runner.py` `ChildAgentRunner`：独立 in-memory store/ConversationState、空 ToolRuntime、无 ContextSource、`max_model_calls=1`；从 parent idempotency key 确定性派生 child conversation/run ID；child events 不混入 parent（_NullEventSink）。child tool request（空 catalog + 1 model call）→ nonterminal。

### U3 delegation tool — Green ✓

- `agent/subagent/tools.py` `build_subagent_tool_registrations(runner)`：`subagent__delegate`（HIGH/EXTERNAL/ALWAYS），identity 绑 runner version/provider profile+destination/workspace scope/limits digest；executor 从 frozen intent 派生 child identity，COMPLETED→bounded 文本、其他明确终态→已知失败文本、unclassified 异常传播 parent recovery。preview 显示 provider destination + bounded objective/handoff。

### U4 composition + opt-in — Green ✓

- `main.py` `--subagent` opt-in，复用 parent provider 建 child runner（同信任域），registration 拼进同一 ToolRuntime。

### U5 架构 + 文档 — Green ✓

- architecture allowlist 加入 `agent/subagent/{__init__,contracts,runner,tools}.py` + `agent.subagent` 包；README 增 SubAgent 章节。
- **SubAgent reference task（Product gate）** `tests/subagent/test_integration.py`：parent → AWAITING_APPROVAL → ResolveApproval → child 跑一次（独立 provider）→ parent COMPLETED，最终回答包含仅能从 child 获得的 `SECRET-OMEGA`（可核对增量），parent 2 次 provider call、child 1 次。

#### 005 SubAgent 最终门

focused(subagent+effect_ordering+runtime_recovery+cli+architecture) 38 passed；`git diff --check` OK；ruff clean；全量 **238 passed**。无第二套 provider/tool loop、无 child 工具/workspace 继承、无递归/后台/durable child。SubAgent 完成，进入 Scheduler。

---

## 阶段 006 Scheduler — 进行中

external occurrence caller（cron/launchd/CI adapter），不是内置计时器。每次 occurrence = 独立 conversation/checkpoint + 确定性首次 SubmitMessage；duplicate fire replay；approval/recovery/limit 交还人类。

### U1 occurrence/report 合同 — Green ✓

- `agent/scheduler/contracts.py`：`ScheduledOccurrence`（严格 ID/canonical UTC/bounded message/workspace scope）；`checkpoint_relative_path` 只由 schedule+occurrence ID 派生；`conversation_id`/`run_id` 额外绑定 scheduled_for+message_digest+workspace scope（同 ID 漂移命中原文件即 conflict）；`ScheduledRunReport` + `occurrence_exit_class`（completed/needs_human/fatal_conflict）。测试 4 passed。

### U2 create-or-load + caller — Green ✓

- `agent/scheduler/caller.py`：`create_or_load_occurrence_store`（排他 `LocalCheckpointStore.initialize`/load，conversation identity 不匹配即 conflict，不暴露 compare_and_swap）；`ScheduledOccurrenceCaller` 只接收 pre-bound Runtime/snapshot，唯一 execution call 是 `run_turn(seq=1, rev=0)`，stale snapshot CONFLICT 最多 reload 一次重交相同 action；report 基于 authoritative active/last run。测试 3 passed（首 fire COMPLETED、duplicate replay、同 ID 不同 message conflict、paused→needs_human）。

### U3 headless CLI — Green ✓

- `main.run_schedule`：create/load store → build_composition(store=...) → caller.run_once → stdout JSON report；exit 0/1/2；state-root 与 workspace 不重叠。console entry `first-agent-schedule`。测试 3 passed（首 run completed、duplicate replay、overlap fail startup）。

### U4 架构 + 文档 — Green ✓

- architecture allowlist 加入 `agent/scheduler/*` + `agent.scheduler` 包；EXTENSION_CONTRACTS/README 增 Scheduler 说明。
- **Scheduler reference task（Product gate）** `tests/scheduler/test_cli.py`：外部 fire → COMPLETED（exit 0 + JSON report）→ duplicate fire replayed（provider/effect 不重复）→ overlap state-root fail closed。

#### 006 Scheduler 最终门

focused(scheduler+action_legality+runtime_turn+architecture+cli) 48 passed；`git diff --check` OK；ruff clean；全量 **248 passed**。无 timer/daemon/cron parser、无共享 scheduler cursor、无自动 approve/recovery/Resume。Scheduler 完成，进入 TUI。

---

## 阶段 007 TUI — 进行中

Textual 作为 optional adapter；shared reducer 是唯一 legality 权威；worker single-flight；event 只作 advisory；restart/reopen 从 authoritative checkpoint 恢复；外部可控文本 literal rendering（markup=False，不解析 link，ANSI/C0/C1/bidi 显示为可见 escape）；不伪造 in-flight cancellation。

### U1 共享 typed-action builder — Green ✓

- `agent/cli/actions.py`：CLI/TUI 共享的 pure builder（build_submit/resolve_approval/resolve_recovery/resume/cancel），按 authoritative state 取 conversation_id/next_seq/revision；legality 仍由 shared reducer 裁决。测试 5 passed（绑定 authoritative state、空 message 拒绝、exact ID binding、Cancel on EXECUTING unchanged conflict、AWAITING_RECOVERY Resume/Cancel unchanged + exact resolution 推进）。

### U2 Textual-free single-flight adapter — Green ✓

- `agent/tui/adapter.py`：`QueueingEventSink`（thread-safe，不可重入 Runtime）、`TuiAdapter.load_view`（只读 authoritative load，不调 provider/tool）、`execute_once`（single-flight gate，唯一 execution call 是 run_turn）。测试 3 passed（read-only load、execute_once、并发 single-flight 拒绝 + provider call count 1）。

### U3 literal rendering + projection — Green ✓

- `agent/tui/render.py`：`safe_display`（ANSI/C0/C1/bidi → 可见 `<U+XXXX>` escape，保留 \n/\t；超 cap 抛 `SafeDisplayTooLargeError`，不截断）+ `project` authoritative projection matrix（ready/terminal/approval/recovery/paused → main_text/form/actions/focus）+ `run_status_label`。测试 6 passed（escape ANSI/bidi/C0/C1、保留换行、cap 拒绝、ready→terminal、approval/recovery form、稳定 label）。

### U4 optional Textual app + Pilot — Green ✓

- `agent/tui/app.py`：lazy import Textual；`build_app`/`run_tui`，single-flight `@work(thread=True)` worker 调 `adapter.execute_once`，Rich `Text(safe_display(...))` literal 渲染。`--tui` 接入 main（缺失给 `TextualNotInstalledError` 安装提示）。pyproject `tui=["textual>=8.2,<9"]`。Pilot smoke（`run_test`）：submit → worker → authoritative state 推进到 COMPLETED `hello from kernel`。
- optional-dependency 测试：subprocess 屏蔽 textual → base import OK + run_tui 给安装提示。

### U5 架构 + 文档 — Green ✓

- architecture allowlist 加入 `agent/cli/actions.py`、`agent/tui/{__init__,adapter,app,render}.py`、`agent.tui` 包；EXTENSION_CONTRACTS EventSink 节 + README 增 TUI 说明。
- **TUI reference journey（Product gate）** `tests/tui/test_app.py`：Textual Pilot submit → approval/recovery/terminal parity（worker 经 adapter 调用同一 Runtime，RunResult/checkpoint 权威）。

#### 007 TUI 最终门

focused(tui+cli+event_ordering+action_legality+architecture) 58 passed；`git diff --check` OK；ruff clean；全量 **265 passed**。无第二套 loop、无 UI-only mutation、event 非权威、无 in-flight cancellation、base install 不依赖 Textual。TUI 完成。

---

## 实现者当时的六项完成声明（已被 2026-07-19 audit 降级）

实现者报告 Skill / MCP / Memory / SubAgent / Scheduler / TUI 按 002—007 串行实现，最终本地门为 **265 passed**、Ruff clean、`git diff --check` clean，且 architecture effect-owners 仍唯一。2026-07-19 audit 已确认这些自动门数值属实，但它们没有覆盖 ignored-file delivery、完整 fault/closure matrix 或用户批准的 E3 reference task，因此当前只能作为 implementation-candidate wiring evidence，不能作为“全部重接完成”的结论。







