# Current Architecture Repair Roadmap (v2)

> 状态：draft — 基于三份审计的合并结论，等待人工 review
> 创建日期：2026-06-11
> 本轮范围：只改本文；不改代码、不 git add、不 commit、不 push

## 1. Status

- cleanup 阶段已收口（git log 最近 5 条 commit 均为 cleanup 类）
- 本文档是 cleanup 后第一份统一架构修复路线图
- 依据三份审计合并：审计一（Roadmap 二审）/ 审计二（严格 review comments）/ 审计三（架构审计摘要）
- 来源主要为 conversation audit output；未在 `docs/06-audit/` 落盘独立审计文件
- **requires human review before commit**；本轮不实施任何修复

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
| V1 | safe metadata / redaction | 仓库内存在多处独立 redact/sanitize 实现（runtime event、evidence persistence、MCP sanitizer、subagent/local、memory summary、local trace 等路径）；当前没有统一 projector | P1 | 先做可复现 inventory（精确命令/口径），再设计最小 safe metadata projector；不直接全量迁移 |
| V2 | evidence.py / `RuntimeActionTargetCatalog` | `agent/runtime_integration/evidence.py` 偏厚（实测 1717 行）；`RuntimeActionTargetCatalog` 是 dispatcher production path 的信任根 | P1 | 先建 TargetCatalog production boundary test / import-boundary test，再做最小 extraction spike；不一次性拆分 |
| V3 | SubAgent 多路径 | `agent/runtime_integration/subagent_action.py` 约 1663 行，包含 V0 current path、L0 probe、L1/L2 legacy/frozen path 及相关 helpers（实测 V0Handler 在 :306；L0Handler 在 :1257；L1Handler 在 :1424） | P2（P1-low） | 先标注各路径 status（V0 current / L0 probe / L1-L2 frozen / inline-local compat）；V0Handler 内部 builder 边界拆分必须单独 design spike，不作第一刀 |
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
