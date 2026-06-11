# Current Architecture Repair Roadmap (v2)

> 状态：active repair in progress — 2026-06-11/12 实施
> 创建日期：2026-06-11
> 本轮范围：v2 修复已实施，Roadmap 状态按 2026-06-12 commit 状态更新

## 1. Status（按 2026-06-12 commit 状态）

- **completed** (V1 路径内) — safe metadata projector 仍存在；private inline-equivalence 测试替换为 projector-contract 测试。
- **completed** (V2) — `RuntimeActionTargetCatalog` 已从 `evidence.py` 提取到 `agent/runtime_integration/target_catalog.py`；65 bindings、helper builders、descriptor 同步迁移；`evidence.py` 保留 back-compat re-export。生产行为未变；新增 `tests/runtime_integration/test_target_catalog_extraction.py` 锁边界。
- **completed** (V3 / V4 子集) — `runtime_decision_frame.py` 中 `subagent.delegate` 的 L1 是生产基线 claim 已修正为 V0 active / L1 legacy frozen。新增 `tests/runtime_integration/test_subagent_runtime_truth.py` 锁 runtime truth。
- **protected_pending** (V1) — safe metadata 真正全量迁移尚未开始（当前只完成第一边界 `...ckpoint_safe_summary_adapter` 与 projector-contract 测试）。后续 migration 必须 one-trust-boundary per commit。
- **documented_pending** (V4) — SubAgent L0/L1/L2 路径文档口径与代码一致；capability 文档 V4 表需后续 align。
- **newly_discovered** — `target_catalog._memory_consolidation_adapter` 仍引用 frozen `memory_consolidation_pipeline`（FROZEN 2026-05-25 兼容层）。已加 compatibility docstring 标记与 `tests/runtime_integration/test_memory_consolidation_truth.py` 锁状态。
- **deferred** — V5/V6/V7 未启动；按 V1/V2/V3 优先继续。

## 2. Git Baseline

- branch: `main`
- HEAD: `a3862a5`
- ahead origin/main: 30
- staged: empty
- dirty tracked: `AGENTS.md` only
- untracked:
  - `.claude/settings.json` 是本地工具设置，不纳入本 Roadmap commit；是否后续入库需用户单独决定。
  - `docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`（本 draft，本身仍是 untracked）
- 本轮：no git add / no commit / no push

> 任何下一步开始前，重新跑一次 `git status` 确认未漂移。

## 3. Audit Inputs

| 审计 | 来源 | 采纳结论 |
|---|---|---|
| 审计一（Roadmap 二审） | conversation audit output | 主方向可用；优先级、行号、路径、范围有偏差，需修正 |
| 审计二（严格 review comments） | conversation audit output | baseline、source-of-truth、redaction inventory、legacy skill tombstone、SubAgentV0Handler 范围、测试规模等口径需校正 |
| 审计三（架构审计摘要） | conversation audit output | cleanup 已完成；缺统一 roadmap；识别 safe metadata、evidence.py、SubAgent 多路径、memory 口径、TUI/local_demo |

> 合并原则：三份共同支持 → verified；两份支持且证据充分 → verified（修正路径/范围/优先级）；单份支持且证据不足 → suspected / needs spike。

## 4. Source-of-truth Assessment

总体可用，但存在局部漂移，需后续对齐。已知 drift：

- `RuntimeDecisionFrame` / `PROJECT_STATUS` / `CURRENT_CAPABILITY_STATUS` / `runtime-decision-spine` 对 capability status、Sub-agent v0/L1/L2 口径不完全一致。
- `docs/design/runtime-decision-spine.md` 可能保留旧 READY / L0 口径，需人工比对。
- `agent/skills/__init__.py` 是 active fail-closed tombstone；其历史隔离目标 `agent/legacy_skills/` 当前**不存在**（已实测确认）——相关表述应为 "tombstone with stale historical target"，不能写成 healthy_current 之类的现状描述。
- 本 Roadmap 本身仍是 draft，不是 source-of-truth。

## 5. Verified Architecture Issues

| # | area | issue | priority | next action |
|---|---|---|---|---|
| V1 | safe metadata / redaction | 仓库内存在多处独立 redact/sanitize 实现；当前 projector 已存在 (`agent/runtime_integration/safe_metadata.py::project_safe_metadata_text`)，call site 迁移进行中 | P1 | 第一边界 (`_checkpoint_safe_summary_adapter`) 已迁移；后续调用点 one-trust-boundary per commit |
| V2 | evidence.py / `RuntimeActionTargetCatalog` | extraction 已完成：catalog 在 `target_catalog.py` (1044 行)，`evidence.py` 现 705 行 | P1 | **completed** — 2026-06-12 commit `8be4dcb`；production boundary + extraction 测试已落 |
| V3 | SubAgent 多路径 | SoT claim 与 runtime 不一致：runtime 真正 active 的是 V0，SoT 之前声称 L1 是 production | P2 → P1 | **partial**: SoT 已修正 (`fix(subagent)` commit `4d0d8e5`)；运行时 truth 测试已落 (`test_subagent_runtime_truth.py`) |
| V4 | capability / 文档口径漂移 | `RuntimeDecisionFrame` 与 PROJECT_STATUS / CURRENT_CAPABILITY_STATUS / runtime-decision-spine 之间存在 capability status 漂移风险 | P2（P1-low docs-alignment） | 先列具体差异（diff table），再做 docs/code terminology alignment；不写为 Phase 1 第一刀 |
| V5 | legacy skill tombstone wording | `agent/skills/__init__.py` 是 active fail-closed tombstone；其历史目标 `agent/legacy_skills/` 不存在 | P2 | 修正文档/注释/测试口径对齐为 "tombstone with stale historical target"；不恢复目录 |
| V6 | Memory consolidation / emergence | consolidation 多文件 frozen；emergence env-gated / partially active | P2 | doc-code 口径对齐；不急于重构 |
| V7 | TUI / local_demo | `tui/` + `agent/local_demo.py` + `agent/local_trace.py` + `agent/local_artifacts.py` 未显式标注 compat path | P3（do-not-touch） | 后续标注 compat path；不进入近期重构 |

> 数字与路径已用 `wc -l` / `ls` 实测；任何进一步修改前需重新对账。

## 6. Suspected Issues / Needs Spike

| # | area | issue | 证据状态 | 需要做的 spike |
|---|---|---|---|---|
| S1 | Config 入口 | provider config 存在 `config.py` / `simple_config.py` / `profiles.py`（实测均存在）；另有 `local_config.py` 与 `mcp_config*.py` | 路径已实测；入口数量与"应否收敛"未定 | 列出所有 import boundary，确认是否真有分散调用面 |
| S2 | Tool mediator 厚度 | `tool_runtime_mediator.py` 偏厚（未在本轮实测行数） | 单点观察，无审计二/三独立支持 | 实测行数 + 边界候选盘点 |
| S3 | core.py / loop.py 厚度 | 大文件观察 | 单点观察 | 实测行数；明确 helper 提取边界 |
| S4 | tests 重组 / 规模 | tests 目录规模偏大 | 审计二质疑精确数字 | 实测 `find tests -name '*.py' | xargs wc -l` 后再讨论 |
| S5 | Stale docs references | `docs/design/*` 引用已删除文件 | 单点观察 | `rg "legacy_skills" docs/` 等可复现命令；本轮不修 |

## 7. Do-not-touch（红线）

1. **不 push**；不改 remote。
2. **不读** `.env` / `agent_log.jsonl` / `sessions/` / `workspace/` 真实内容。
3. **不真实调用** LLM / MCP / external server。
4. **不恢复** legacy L1/L2 production route。
5. **不新增第二 runtime**；不绕过 `agent/core.py` / `agent/loop.py` 主线。
6. **不绕过** `ToolRuntimeMediator`；不写第二条 tool execution path。
7. **不让 child** 直接执行 tool / MCP / memory 写入。
8. **不新增** Memory raw write / auto-adoption / 真实 LLM consolidation。
9. **不动 frozen** memory consolidation（`memory_consolidation*.py` 系列的 ⛔FROZEN 标签）。
10. **不先大拆** `agent/core.py` / `agent/loop.py`。
11. **不削弱** `tests/test_architecture_boundaries.py`。
12. **不复活** `agent/legacy_skills/` 或 `agent/skills/` 原型。
13. **不做** broad ruff cleanup（放最后）。
14. **不移出** `RuntimeActionTargetCatalog` 生产路径（信任根）。
15. **不把 TUI / local_demo 当主线迁移**。
16. **不删除** tests / fixtures，除非先有引用证明与 focused tests。

## 8. Recommended Next Repair Candidates

按推荐顺序；每项先做 spike / 文档对齐，再决定是否进入实施。

1. **TargetCatalog production boundary spike**：建 production boundary test / import-boundary test，确认 `RuntimeActionTargetCatalog` 信任根边界；产出最小 extraction 方案（不立即拆）。
2. **Safe metadata reproducible inventory + minimal projector spike**：用可复现命令盘点所有 redact/sanitize 调用点（覆盖 runtime event、evidence persistence、MCP、subagent、memory、local trace），再设计最小 projector 接口；不替换任何调用。
3. **RuntimeDecisionFrame / capability docs diff table**：列出 `RuntimeDecisionFrame` / `PROJECT_STATUS` / `CURRENT_CAPABILITY_STATUS` / `runtime-decision-spine` 四方在 capability status 与 Sub-agent v0/L1/L2 上的具体差异；不直接改代码逻辑。
4. **legacy skill tombstone wording alignment**：把 `docs/design/skill-system-architecture.md` 等引用该旧表述之处改为 "tombstone with stale historical target"；不恢复 `agent/legacy_skills/`。
5. **Sub-agent path status labeling**：在 `subagent_action.py` 顶部与各 handler 入口标注 V0 current / L0 probe / L1-L2 frozen / inline-local compat；不拆 V0Handler。

## 9. Execution Rules

- tests first；先有 failing test 才有改动。
- one boundary per commit；每步独立可测、可回滚、可审计。
- no broad ruff；no package moves；no behavior change unless explicitly approved。
- do not touch TUI / local_demo in this roadmap commit; any future compat-path labeling must be handled in a separate doc-only change.
- no push；任何 push 需用户明确授权。
- 每个小任务结束前跑 `git status` + focused tests + 护栏测试；任一失败即停下报告。

## 10. Final Verdict

- cleanup 阶段已收口，git baseline 干净（除 AGENTS.md 与本 draft）。
- 当前 source-of-truth 大体可用，但存在局部 drift；本 Roadmap 不替代它。
- 架构修复应**先做 design spike + 文档对齐**，不直接进入代码重构。
- 没有 verified issue 应被解释为"必须立即动代码"；全部需要先经 spike 验证。
- Roadmap v2 ready for human review；review 通过后再讨论是否进 `docs/` 落盘与下一步 spike 启动。
