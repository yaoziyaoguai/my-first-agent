# Project Status — First Agent

**最后更新**: 2026-05-29 (Batch A attribution corrected + Batch B SDD complete)
**状态**: Batch A evidence hardening: 004 direct-fallback removed (credible), 007 real StdioMCPClient verified (partial-credible)；004 B1/B2 归因已修正; Batch B SDD complete — Scheduler main-path injection design ready; current score 3.5/5；REAL-EVIDENCE closure credibility = 3-4/8 credible

本文档是 Coding Agent 和人类开发者的**第一优先读取入口**。如果其他文档与本文档冲突，以本文档为准。

---

## 0. Independent Re-Audit Override (2026-05-29)

本节是当前最新事实源。下方历史段落保留当时登记的修复和验证流水；如果历史段落仍写有 `ALL REAL-EVIDENCE CLOSED`、`8/8 validated` 或某 subsystem `VALIDATED`，以本节的独立复审口径为准。

### Current Verdict

| 项目 | 当前复审结论 |
|------|--------------|
| 原 redteam inferred score | 1.4/5 |
| 当前 independent re-audit score | 3.5/5 (was 3.2/5 — Batch A evidence hardening completed) |
| 总体判断 | 相比原 redteam 明显改善；Batch A 硬化了 004/007 的证据链；004 B1/B2 归因已修正（非 confirmation='always' 阻止工具执行，而是 checkpoint save trigger condition not met）；008 Batch B SDD complete；003/006 仍 questionable (defer) |
| REAL-EVIDENCE closure credibility | 3-4/8 credible (004 hardened + 007 partial-credible)；4-5/8 questionable |
| 核心 runtime milestone | PARTIAL / code-path-heavy validated；Batch A 移除了 004 direct-save fallback + 007 direct execute_tool() |
| 明确排除 | B7 Multi-instance readiness；B8 TUI architecture；006 TOOL_MEDIATOR_GAP (defer)；003 claim downgrade |

主要纠偏点：
- `RuntimeDecisionFrame` registry 当前仍没有 READY branch point，状态文档不能把它当作完全 READY 事实源。
- Skill allowed_tools 的 contract path 有效，但 real dogfood 没有证明 same-turn disallowed-tool blocking。
- Checkpoint validation 有 direct-save fallback，real provider 部分仍有 concern，不能称为 true resume fully validated。
- MCP bridge readiness 可信；MCP external flight 仍主要是 direct `execute_tool()`，不是完整 model-selected runtime path。
- SubAgent L1 child loop 有进展；production delegation path 未实际传入 `ToolRuntimeMediator` 触发 child tool mediation。
- Scheduler 有代码和手动 harness；默认 `core.chat()` 没有注入 `ActionScheduler`，不应标为 main-path validated。

### Corrected Current Loop Scores

| Loop | 当前复审状态 | Score | 说明 |
|------|--------------|------:|------|
| Loop 1.1 Unified Runtime Decision Spine | CODE_PATH_COMPLETE | 3 | frame/dispatcher 已集成；registry 仍全 PARTIAL |
| Loop 1.2 Evidence Classification Repair | VALIDATED | 4 | guard code/tests 可信；result JSON 仍可增强 |
| Loop 1.3 Tool Path Unification | VALIDATED | 4 | model tool-use path 经 ToolRuntimeMediator |
| Loop 2.1 Explicit Memory Main-Path Completion | VALIDATED | 4 | REAL-EVIDENCE-001 可信，但 provenance 有局部 caveat |
| Loop 2.2 Skill Activation / allowed_tools | PARTIAL | 3 | post-turn activation/contract 有效；same-turn real blocking 未证实 |
| Loop 2.3 Storage / Checkpoint True Resume | VALIDATED | 4 | Batch A hardened: direct-save fallback removed, Part A 10/10 PASS；Part B 2 CONCERN — checkpoint save trigger condition not met (tools executing but no save point reached) |
| Loop 2.4 MCP Main-Path Readiness | PARTIAL | 3 | bridge readiness 可信；main runtime E2E 未证实 |
| Loop 3.2 Real SubAgent L1/L2 | PARTIAL | 3 | L1 loop/result 有进展；child tool mediation 未走 core path |
| Loop 3.3 Real MCP External Flight | PARTIAL | 3 | Batch A hardened: real StdioMCPClient bridge + TOOL_REGISTRY verified；model-selected invocation pending (Guardrail 1) |
| Loop 3.4 Advanced Scheduler | PARTIAL | 2 | Batch B SDD complete — scheduler main-path injection design ready; implementation pending: core.chat() 需支持 ActionScheduler 注入; 008 原 CLOSED 标记为 overclaim (manual harness ≠ main-path evidence) |
| Loop 4.1 Dogfood / Evaluation Harness Honesty | VALIDATED | 4 | honesty guard 可信 |
| Loop 4.2 UX / Error Recovery / Storage Hygiene | CODE_PATH_COMPLETE | 4 | hardening 完成；不是核心能力 completion proof |

### Corrected REAL-EVIDENCE Closure Credibility

| ID | Capability | Closure credibility | Notes |
|----|------------|---------------------|-------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | credible | positive assertions 充分；局部 direct dispatcher provenance caveat |
| REAL-EVIDENCE-002 | Skill selection | questionable | deterministic fallback/post-turn activation，不是 model-owned skill tool selection |
| REAL-EVIDENCE-003 | Skill allowed_tools | questionable | contract tests 可信；real dogfood 未证明 same-turn disallowed blocking |
| REAL-EVIDENCE-004 | Checkpoint save/resume | **credible** (hardened) | Batch A: direct-save fallback removed (Guardrail 2)；Part A 10/10 PASS (CHECKPOINT_PATH redirection fix)；Part B 2 CONCERN — tools executing (tool.gate/invoke/result in action_log) but no checkpoint save point reached |
| REAL-EVIDENCE-005 | MCP bridge readiness | credible | local stdio fixture discovery/register/visibility/allowlist 可信 |
| REAL-EVIDENCE-006 | SubAgent L1 | questionable | child loop/result 有价值；child tool mediation 未在 core delegation path 证实 |
| REAL-EVIDENCE-007 | MCP external flight | **partial-credible** (hardened) | Batch A: real StdioMCPClient bridge PASS (W1/W2: 2 tools registered)；model-selected invocation CONCERN (W3-W6: Guardrail 1)；不再使用 direct execute_tool() |
| REAL-EVIDENCE-008 | Advanced scheduler | questionable → **Batch B SDD complete** | ActionScheduler code + loop.py integration exist but core.chat() 不注入 → dead code in default path; 原 CLOSED 为 overclaim (manual harness); Batch B SDD defines main-path injection plan; implementation pending |

**Batch A completed (2026-05-29)**: 004 direct-fallback removed + 007 real StdioMCPClient verified. **004 B1/B2 归因修正 (2026-05-29)**: action_log 中 tool.gate/invoke/result 均存在 → 工具执行管道活跃，根因非 confirmation='always' 阻止工具执行，而是 checkpoint save trigger condition not met。**Batch B SDD complete (2026-05-29)**: `docs/design/batch-b-scheduler-main-path-injection.md` — 008 原 CLOSED 为 overclaim (manual harness)，需 code-path hardening 让 ActionScheduler 进入 core.chat() 默认 main runtime path。003/006 still questionable per independent re-audit.

---

## 1. 当前状态快照

### Real API Dogfood (direct provider call)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 结果 | **19 non-failing / 1 CONCERN / 0 FAIL**（共 20 cases） |
| 执行日期 | 2026-05-27 |
| Evidence level | **REAL_DOGFOOD_SMOKE** |

### Real API Interactive Dogfood (subprocess + full runtime)

| 指标 | 值 |
|------|---|
| 最新报告 | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 结果 | **15/15 PASS（0 CONCERN / 0 FAIL）** |
| Provider | kimi-k2.5 via anthropic_compatible (DashScope) |
| 执行日期 | 2026-05-27 |
| 耗时 | 118.5s |
| Evidence level | **REAL_API_INTERACTIVE_SMOKE** |
| Harness | `scripts/real_api_interactive_dogfood_sweep.py` |
| 结果 JSON | `docs/dogfood/real-api-interactive-dogfood-results-2026-05-27.json` |

**已验证的交互路径**：
- y/n tool confirmation（R06-R08）— real API 下正确处理
- memory proposal + accept/deny（R09-R11）— 流程正常
- subagent delegation（R12-R13）— 委托标记正常
- 不存在工具的安全错误恢复（R14）— 不 crash
- 多约束复杂中文任务（R15）— 19.7s 完成，不超时
- secret 拒绝（R03）— 不泄露 API key

### Interactive Dogfood Harness

| 指标 | 值 |
|------|---|
| Harness | `scripts/dogfood_interactive_harness.py` — 完成（870+ lines, 16 cases） |
| 测试 | `tests/test_interactive_dogfood_harness.py` — 28 pass + 1 slow smoke |
| Fake/local cases | 16/16 PASS（6 类别：I-SANITY/I-CONFIRM/I-TOOL/I-MEMORY/I-STREAM/I-RESUME） |
| 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| Case matrix | `docs/dogfood/interactive-dogfood-case-matrix-2026-05-27.md` |
| 结果 JSON | `docs/dogfood/interactive-dogfood-results-2026-05-27.json` |
| Evidence level | **FAKE_LOCAL_SMOKE** — FakeProvider 下验证交互路径正确性 |

### Fake/Local Gate

| 指标 | 值 |
|------|---|
| FakeProvider 契约 | `docs/design/fake-provider-scripted-scenario-contract.md` |
| 用户路径 dogfood | `tests/test_user_path_dogfood.py` — PASS |
| Runtime 集成测试 | `tests/runtime_integration/` — PASS |

### Log Hygiene (Loop 2 — COMPLETED)

| 项目 | 值 |
|------|---|
| 大小上限 | 50MB（`MAX_LOG_SIZE_BYTES` in config.py） |
| 轮转策略 | rename 为 `agent_log.archived-YYYYMMDD-HHMMSS.jsonl`（原子 rename） |
| 脱敏规则 | `sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}` → `sk-***REDACTED***`；`Bearer *{20,}` → `Bearer ***REDACTED***` |
| 字符串截断 | >2000 字符自动截断 |
| 递归深度 | 最大 5 层，超出返回 `<nested-too-deep>` |
| 写入路径覆盖 | Path A (logger.log_event, 7 modules) + Path B (runtime_observer.log_event, 5 modules) |
| 旧 773MB 日志 | 已删除（用户授权） |
| 测试 | `tests/test_log_hygiene.py` — 21 tests (4 classes: Sanitization/Rotation/E2E/Boundary) |

### Config Safety (Loop 1 — COMPLETED)

| 项目 | 值 |
|------|---|
| 推荐入口 | `config/config.yaml`（provider section） |
| 安全默认 | `enabled: false, type: fake` — 零 API key 可运行 |
| API key | 个人本地项目直接写在 `config/config.yaml` 的 `api_key` 字段，不可 commit |
| tracked 版本 | `api_key: sk-REPLACE_ME`（占位符），安全 |
| 本地保护 | `git update-index --skip-worktree config/config.yaml` — 防止误 stage |
| 预防层 1 | pre-commit hook 扫描 staged diff 中的真实 key 特征 (sk-sp-/sk-ant-/sk-or-) |
| 预防层 2 | `tests/test_config_secret_safety.py` — 8 个 guard tests 验证 config examples/tracked/staged |
| Legacy 路径 | `FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER` 已 deprecated |
| .env | **不作为当前推荐主路径**；仅作为兼容层保留 code path |

### 已修复的关键 Bug

| Issue | 描述 | 状态 |
|-------|------|------|
| ISSUE-002 (G2) | handle_end_turn_response 返回空串 | **FIXED** (e789c11) |
| ISSUE-001 (C1) | 非交互式 harness 无法处理 confirmation | **HARNESS ENHANCED** (e789c11) |
| 无限循环 | plan mode 确认后不退出的死循环 | 已修复 |
| summary overclaim | step_complete_event 对未执行步骤宣称完成 | 已修复 |
| model_provider_required | 缺少 model_name 时 crash | 已修复 |

### Memory E2E (Loop 3 — COMPLETED)

| 项目 | 值 |
|------|---|
| Commit | `38d757a` |
| 核心变更 | `refresh_runtime_system_prompt()` 将 MEMORY_RECALL 统一走 dispatcher path，不再直接调 `_memory_runtime.snapshot_for_prompt()` |
| Memory recall 路径 | 统一 → `route_from_runtime_loop(request)` → dispatcher → handler → `build_system_prompt(memory_section=...)` |
| fallback | dispatcher 为 None 时保留直接 `snapshot_for_prompt()` 路径（测试/dogfood 兼容） |
| prompt_builder | `build_system_prompt(memory_section=...)` 支持可选预渲染 memory 段 |
| turn-end hook | 移除重复 MEMORY_RECALL dispatch，只保留 MEMORY_TURN_END_PROPOSAL + MEMORY_PROPOSE |
| 测试更新 | `spy.route_calls[0]` → 按 `RuntimeActionType.MEMORY_TURN_END_PROPOSAL` 过滤（MEMORY_RECALL 先于 turn-end hook 触发） |
| import baseline | `test_architecture_boundaries.py` 添加 `agent.runtime_integration.schema`（local import in `refresh_runtime_system_prompt()`） |
| 回归基线 | 80 失败全部为已有（缺失过期文档、README 内容不匹配等），非 Loop 3 引入 |

### Evidence Kind 分类

| 指标 | 值 |
|------|---|
| 实现 | `classify_action_evidence_kind()` in `agent/runtime_integration/schema.py` |
| 测试 | `tests/unit/test_evidence_kind_classification.py` — 17 PASS |
| Run summary 集成 | `agent/loop.py` — `_emit_run_summary` 统计 business/probe 计数 |
| 分类 | business: 6 类型（TOOL_REQUEST/INVOKE/RESULT, MEMORY_PROPOSE, STREAMING_PROVIDER_CALL/EVENT）+ CLI_SHOW_MEMORIES/CLI_SHOW_SUBAGENTS |
| | probe: 7 类型（SKILL_SELECT, TOOL_GATE, MEMORY_TURN_END_PROPOSAL/RECALL/CONSOLIDATE, CHECKPOINT_SAFE_SUMMARY, SUBAGENT_DELEGATE_L0） |

### Evidence Honesty (Loop 13 — COMPLETED)

| 项目 | 值 |
|------|---|
| 核心变更 | `SUBAGENT_DELEGATE_L0` 从 `business` 重分类为 `probe` — 它是每 turn routing check，非用户可见业务动作 |
| 测试更新 | `test_evidence_kind_classification.py` 更新分类断言；新增 `test_lifecycle_checks_are_probe_not_business` guard test |
| Evidence taxonomy guard tests | 17→18（新增 lifecycle check honesty guard） |
| 影响 | `_emit_run_summary` 中 SUBAGENT_DELEGATE_L0 的 rejected routing check 不再计入 business_events |

### Evidence Classification Repair (Loop 1.2 — COMPLETED)

| 项目 | 值 |
|------|---|
| 核心函数 | `is_business_capability_evidence()` in `agent/runtime_integration/evidence.py` |
| 新增常量 | `_BUSINESS_DISPOSITIONS` — 10 个有效业务 disposition |
| Guard tests | `test_evidence_taxonomy_guard.py` — 24 tests（3 原有 + 6 新增 + 1 增强） |

**编码规则**：
- `real_core_loop_runtime_e2e` ≠ business capability complete — routing evidence 不等于业务能力证明
- 必须同时满足：主路径 routing provenance（REAL_CORE_LOOP_RUNTIME_E2E）+ 有效业务 disposition（allowed/recalled/retain/executed/...）
- disposition=noop/no_action/rejected/insufficient_evidence 等即使通过主路径也不构成业务能力证据

### Runtime Decision Spine (Loop 1.1 — COMPLETED)

| 项目 | 值 |
|------|---|
| 模块 | `agent/runtime_decision_frame.py`（609 lines） |
| 设计文档 | `docs/design/runtime-decision-spine.md`（9 sections） |
| Branch points | 14 个预定义，注册表冻结（MappingProxyType） |
| 诚实标记 | 0 READY / 8 PARTIAL / 1 NOT_READY / 2 DEFERRED / 1 FAKE_DEMO / 1 STUB |
| Guard tests | `tests/unit/test_runtime_decision_frame.py` — 35 PASS |
| 主路径集成 | core.py（+13 行）、loop.py（+9 行）、display_events.py（+3 行） |
| 设计原则 | 描述不执行、诚实标记、有限 branch point、证据等级绑定、frozen dataclass |

**各子系统 Branch Point 状态**：

| Branch Point | 状态 | 证据等级 | 说明 |
|-------------|------|---------|------|
| skill.select | PARTIAL | REAL_DOGFOOD_SMOKE | registry 注入、body load、post-turn `_active_skill` 设置已验证；但真实路径是 deterministic keyword fallback，不是 model-owned skill tool selection；REAL-EVIDENCE-002 独立复审为 questionable |
| skill.apply | PARTIAL | CONTRACT_PLUS_DOGFOOD | allowed_tools contract path 有效；real dogfood 有 TOOL_GATE/INVOKE/RESULT evidence chain，但未证明 same-turn disallowed-tool blocking；REAL-EVIDENCE-003 独立复审为 questionable |
| mcp.discover | PARTIAL | REAL_EVIDENCE_SMOKE | local stdio fixture bridge discovery/register/visibility/allowlist 可信；REAL-EVIDENCE-005 独立复审为 credible |
| mcp.invoke | PARTIAL | REAL_STDIO_BRIDGE_REGISTERED | Batch A hardened: real StdioMCPClient bridge → TOOL_REGISTRY verified (W1/W2 PASS)；model-selected invocation pending (Guardrail 1)；不再 direct execute_tool()；REAL-EVIDENCE-007 独立复审 partial-credible |
| subagent.delegate | PARTIAL | REAL_DOGFOOD_SMOKE | L1 child provider loop/result/adjudication 有证据；production delegation path 未实际传入 `ToolRuntimeMediator` 触发 child tool mediation；REAL-EVIDENCE-006 独立复审为 questionable |
| memory.recall/propose/retain/forget | PARTIAL | REAL_PROVIDER_E2E | retain/recall/forget 行为闭环可信；registry 仍是 PARTIAL，且部分 path 使用 direct dispatcher provenance；REAL-EVIDENCE-001 独立复审为 credible |
| tool.gate/invoke/result | CODE_PATH_COMPLETE | REAL_CORE_LOOP_RUNTIME_E2E | model `tool_use` 已经通过 ToolRuntimeMediator 进入 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT；MCP direct evidence 不应借此升级为 full MCP runtime E2E |
| checkpoint.save/resume | PARTIAL | CONTRACT_PLUS_DOGFOOD | Batch A hardened: direct-save fallback removed (Guardrail 2), Part A 10/10 PASS (CHECKPOINT_PATH redirection)；Part B 2 CONCERN per stop condition (confirmation='always')；REAL-EVIDENCE-004 独立复审 credible |
| trace.summary | PARTIAL | FAKE_LOCAL_USER_PATH | in-memory action_log，无 durable store |

**Overclaim 防护规则**：
- `is_capability_complete()` = status==READY AND evidence_level >= FAKE_LOCAL_USER_PATH
- `should_not_silent_pass()` = status in (NOT_READY, DEFERRED, STUB)
- 禁止：status=PARTIAL + "capability complete"、status=FAKE_DEMO + "E2E verified"、evidence_level=GUARD_TEST + "COMPLETE"、no-crash → PASS

### 已知剩余 Issues（Loop 14 审计更新）

**项目当前阶段：developer prototype / developer-dogfood。** 不可标 user-usable。

#### P1（已解决 — Loop 14）

| Issue | 来源 | 状态 |
|-------|------|------|
| Dogfood harness expected_events 死字段（不参与 PASS 判定） | Loop 14 G-Stack audit | **RESOLVED** — CaseEvaluator 检查 expected_events，缺失降为 CONCERN |
| Dogfood harness no-crash → PASS（空断言 case 不应标 capability PASS） | Loop 14 G-Stack audit | **RESOLVED** — 新增 SMOKE_PASS 状态，8 个 guard tests |
| Dogfood harness expected_business_actions 缺失 | Loop 14 G-Stack audit | **RESOLVED** — CaseSpec 新字段 + BUSINESS_ACTION_PATTERNS 检测 |

#### P2（近期）

| Issue | 来源 | 状态 |
|-------|------|------|
| Memory confirm→retain write path 仍直调 _memory_runtime，不走 dispatcher | Loop 14 analysis | **RESOLVED** — Loop 15 Phase 1-4 completed；`resolve_confirmation()` 返回 `_dispatcher_payload`；`handle_memory_confirmation_reply()` 通过 dispatcher 走 `MEMORY_PROPOSE → MemoryRetainHandler`；100/100 memory tests pass |
| Memory extractor zero proposals | red-team audit | **PARTIAL** — 内联路径已部分修复 |
| PROJECT_STATUS 历史 overclaim 清理 | Loop 13 review | **PARTIAL** — Loop 13 overclaim 已在 AutoRun fix 中回退；PROJECT_STATUS 不再包含 false RESOLVED |

#### 已确认修复（证据充分）

| Issue | 证据 |
|-------|------|
| Config safety (Loop 1) | skip-worktree + pre-commit hook + 8 guard tests |
| Log hygiene (Loop 2) | 50MB rotation + sanitization + 21 log hygiene tests |
| Memory recall → prompt context (Loop 3) | 统一走 dispatcher path（`refresh_runtime_system_prompt(dispatcher=...)`） |
| CLI shortcut (Loop 4) | CLI READ_ONLY 命令（show memories/show subagents）走统一 dispatcher；**MUTATING/DELEGATING shortcuts（forget/delegate/nl_delegation）仍为 CLI-only/demo-only 直接调用，不走 dispatcher/evidence path** — 待 confirmation pipeline 就绪后迁入 |
| Turn-end hook (Loop 4) | 提取 _dispatch_tool_pipeline() helper |
| Checkpoint schema version (Loop 6) | SCHEMA_VERSION + _MIGRATION_REGISTRY |
| Test taxonomy (Loop 7) | evidence taxonomy guard tests + file rename |
| Evidence overclaim: SUBAGENT_DELEGATE_L0 (Loop 13) | business→probe 重分类 + lifecycle guard test |
| core.py god object (Loop 8) | 抽取 provider_evidence + subagent_inline (1237→1112 lines) |

#### P3（排队/不修）

| Issue | 状态 |
|-------|------|
| RESUME_PROMPT 全量检测 | 不修 — checkpoint 设计行为 |
| Provider identity "我是 Claude" | 不修 |
| Product context (I1/I7) | 延后 |

---

## 2. 推荐下一步

**Loop 4.2 完成。** 本轮为 product hardening——所有变更均为防御性错误处理、用户可见通知和存储整洁性改进，不新增核心能力。Provider error 不再 crash（RuntimeEvent fallback），scheduler node failure 用户可见通知，checkpoint resume 有确认消息，session/file hygiene 就位，trace report 覆盖 Skill/MCP/Scheduler evidence。

**全部 safe-to-auto-run code loops 已闭环。所有 REAL-EVIDENCE (001-008) 全部 CLOSED。Batch A evidence hardening (2026-05-29): 004/007 证据加固。** 剩余待办项：架构决策（B7/B8）+ Batch B (008 Scheduler main-path injection)。

基于 2026-05-28 红队补审报告（`docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md`），
真实完成率仅 23.1%（27/117），根因为缺少 runtime-owned decision vocabulary。

**新 Roadmap（按红队补审推荐的 loop 顺序）**：

| Loop | 描述 | 状态 |
|------|------|------|
| Loop 1.1 | Unified Runtime Decision Spine | **COMPLETED** — 已实现 |
| Loop 1.2 | Evidence Classification Repair | **COMPLETED** — 已实现 |
| Loop 1.3 | Tool Path Unification | **COMPLETED** — 方案 2（dispatcher 中介）完整实现，gate_disposition 驱动执行流 |
| Loop 2.1 | Explicit Memory Main-Path Completion | **VALIDATED with caveat** — REAL-EVIDENCE-001 独立复审为 credible；retain/recall/forget 行为和 store assertions 充分，但部分 provenance 仍是 direct dispatcher route |
| Loop 2.2 | Skill Activation Main-Path Completion | **PARTIAL** — body injection/post-turn activation/allowed_tools contract path 有效；REAL-EVIDENCE-002/003 独立复审为 questionable，因为 same-turn real blocking 和 model-owned skill selection 未证实 |
| Loop 2.3 | Storage/Checkpoint True Resume | **VALIDATED** — Batch A hardened: direct-save fallback removed, Part A 10/10 PASS (CHECKPOINT_PATH redirection + Guardrail 2 enforcement)；Part B 2 CONCERN per documented stop condition (confirmation='always') |
| Loop 2.4 | MCP Main-Path Readiness | **PARTIAL** — REAL-EVIDENCE-005 bridge readiness credible；Batch A: 007 real StdioMCPClient verified (W1/W2 PASS)；model-selected invocation pending (Guardrail 1) |
| Loop 3.2 | Real SubAgent L1/L2 | **PARTIAL** — L1 child provider loop/result/adjudication 有进展；REAL-EVIDENCE-006 独立复审为 questionable，child tool mediation 未在 core delegation path 证实；L2 不在本阶段范围 |
| Loop 3.3 | Real MCP External Flight | **QUESTIONABLE** — REAL-EVIDENCE-007 独立复审为 questionable；当前是 direct `tool_registry.execute_tool()` → stdio fixture，不是 full runtime-mediated path |
| Loop 3.4 | Advanced Scheduler | **PARTIAL** — scheduler code/tests/manual harness 存在；REAL-EVIDENCE-008 独立复审为 questionable，因为默认 `core.chat()` 未注入 `ActionScheduler`，没有 real model-generated plan main-path proof |
| Loop 4.1 | Evaluation/Dogfood Harness Honesty | **code path complete** — (1) `agent/evaluation_honesty.py`（~220 lines）：EvidenceClassification 4 级枚举 + EvaluationEvidence/EvaluationReport dataclass + classify_evaluation/classify_smoke_vs_capability 分类引擎；(2) NON_CAPABILITY_PROVIDERS/ASSERTIONS + CAPABILITY_ASSERTIONS frozenset 定义；(3) `scripts/dogfood_interactive_harness.py` CaseResult 新增 evidence_classification 字段；(4) 41 个 guard tests（`tests/unit/test_evaluation_honesty.py`，10 classes）全部通过；(5) SMOKE_PASS ≠ CAPABILITY_PASS——fake/local/no-crash/expected_events 不能关闭 REAL-EVIDENCE debt |
| Loop 4.2 | UX / Error Recovery / Storage Hygiene | **COMPLETED** — product hardening, not new core capability: (1) provider error → RuntimeEvent fallback（`_call_model()` catch ProviderError → `control_message()` → empty ProviderResponse，不 crash）；(2) scheduler node failure → RuntimeEvent notification（`run_main_loop()` 检测 halted status → `control_message()` 显示 node title + error）；(3) checkpoint resume → `[系统] 正在恢复上次对话状态...` RuntimeEvent 在 session.py 中 emit；(4) storage hygiene: `.gitignore` 添加 `state.json`/`runs/`；(5) trace report enrichment: `_emit_run_summary()` 含 skill_activations/skill_names/mcp_tool_invocations/scheduler_plan_steps；(6) 6 streaming protocol tests + 4 个 contract confirmations 通过；ruff clean；568/574 tests pass（6 pre-existing failures） |

**已完成的历史 loops（安全可自动修）**：
- Loop 14-18, Loop 15 (Memory Write Dispatcher), Loop 1-13 — 详见 PROGRESS_LEDGER

**需要架构决策的项目（B2-B8）**：
| Item | 描述 | 状态 |
|------|------|------|
| B2 | CLI delegate shortcut → dispatcher | **DONE** — delegate shortcut 已迁入 dispatcher-mediated path（_dispatch_or_fallback_delegation → SUBAGENT_DELEGATE_L1），L1 handler/provider 可用时走 L1，不可用时 fallback 到 L0 inline |
| B3 | SubAgent L1/L2 成熟化 | 需要真实 subagent execution |
| B4 | MCP real connection | PARTIAL — bridge readiness credible；external invocation 仍是 direct registered-tool execution，非完整 runtime-mediated MCP E2E |
| B5 | Skill runtime 深化 | code path complete — body 注入 + allowed_tools enforcement 已实现；缺真实模型 SKILL_SELECT + real dogfood E2E（REAL-EVIDENCE-002/003） |
| B6 | Checkpoint true state restoration | QUESTIONABLE — handler path 存在；REAL-EVIDENCE-004 closure 被 direct-save fallback 和 real-provider concerns 削弱 |
| B7 | Multi-instance readiness | 需要消除模块级单例 |
| B8 | TUI architecture | 需要 TUI framework decision |

**剩余 PARTIAL**：
- Memory extractor zero proposals（procedural 走 inline confirmation，episodic 可能需要 extractor redesign）

**Loop 4.2 hardening 完成。** 按 2026-05-29 independent re-audit，Real Evidence closure credibility 为 2/8 credible、6/8 questionable；不能再表述为 8/8 fully validated。B7 (Multi-instance) 与 B8 (TUI) 仍是后续架构/产品化决策，本轮排除。

---

## 3. 活跃约束

- `config/config.yaml` 可含真实 API key，**不得 commit**
- `.env` **不得 commit**
- `agent_log.jsonl` **不得 commit**
- sessions/runs/private data **不得 commit**、不得作为测试素材
- 不调用真实 API（除非明确需要的 dogfood 最小验证）
- 不读取真实私人资料
- 不新增 Anchor / 第二条主流程
- 所有工程操作通过 auto_run 推进

---

## 4. Config 规则

```
推荐：config/config.yaml  provider.api_key（个人本地项目直接写入）
安全默认：provider.enabled: false, type: fake
Legacy（不推荐）：.env / FIRST_AGENT_PROVIDER_PROFILE / MY_FIRST_AGENT_LLM_PROVIDER
```

`request_path`、`auth_scheme` 由 provider adapter 内部决定，不出现在用户配置面。

**配置安全边界**：
- `config/config.yaml` 当前可能是用户本地真实配置（含 api_key），**auto-run 和 Coding Agent 不得 commit 此文件**
- 只能通过 `git diff --stat` / `git status` 检查其状态，不得读取内容
- 如果 staged diff 包含 key-shaped fragment，立即 hard stop
- `.gitignore` 已覆盖 `.env`、`agent_log.jsonl`、`sessions/`、`runs/`、`memory/`、`workspace/`

---

## 5. 文档导航

| 想了解 | 读这里 |
|--------|--------|
| 当前项目状态 | `docs/PROJECT_STATUS.md`（本文件） |
| 进度账本 | `docs/PROGRESS_LEDGER.md` |
| 工程流程 | `docs/dev/AUTO_RUN_WORKFLOW.md`、`docs/dev/ENGINEERING_WORKFLOW.md` |
| 最新 dogfood (direct) | `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` |
| 最新 dogfood (interactive) | `docs/dogfood/real-api-interactive-dogfood-report-2026-05-27.md` |
| 交互式 harness 报告 | `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md` |
| 交互式 harness plan | `docs/plans/interactive-dogfood-harness-plan-2026-05-27.md` |
| 全能力红队审计 | `docs/audits/2026-05-27-full-capability-red-team-audit.md` |
| 最新审计（全局） | `docs/audit/global-readonly-audit-2026-05-27.md` |
| Remediation loop plan | `docs/plans/2026-05-27-capability-remediation-loop-plan.md` |
| 修复计划 | `docs/plans/source-of-truth-repair-plan-2026-05-27.md` |
| 能力边界定义 | `docs/CAPABILITY_BOUNDARIES.md` |
| SubAgent 边界架构 | `docs/design/subagent-boundary-architecture.md` |
| Skill 系统架构 | `docs/design/skill-system-architecture.md` |
| MCP 系统架构 | `docs/design/mcp-architecture.md` |
| MCP Real External Flight 契约 | `docs/design/mcp-real-external-flight-contract.md` |
| Runtime Decision Spine 设计 | `docs/design/runtime-decision-spine.md` |
| Memory Write Dispatcher 迁移设计 | `docs/design/memory-write-dispatcher-migration-design.md` |
| 首次运行 & 真实 API | `docs/onboarding/first-run-real-api-opt-in.md` |
| 配置示例 | `config/config.example.yaml` |
| 运行时宪法 | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` |
| 历史文档 | `docs/archive/` |

---

## 6. Auto-Run 规则

每次 auto_run 启动必须先读：

1. `docs/PROJECT_STATUS.md` — 当前状态
2. `docs/PROGRESS_LEDGER.md` — 进度历史
3. `docs/dev/AUTO_RUN_WORKFLOW.md` — workflow 定义
4. 当前任务相关 report/plan

auto_run 不要求从头开始全 loop；根据任务类型选择合适的 loop 起点。

### Auto-Run 授权状态

用户已明确授权的操作范围：
- **真实 API dogfood** — 已授权，可读取 config/config.yaml 中的真实 provider 配置用于 API 调用，不得 commit
- **agent_log.jsonl 删除** — 已授权
- **按审计文档修复 P0/P1** — 已授权，安全范围内的自动修复
- **自动继续 loop** — 已完成一个 loop 后，如无 hard stop，自动继续下一 loop，不需要每轮都问用户

不得在已授权范围内反复请求授权。

---

## 7. Owner Notes

- 项目定位：个人学习/实验项目，非生产系统
- 不追求 feature completeness，追求可理解性、可审计性、可持续性
- 文档宁可少而准，不可多而乱
