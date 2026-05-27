# Progress Ledger — First Agent

**最后更新**: 2026-05-27

记录关键 milestones，倒序排列。每个 milestone 包含日期、commit、简述。

---

## 2026-05-27

| Milestone | Commit | 简述 |
|-----------|--------|------|
| Runtime evidence diet | — | `classify_action_evidence_kind()` — business(7)+probe(6) 分类；run summary 集成；17 个单元测试 |
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

## 当前 P1/P2/P3

### P1（本轮修复中）

| Issue | 来源 | 状态 |
|-------|------|------|
| config/config.yaml tracked dirty 安全边界 | audit 2026-05-27 | 文档化边界，不修改文件 |
| active docs 与 PROJECT_STATUS 冲突 | audit 2026-05-27 | 6 个文件已修复 |
| dogfood evidence 口径过乐观 | audit 2026-05-27 | 已降为 REAL_DOGFOOD_SMOKE |

### P2（下一步）

| Issue | 来源 | 决策 |
|-------|------|------|
| Real API opt-in dogfood | interactive harness report 2026-05-27 | 下一步 — fake/local harness 就绪，待用户授权 |
| core.py / loop.py 过大 | audit 2026-05-27 | harness 就绪后 surgical slim |
| provider diagnostics legacy 建议 | audit 2026-05-27 | 延后 |
| dogfood scripts stateful | audit 2026-05-27 | 延后 |

### P3（延后/不修）

| Issue | 来源 | 决策 |
|-------|------|------|
| Provider identity（"我是 Claude"） | A1 dogfood | 不修 |
| Product context（I1/I7） | dogfood | 延后 |
| C1 event counting bug | harness | 延后 |
| OpenAI-compatible streaming fail-closed | design | 延后 |
| Memory consolidation deferred | design | 不修 |
| SubAgent L1-L5 | design | 不修 |
