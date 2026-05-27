# Progress Ledger — First Agent

**最后更新**: 2026-05-27

记录关键 milestones，倒序排列。每个 milestone 包含日期、commit、简述。

---

## 2026-05-27

| Milestone | Commit | 简述 |
|-----------|--------|------|
| AutoRun Skill Router Upgrade | — | **COMPLETED** — `/auto-run` 从"单一自动执行命令"升级为"工程技能调度器"：新增 Skill Routing Policy + Skill Router Decision Table（12 任务类型 × 5 技能体系）；Continuation Policy 明确技能选择/loop 完成/review 完成不是停止条件；新增 14 个 skill routing guard tests；source-of-truth tests 41→55 |
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
| Real API interactive dogfood sweep | — | 15/15 PASS — 真实 API（kimi-k2.5）交互式 dogfood，覆盖 tool/memory/subagent/edge 5 类别 |
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
