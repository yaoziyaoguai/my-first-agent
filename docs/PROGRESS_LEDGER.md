# Progress Ledger — First Agent

**最后更新**: 2026-05-28 (Loop 3.2 SDD — architecture decision complete)

记录关键 milestones，倒序排列。每个 milestone 包含日期、commit、简述。

---

## 2026-05-28

| Milestone | Commit | 简述 |
|-----------|--------|------|
| Loop 3.2 SDD: Real SubAgent L1/L2 | — | **architecture decision complete / implementation pending** — (1) 完成全部 SubAgent 代码/测试/文档/边界读取；(2) 红队补审确认：5/5 SubAgent COMPLETE 全部降级（DEMO/FAKE_ONLY/STUB/NOT_STARTED），当前 L0 deterministic executor 不调 provider/不执行工具/不写 memory；(3) 新建 `docs/design/subagent-l1-l2-execution-contract.md`（8 sections）：L0/L1/L2 精确定义、parent-child 边界表（Tool/Memory/Skill/provider/checkpoint/dispatcher）、parent-mediated tool execution path（child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT → child result）、child provider 继承、memory scope 三种模式、skill scope 隔离、4 个新 RuntimeActionType、10 个 test intents（含 not-fakeable 防护）、implementation scope（Loop 3.2a 最小切片 + prerequisite）；(4) REAL-EVIDENCE-006 登记（真实 provider child loop + parent-mediated tool + memory scope roundtrip）；(5) 不宣称 SubAgent READY — 仍标 FAKE_DEMO→implementation pending |
| Loop 2.4: MCP Main-Path Readiness | a318237 | **code path complete, real validation pending** — (1) 新增 `MCP_BRIDGE_LIFECYCLE` RuntimeActionType（probe），bridge lifecycle 通过 disposable dispatcher 产生 evidence（与 `_try_dispatch_checkpoint_resume()` 模式一致）；(2) `MCPBridgeLifecycleHandler` 在 `phase1_hook.py` 注册（共 16 个 handler）；(3) `main.py` 新增 `_try_dispatch_mcp_bridge_lifecycle()` helper，bridge report 生成后调用；(4) `runtime_decision_frame.py` 中 `mcp.discover` DEFERRED→PARTIAL（code path complete via disposable dispatcher）、`mcp.invoke` DEFERRED→PARTIAL（MCP 工具复用统一 Tool pipeline + L3 evidence）；(5) 6 个 bridge lifecycle contract tests + 5 个 decision frame tests 更新 + 34 个已有 tests 全部通过（40/40）；(6) 32/33 MCP 回归 tests pass（1 个预先存在的 HOME 隔离测试失败）。剩余：真实 MCP server 连接（REAL-EVIDENCE-005） |
| Loop 2.2b: Skill allowed_tools enforcement | 98b4163 | **code path complete, real validation pending** — 实现 skill allowed_tools 运行时约束：(1) `ToolRuntimeMediator` 新增 `skill_allowed_tools` 参数，从 `_active_skill` 懒加载传递；(2) `ToolGateHandler.handle()` 中在 tool registry lookup 前检查 `skill_allowed_tools`，非允许工具返回 `rejected`（`policy_path: skill_allowed_tools→rejected`）；(3) `response_handlers.py` 中 `handle_tool_use_response` 从 `core._active_skill` 提取 `allowed_tools` 传入 `ToolRuntimeMediator`；(4) gate_disposition `rejected` → FORCE_STOP → 不进入 `execute_single_tool`，复用已有安全失败路径；(5) `core._update_active_skill_from_dispatcher()` 从 SKILL_SELECT success result 提取 `allowed_tools_after_selection`。15 个新 tests（6 ToolGate + 6 Mediator + 3 NotFakeable）全部通过。REAL-EVIDENCE-002（真实模型 SKILL_SELECT）和 REAL-EVIDENCE-003（real dogfood E2E）已登记；当前代码 loop 可继续；READY claim 被真实验证 debt 阻塞 |
| Loop 2.2b debt confirmation | — | REAL-EVIDENCE-002/003 已在 `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` 中确认登记，详细验证步骤、当前证据、阻塞范围均已明确 |
| Loop 2.2: Skill Activation Main-Path Completion | 2d26c2a | **PARTIAL** — bridge 已连接：(1) `phase1_hook.py`: `build_phase1_dispatcher` 接受可选 `skill_registry` 参数，避免重复扫描 filesystem；(2) `core.py`: 构建 `_skill_registry` 一次，注入 `LoopDependencies.skill_registry`，turn-end hook 从 registry 填充 `available_skill_metadata`，fake provider 路径 auto-select 第一个可见 skill；新增 `_update_active_skill_from_dispatcher()` 从 action_log 提取 SKILL_SELECT 结果并更新 `_active_skill`；(3) `prompt_builder.py`: `build_system_prompt()` 接受 `skill_registry` 和 `active_skill_section` 参数，生成 Skill 可用列表 + `[Active Skill Instructions]` section；(4) `skill_action.py`: 所有失败路径通过 `invoke_registered_target` 获取 L3 evidence chain，修复 `runtime_e2e_disqualified_reason` 导致的 evidence 降级；(5) `runtime_decision_frame.py`: `skill.select` NOT_READY→PARTIAL，`skill.apply` STUB→PARTIAL；(6) 13 L2 contract tests + 6 L3 pipeline tests + 3 skill L3 tests 全部通过。**剩余**：allowed_tools 约束 → 已在 Loop 2.2b 解决；真实模型 SKILL_SELECT tool call → REAL-EVIDENCE-002；real dogfood E2E → REAL-EVIDENCE-003 |
| Loop 2.1b: Memory shared-store L3 + store mismatch fix | 480da7e | **PARTIAL→PARTIAL** — 修复 3 个 blocker：(1) `phase1_hook.py` 提取 `_shared_store` 并传给 `MemoryRetainHandler(store=_shared_store)` 和 `MemoryRecallHandler(store=_shared_store)`，确保 retain/recall/forget 共享同一 store 实例；(2) 新增 5 个 L3 shared-store contract tests（`route_from_runtime_loop()` provenance），验证 retain→recall、retain→forget→recall、forget only shared store、handler same instance、recall sees direct add 全部通过；(3) confirmation-to-store evidence 链闭合：retain writes→shared store, recall reads→shared store, forget removes→shared store，不再有独立 store 数据分裂。ruff 通过。更新 evidence_kind_classification 和 branch_point count tests（14→15）。real dogfood E2E 已登记为 validation debt（REAL-EVIDENCE-001），不阻塞后续代码 loop |
| Loop 2.1: Memory forget → dispatcher | f229ef7 | **PARTIAL** — MEMORY_FORGET 从 direct call 迁入 dispatcher：新增 `MemoryForgetHandler`（通过 context.success/rejected/failed 返回）、`RuntimeActionType.MEMORY_FORGET` enum、evidence catalog descriptor + adapter；`core.py` 中 3 处 `_memory_runtime.remove_record()` 替换为 `_forget_via_dispatcher()`。5 个 L2 contract tests（existing/nonexistent/empty_id/evidence/side_effect）全部通过。修复 `cli_handlers.py` 同类 latent bug（`disposition=` kwarg 不存在 → context.success）。RuntimeDecisionFrame 新增 `memory.forget` branch point（PARTIAL — 缺 L3 E2E） |
| Loop 2.1: Recall direct fallback 消除 | f229ef7 | `refresh_runtime_system_prompt` 现在返回 `(system_prompt, snapshot_item_count)`，消除第 2 次 `_memory_runtime.snapshot_for_prompt()` 直接调用（仅保留 dispatcher=None 的模块初始化期 fallback）。`memory.retain` why_partial 更新（移除 forget/list/recall direct fallback 原因） |
| Loop 1.3b: Tool Path Unification — gate_disposition | 55ea045, 895123d | **COMPLETED** — gate_disposition 驱动执行流：allowed → TOOL_INVOKE → execute_single_tool → TOOL_RESULT；rejected/None → FORCE_STOP（安全失败，不执行工具）；confirmation_required → AWAITING_USER（设置 pending_tool，不执行工具）。新增 `_handle_blocked()`（写 tool_execution_log + tool_result）和 `_handle_confirmation_required()`（设置 pending_tool + save_checkpoint）。6 个新 tests（t11-t16）验证 blocked/rejected/confirmation_required/malformed 短路行为 + tool_result 保持 + TOOL_INVOKE 仅在 allowed 后 dispatch。SDD 更新至 7b 节。3705 regression tests pass |
| Loop 1.3: Tool Path Unification | b025e0d | **PARTIAL** — 方案 2（dispatcher 中介）基础设施就绪：新建 `agent/tool_runtime_mediator.py`（ToolRuntimeMediator 桥接 dispatcher lifecycle 与 execute_single_tool）；`agent/response_handlers.py` 中 `handle_tool_use_response` 不再裸调 execute_single_tool，改为通过 mediator.mediate()；SDD 明确定义方案 2 contract（`docs/design/tool-path-unification-l1.3.md`）；10 个 contract tests 验证 GATE→INVOKE→execute_single_tool→RESULT 生命周期顺序 + 防呆 + probe vs business 区分。**剩余**：TOOL_GATE 的 gate_disposition 尚未驱动执行流（blocked→FORCE_STOP 快捷路径），留待 Loop 1.3b |
| Loop 1.2: Evidence Classification Repair | — | **COMPLETED** — 新增 `is_business_capability_evidence()` in `agent/runtime_integration/evidence.py`（_BUSINESS_DISPOSITIONS + 规则：real_core_loop_runtime_e2e + business disposition = business capability evidence）；6 个新 guard tests + 1 个增强 test（24 total in test_evidence_taxonomy_guard.py）；78 evidence-related tests pass |
| Loop 1.1: Unified Runtime Decision Spine | 0ea8313, bd0a6af, e6cb970 | **COMPLETED** — 新建 `agent/runtime_decision_frame.py`（609 lines）：14 个 BranchPoint 诚实标记（0 READY / 8 PARTIAL / 1 NOT_READY / 2 DEFERRED / 1 FAKE_DEMO / 1 STUB）；RuntimeDecisionFrame 作为 core.chat() 入口 per-turn subsystem 状态描述；`docs/design/runtime-decision-spine.md` 设计文档（9 sections）；35 个 guard tests 全部通过；集成到 core.py/loop.py/display_events.py 主路径（不影响现有行为）；ruff 全部通过 |
| Loop 15: Memory Write Dispatcher Migration | ca0a03c | **COMPLETED (Phase 1-5)** — memory confirm→retain write path 从 direct `_memory_runtime` 调用迁入 dispatcher；5 个 Phase 完成：(1) handler 接受 `candidate:` 前缀 proposal_id，(2) `resolve_confirmation()` 返回 `_dispatcher_payload` 而非直接写 store，(3) `handle_memory_confirmation_reply()` 通过 dispatcher 走 `MEMORY_PROPOSE → MemoryRetainHandler`，(4) 5 个 new E2E integration tests，(5) docs finalization + commit/push。100/100 memory tests pass；11 个文件变更 |

## 2026-05-27

| Milestone | Commit | 简述 |
|-----------|--------|------|
| Loop 18: CLI Shortcut Honesty Marking | 6000a00 | **COMPLETED** — PROJECT_STATUS 中 Loop 4 CLI shortcut 条目扩展：明确标记 MUTATING/DELEGATING shortcuts（forget/delegate/nl_delegation）为 CLI-only/demo-only 直接调用，不走 dispatcher/evidence path；A4 run_summary business/probe 计数已验证正确（37 现有 tests） |
| Loop 17: Dogfood Report Reclassification | a6e0980 | **COMPLETED** — 旧 dogfood reports 重分类：2026-05-27/2026-05-26 两个 direct provider sweep report 添加 REAL_DOGFOOD_SMOKE evidence level 声明、READY→SMOKE_READY、PASS→"Direct provider smoke (non-failing)" |
| Loop 16: Evidence Taxonomy & Overclaim Guard Tests | 76db3db | **COMPLETED** — 创建 `docs/audits/2026-05-27-current-capability-recovery-map.md`（24 能力评估 + overclaim inventory + safe-to-auto-run vs architecture-decision 分类）；修复 5 个 stale claims（"limited user-usable"、"12/12 passed"、"15/15 PASS" 等）；新增 11 个 evidence taxonomy/overclaim guard tests；source-of-truth tests 68→79 |
| Memory Write Dispatcher Migration Design | — | **DESIGN COMPLETE** — `docs/design/memory-write-dispatcher-migration-design.md`（13 sections, 14 audit questions 逐条回答）；方案：复用已有 MEMORY_PROPOSE + MemoryRetainHandler，resolve_confirmation 不再直接写 store 改为返回 _dispatcher_payload 供 core.py dispatch；~50 行生产代码变更，4-5 个新测试；等待用户审批后进入 Loop 15 implementation |
| Loop 14: Evidence Pipeline Foundation | 7172d2c | **COMPLETED** — dogfood harness 证据门禁修复：expected_events 从死字段升级为 PASS 判定条件、新增 SMOKE_PASS 状态、新增 expected_business_actions 字段；memory recall 路径确认（dispatcher ✓）；PROJECT_STATUS honesty 修复（developer prototype）；8 harness evidence gate guard tests；37 harness tests PASS + 68 source-of-truth tests PASS |
| AutoRun Skill Orchestration Fix | de21474, b3f3ae3 | **COMPLETED** — `/auto-run` 从"任务调度器"升级为完整的"流程+技能+证据+回退"工程总控：新增 Workflow Stage → Skill Table（10 stage × 6 列含 failure route）、Status Promotion Gate（6 门禁）、Recursive Backtrack Policy、Claim-to-Evidence Gate、Review Failure Routing Table；Forbidden Patterns 扩展 6 项（partial fix→resolved、no-crash→PASS、admin→capability 等）；source-of-truth guard tests 60→68。根因：旧 auto-run 有 task routing 但无 stage-based skill switching、无 status promotion gate、review 失败无强制回退路由 |
| Loop 13: Evidence Honesty & Production Path Repair | — | **COMPLETED** — SUBAGENT_DELEGATE_L0 从 business→probe 重分类（每 turn routing check 不应用户可见业务动作）；新增 lifecycle check honesty guard test；evidence taxonomy guard tests 17→18；PROJECT_STATUS 剩余 P1 全部解决（**注：事后 audit 发现此条 overclaim——参见 AutoRun Skill Orchestration Fix**） |
| AutoRun Skill Router Upgrade | 855de5b | **COMPLETED** — `/auto-run` 从"单一自动执行命令"升级为"工程技能调度器"：新增 Skill Routing Policy + Skill Router Decision Table（12 任务类型 × 5 技能体系）；Continuation Policy 明确技能选择/loop 完成/review 完成不是停止条件；新增 14 个 skill routing guard tests；source-of-truth tests 41→55 |
| 全能力红队审计 | — | 15 域 (A-O) 达标审计：总分 4.2/10，2 PASS / 9 CONCERN / 4 FAIL，P0=3 / P1=10 / P2=14 / P3=5。产出审计报告 + remediation loop plan（12 loops） |
| Loop 1: Config Safety & Security Harden | — | **COMPLETED** — skip-worktree 本地保护 + pre-commit secret scan + 8 guard tests；config/config.yaml tracked 版本始终为 sk-REPLACE_ME 占位符 |
| Loop 2: Log Hygiene & Evidence Governance | — | **COMPLETED** — 50MB 自动轮转 + API key/Bearer 脱敏 + 字符串截断；21 个 log hygiene tests；773MB agent_log.jsonl 已删除；新增 tests/test_log_hygiene.py |
| Loop 3: Memory E2E 验证闭环 | 38d757a | **COMPLETED** — MEMORY_RECALL 统一走 dispatcher path；prompt_builder 支持 memory_section 参数；移除 turn-end hook 重复 dispatch；测试按 action_type 过滤非 [0] 索引；6 个文件变更；所有 P0 已解决 |
| Loop 4: Runtime Entry Consolidation | c94fc18 | **COMPLETED** — CLI READ_ONLY 命令（show memories/show subagents）走统一 dispatcher；新增 CLI_SHOW_MEMORIES/CLI_SHOW_SUBAGENTS RuntimeActionType + cli_handlers.py；loop.py 提取 _dispatch_tool_pipeline() helper 精简 turn-end hook；evidence.py 注册 catalog descriptors + adapters；新增 SubAgentRegistry overclaim 测试；7 个文件变更 |
| Loop 6: Checkpoint/Resume 能力补全 | b759e62 | **COMPLETED** — schema 版本治理（SCHEMA_VERSION="checkpoint.v1"）；v0→v1 迁移注册表；`_resolve_checkpoint_version()` 拒绝未知 future version；`_build_checkpoint_from_state()` 写入版本号；4 个 schema version 测试；2 个文件变更 |
| Loop 5: Interactive Harness 扩展 | b850605 | **COMPLETED** — 新增 4 个 cases（I-COMPLEX/I-INTERRUPT/I-STREAM/I-RESUME）；20 cases 覆盖 8 类别；修复 agent/logger.py datetime.datetime bug；3 个文件变更 |
| Loop 7: Test Taxonomy Reclassification | 0844ed8 | **COMPLETED** — 新增 evidence taxonomy guard tests (17 pass)；*_l3.py 文件名强制 REAL_CORE_LOOP/route_from_runtime_loop 引用；AST 级正向 L3+direct dispatcher.route() overclaim 检测；重命名 test_local_trace_runtime_wiring_l3.py → test_local_trace_runtime_wiring.py（trace 为纯观测基础设施） |
| Loop 8: Surgical Hub Slimming | 50bbd80 | **COMPLETED** — 行为保持型抽取：`_resolve_provider_evidence_metadata` → `agent/provider_evidence.py` (61 lines)，`_execute_subagent_delegation` → `agent/subagent_inline.py` (97 lines)；core.py: 1237 → 1112 lines (-125)；4 个文件变更；import baseline 和 top-level symbol 审计测试已同步更新 |
| Loop 9: SubAgent Boundary Hardening | b58b27b | **COMPLETED** — L0 文档化：`docs/design/subagent-boundary-architecture.md`（两条委托路径/已知限制/迁移路线图）+ `docs/CAPABILITY_BOUNDARIES.md`（skill/subagent/tool 边界不变式）；新增 CLI delegation guard test 验证 SubAgentRegistry+delegate_once 路径；修复 pre-existing capability_boundary_contract 测试失败 |
| Loop 11: Skill System Hardening | 1bd4580 | **COMPLETED** — L0 文档化：`docs/design/skill-system-architecture.md`（skill 系统架构/SKILL_SELECT dispatch/legacy 隔离）；新增 2 个 guard tests（skill_system 不 import legacy_skills、SKILL_SELECT handler 注册路径完整） |
| Loop 12: UX Hardening | e3251f6 | **COMPLETED** — 新增 `docs/onboarding/first-run-real-api-opt-in.md`（首次运行/fake mode/真实 API opt-in/provider 类型/安全警告/fake→real 迁移指南） |
| Loop 10: MCP Minimal Real Connection | — | **COMPLETED** — 新增 `docs/design/mcp-architecture.md`（7 模块架构/4 层安全隔离/3 种 bridge 模式/审计覆盖/已知限制）+ 2 个 guard tests（MCP 不 import runtime core；register_mcp_tools 是唯一 registry 连接点）；架构 boundaries 22→24 tests |
| Memory policy "请记住" 前缀修复 | 3089316 | 根因：RETAIN_PREFIXES 缺少中文礼貌形式 "请记住"，导致 policy CLARIFY→NO_OP。新增 4 个前缀 + 2 个 policy 测试 |
| Real API interactive dogfood sweep | — | 15/15 SMOKE_PASS（无 crash，非 capability PASS）— 真实 API（kimi-k2.5）交互式 dogfood，覆盖 tool/memory/subagent/edge 5 类别 |
| Runtime evidence diet | — | `classify_action_evidence_kind()` — business(7)+probe(6) 分类；run summary 集成；17 个单元测试 |
| Real API interactive dogfood authorized | — | 用户已明确授权真实 API dogfood；config/config.yaml 含真实 provider 配置，可读取用于 API 调用，不得 commit |
| Interactive dogfood harness v2 (16 cases) | — | 扩展到 16 cases (6 categories incl. I-RESUME)，补齐 I15 memory deny + I16 resume decline |
| Interactive dogfood harness 实现 + 首轮 fake/local 验证 | — | `scripts/dogfood_interactive_harness.py` — SubprocessRunner/CaseEvaluator/14-case matrix, 14/14 PASS |
| Interactive dogfood harness tests | — | `tests/test_interactive_dogfood_harness.py` — 29 tests (28 pass + 1 slow smoke) |
| Interactive dogfood harness report | — | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| Interactive dogfood harness plan | — | `docs/plans/interactive-dogfood-harness-plan-2026-05-27.md` — 18-case matrix, 3 phases, subprocess harness design |
| Global readonly audit | — | `docs/audit/global-readonly-audit-2026-05-27.md` — P0=0, P1=3, P2=7 |
| Source-of-truth repair | 2d1ea13 | 修复 root README、CURRENT_CAPABILITY_STATUS、CURRENT_AUDIT_STATUS、TEST_MATRIX、config-legacy-sunset-contract、archive/README 共 6 个冲突文档 |
| Config safety boundary clarified | — | PROJECT_STATUS 明确定义 config/config.yaml 安全边界；guard tests 扩展 |
| Dogfood evidence wording hardened | — | Evidence level 降为 REAL_DOGFOOD_SMOKE；标注 interactive path 覆盖不足 |
| Guard tests expanded | — | 新增 root README、active docs 状态口径、config 安全边界、审计引用 共 9 个测试 |
| Auto-run command hardened | f06ceb4 | `/auto-run` 命令重写为可执行规范：Startup、Task routing、Loop start、Progress rule、Hard stops、Forbidden patterns |
| Source-of-truth established | fb3712a | PROJECT_STATUS.md + PROGRESS_LEDGER.md 作为事实源；39+ 文档归档；13 个守护测试 |
| ISSUE-002 fix | e789c11 | handle_end_turn_response 返回模型正文而非空串；非交互式调用方（dogfood harness）不再收到空响应 |
| ISSUE-001 harness enhanced | e789c11 | call_agent_chat 支持 confirmation_reply 参数，自动跟进交互式确认 |
| Real API dogfood rerun | — | 20 cases → 19 non-failing / 1 CONCERN / 0 FAIL（evidence: REAL_DOGFOOD_SMOKE） |
| Ruff pre-commit fix | e789c11 | 修复 9 个 ruff 错误（I001, W293, SIM102, E501） |

## 2026-05-26

| Milestone | Commit | 简述 |
|-----------|--------|------|
| Real API full dogfood sweep | ffa5677 | 首次全量 20-case real API dogfood：18 PASS / 2 CONCERN / 0 FAIL |
| Dogfood remediation plan | ffa5677 | ISSUE-001/002 根因分析和修复计划 |
| Provider config simplification | 7c5643d | 移除 request_path/auth_scheme 用户配置面 |
| Unified project config | 7dc2abb | config/config.yaml 成为唯一推荐配置入口 |
| Legacy provider guidance guard | 1146cce | 测试防止 legacy 配置路径复活 |
| Config legacy sunset contract | — | `docs/design/config-legacy-sunset-contract.md` |

## 2026-05-25

| Milestone | Commit | 简述 |
|-----------|--------|------|
| FakeProvider scripted scenario contract | — | `docs/design/fake-provider-scripted-scenario-contract.md` |
| User-path dogfood smoke tests | — | `tests/test_user_path_dogfood.py` |
| Multiple audit reports | — | global red-team, industry gap, low-complexity, capability gap audits |
| User-usable agent runtime MVP plan | — | `docs/plans/user-usable-agent-runtime-mvp-plan.md` |

## 2026-05-22 ~ 2026-05-24

| Milestone | Commit | 简述 |
|-----------|--------|------|
| Unified runtime flow remediation | — | global runtime flow alignment across all branch points |
| Memory anchor real smoke | — | `docs/plans/2026-05-22-001-feat-memory-anchor-real-smoke-plan.md` |
| Tool confirmation anchor | — | `docs/plans/2026-05-22-002-feat-tool-confirmation-anchor-plan.md` |
| ENGINEERING_WORKFLOW.md | — | SDD→TDD→Implementation→Review→Debug loop 纪律 |
| AUTO_RUN_WORKFLOW.md | — | auto-run 命令 workflow 定义 |

## Earlier (2026-04 ~ 2026-05-21)

| Milestone | 简述 |
|-----------|------|
| Summary overclaim fix | step_complete_event 不再对未执行步骤 claim 完成 |
| Infinite loop fix | plan mode 确认后正确退出循环 |
| model_provider_required fix | 缺少 model_name 时不再 crash |
| Fake/local crash fix | FakeProvider 路径稳定性修复 |
| Memory inline confirmation | `docs/archive/design/MEMORY_INLINE_CONFIRMATION_AGENT_LOOP_DESIGN.md` |
| Checkpoint save/resume L3 | `docs/archive/implementation-notes/checkpoint-save-resume-l3.md` |
| Tool pipeline L3 completion | `docs/archive/implementation-notes/tool-pipeline-l3-completion.md` |
| Runtime integration | `docs/archive/runtime-integration/` |
| V0.1 ~ V0.5 | CLI output contract, basic TUI, manual smoke, observer audit 等 |

---

## 当前 P0/P1/P2/P3

基于 2026-05-27 全能力红队审计。详见 `docs/audits/2026-05-27-full-capability-red-team-audit.md`。

### P0（必须立即处理）

| Issue | 来源 | 状态 |
|-------|------|------|
| config/config.yaml tracked dirty（安全风险） | red-team audit | → Loop 1 |
| ~~agent_log.jsonl 773MB 无治理/可能含敏感信息~~ | red-team audit | **RESOLVED** — Loop 2 完成 |
| Memory recall 未真正进入 prompt context | red-team audit | → Loop 3 |

### P1（本阶段必须修）

| Issue | 来源 | 状态 |
|-------|------|------|
| CLI shortcut 构成第二能力平面 | red-team audit | → Loop 4 |
| Turn-end hook 过重（11 种 action） | red-team audit | → Loop 4 |
| Fake/real memory 不共享核心路径 | red-team audit | → Loop 3 |
| Memory confirm→retain→recall E2E 未验证 | red-team audit | → Loop 3 |
| Session-end extractor 过滤语义型偏好 | red-team audit | → Loop 3 |
| Resume 本质是 prompt 拼接 | red-team audit | → Loop 6 |
| 无 checkpoint schema 版本治理 | red-team audit | → Loop 6 |
| 大量 L3 标签测试实际是 L2 | red-team audit | → Loop 7 |
| Evidence overclaim (probe 计为能力) | red-team audit | → Loop 2 |
| core.py 是 god object (1172 行) | red-team audit | → Loop 8 |

### P2（近期）

详见审计报告 P2 issue list（14 项），主要集中在 Tool/SubAgent/Skill/MCP real API 覆盖不足、log/session 管理、文档偏乐观、模块级可变单例等。

### P3（排队/不修）

详见审计报告 P3 issue list（5 项）：Provider identity、Legacy skills 并存、Skill/Tool 边界模糊、文档数量过多、跨平台兼容性。
