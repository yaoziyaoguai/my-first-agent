# First Agent v1 Engineering Closeout

**创建**: 2026-06-03
**Closeout HEAD**: `9a059b7`
**Project**: my-first-agent — local-first agent runtime
**状态**: engineering baseline, **not product-ready**

---

## 1. Scope

v1 是 First Agent 的 engineering baseline / first-version baseline。它建立了一个经过硬验证的代码和测试基线，明确了哪些能力已经工程完成，哪些作为已知 v2 backlog 等待后续专项工程。

**v1 is NOT:**
- product-ready release
- broadly user-usable claim
- production MCP ready
- model behavior fully solved

**v1 is:**
- code-clean baseline (full pytest 0 failed)
- agent-dogfood-verified baseline (AGENT_DOGFOOD_AUTO complete)
- honest about remaining caveats and debt

---

## 2. Completed Capabilities

### Runtime Core
- **unified runtime / core.chat main path** — `core.chat()` 作为唯一 Runtime 主路径，统一 Tool/Checkpoint/Memory/SubAgent 入口
- **ToolRuntimeMediator path** — MCP 工具复用统一 Tool pipeline (TOOL_GATE → TOOL_INVOKE → TOOL_RESULT)
- **D-01 SubAgent L2 native loop** — `execute_l2()` + delegate/mediation + batch_memory_proposals, `_SpyProvider` contract tests
- **008 ActionPlan / scheduler** — build_action_plan_from_model_output() → core.chat(action_scheduler=scheduler) → evidence chain fully closed; 104/104 scheduler focused tests PASS; scheduler remains opt-in

### Entry Points
- **plain CLI stable primary** — `python main.py` / `first-agent` / `python main.py --plain`
- **Textual TUI candidate** — `python main.py --tui` / `python main.py --textual`; 11/11 contract tests PASS
- **Ink TUI prototype** — `cd tui && npm start`; TuiShell visual shell, 495/495 tests PASS, tsc clean
- `--shell` deprecated compatibility only
- **default entry NOT ACTIVATED** — CLI fallback retained

### Provider / Config
- **provider / config safety** — FakeProvider 默认路径; 真实 provider 通过 `config/config.yaml` opt-in; diagnostics 不再读取真实 config.yaml (82/82 pass); legacy `.env` / provider profiles deprecated
- **D-04 real provider validation** — 7/7 real provider smoke PASS; anthropic_compatible provider path verified

### Evidence & Validation
- **D-09 skill selection evidence** — real provider re-validation: 7 PASS / 1 FAIL / 2 CONCERN; deterministic selector 43/43 PASS; C6/C3/C7 failures are MODEL_BEHAVIOR_CONCERN, not code bugs
- **D-02 local MCP filesystem smoke** — local stdio MCP bridge lifecycle validated; production MCP not yet validated
- **memory/checkpoint** — Filesystem memory backend 14/14 pass; checkpoint save/resume/ownership verified
- **docs source-of-truth** — 79/79 tests PASS
- **AGENT_DOGFOOD_AUTO complete** — 873 tests PASS, 0 AGENT_FIX_AUTO, 7 xfailed (known/expected)
- **AGENT_FIX_AUTO remaining = 0**

---

## 3. Entry Policy

| 入口 | 命令 | 状态 |
|------|------|------|
| **Plain CLI (稳定主入口)** | `python main.py` / `first-agent` / `python main.py --plain` | **active / primary** |
| **Textual TUI (v1 候选)** | `python main.py --tui` / `python main.py --textual` | **candidate** — 非默认 |
| **Deprecated shell** | `python main.py --shell` | **deprecated** — 兼容 plain CLI + stderr 迁移提示 |
| **Ink Visual Shell (实验原型)** | `cd tui && npm start` | **prototype / visual experiment** — 非 v1 验收路径 |
| **Ink WorkbenchLayout** | `npm run start:legacy` / `npm run start:workbench` | **experimental** — `--legacy`/`--workbench` flag only |

**Default entry**: NOT ACTIVATED.
**CLI fallback**: retained — `main_loop()` + simple CLI backend.

---

## 4. Gates and Evidence

### Test Suite (HEAD: `9a059b7`)

| Suite | Result | Command |
|-------|--------|---------|
| full pytest | **4406 passed, 0 failed, 18 skipped, 37 xfailed** | `python -m pytest -q -p no:cacheprovider` |
| memory backend focused | **14/14 PASS** | `python -m pytest tests/test_memory_store_backend.py -q` |
| docs source-of-truth | **79/79 PASS** | `python -m pytest tests/test_docs_source_of_truth.py -q` |
| TUI (Ink) | **495/495 PASS, tsc clean** | `cd tui && npx vitest run && npx tsc --noEmit` |
| secret safety | **config/config.yaml NOT staged; no secret committed** | verified |
| ruff (touched files) | **clean** | `ruff check` |
| ruff (full repo) | **~991 legacy pre-existing** | documented, not blocking |

### Architecture Boundaries

Architecture boundaries are enforced through:
- docs source-of-truth tests (79/79)
- import cycle detection (ongoing via ruff I-rule)
- B1-B8 architecture classification ledger in PROJECT_STATUS.md

No standalone `test_architecture_boundaries.py` file exists; boundaries are validated through the docs source-of-truth test suite and PROJECT_STATUS.md as the authoritative architecture reference.

---

## 5. Accepted Caveats

以下项目在 v1 closeout 时**未完成**，作为已知 caveats 接受，不阻塞 v1 baseline：

### USER_MANUAL_TRIAL (Owner: user)
| ID | Issue |
|----|-------|
| UMT-001 | Chinese IME validation (requires real terminal + IME) |
| UMT-002 | Paste / multiline validation (requires real terminal paste) |
| UMT-003 | Terminal real interaction combo scenarios |

### PRODUCT_DECISION (Owner: user)
| ID | Issue |
|----|-------|
| PD-001 | Textual TUI 是否未来默认 terminal app |
| PD-002 | Plain CLI fallback 保留策略 |
| PD-003 | Ink prototype 冻结/归档决策 |
| PD-004 | `--shell` flag v2 去留 |
| PD-005 | v1 tag wording |

### REAL_ENV_REQUIRED (Owner: user + agent)
| ID | Issue |
|----|-------|
| RER-001 | Production / external MCP server validation |
| RER-002 | Real provider opt-in smoke (需用户配置真实 key) |
| RER-003 | External MCP E2E validation |

### MODEL_BEHAVIOR_DESIGN (Owner: agent)
| ID | Issue |
|----|-------|
| MBD-001 | 002 C6 negative trigger bypass (模型行为，非代码 bug) |
| MBD-002 | 002 C3/C7 over-eager selection (模型行为) |
| MBD-003 | 003 OTHER_GATE vs skill_allowed_tools→rejected |
| MBD-004 | FakeProvider state-machine xfails |

### FUTURE_DEBT (Owner: agent)
| ID | Issue |
|----|-------|
| FD-001 | Memory extractor zero proposals redesign |
| FD-002 | Full repo ruff legacy debt (~991 issues) |
| FD-003 | when_to_use / when_not_to_use semantic matching |
| FD-004 | Runtime action / catalog coverage |

详见 `docs/debt/first-agent-v2-priority-backlog.md`。

---

## 6. Non-Goals (v1 does NOT claim)

- ❌ product-ready
- ❌ broadly user-usable
- ❌ default TUI activation
- ❌ production MCP server integration
- ❌ private data dogfood
- ❌ Ink runtime integration (Ink is visual shell only)
- ❌ real external service activation
- ❌ model behavior hardening completion
- ❌ full repo ruff legacy debt cleared

---

## 7. Security

- **config/config.yaml** — local-only, NOT committed, NOT staged
- **.env** — not committed, not in repo
- **no secrets** in release docs, test output, or commit history
- **provider diagnostics** — redacted; key prefix not exposed in error messages
- **MCP smoke** — local filesystem `/tmp` only; no HOME/repo/config access
- **real provider key** — configured in local `config/config.yaml` only; never printed, committed, or copied

---

## 8. V2 Handoff

v2 工作应从以下文档开始，而非从 v1 过程文档：

| 优先级 | 文档 | 说明 |
|--------|------|------|
| P0 | `README.md` | 项目入口 |
| P0 | `docs/CURRENT_DOCS.md` | 文档导航 + v2 start section |
| P0 | `docs/releases/v1/first-agent-v1-closeout.md` | 本文件 — v1 baseline 声明 |
| P0 | `docs/debt/first-agent-v2-priority-backlog.md` | v2 优先项分类 |
| P1 | `docs/manual-trials/first-agent-user-trial-guide.md` | 手动试用指南 |
| P1 | `docs/dev/ENGINEERING_WORKFLOW.md` | 工程流程 |
| P1 | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | Runtime flow contract |
| P2 | `docs/archive/v1/README.md` | v1 archive index (历史参考) |

**Rule**: v1 archived docs are historical. v2 should not use archived plans/audits as implementation source-of-truth. Start from backlog + current runtime contract.

---

## 9. Recommended Tag

```
v1.0.0-engineering-closeout
```

**Tag message**:
```
First Agent v1 engineering closeout — code-clean baseline with known v2 backlog.

Full pytest: 4406 passed / 0 failed / 37 xfailed
AGENT_FIX_AUTO: 0 remaining
AGENT_DOGFOOD_AUTO: 0 remaining
TUI (Ink): 495/495 PASS, tsc clean

Remaining work (not v1 blockers):
- USER_MANUAL_TRIAL
- PRODUCT_DECISION
- REAL_ENV_REQUIRED
- MODEL_BEHAVIOR_DESIGN
- FUTURE_DEBT

Not product-ready. Not a release. Engineering closeout only.
```

**本轮不创建 tag。tag 创建需用户单独确认。**

---

## 10. References

- `docs/PROJECT_STATUS.md` — 当前状态、REAL-EVIDENCE-001..008、B1-B8 架构分类账
- `docs/PROGRESS_LEDGER.md` — milestones 历史
- `docs/debt/first-agent-open-items.md` — 未结项 (by owner 分类)
- `docs/debt/first-agent-v2-priority-backlog.md` — v2 优先项 backlog
- `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` — FROZEN 阶段交接
- `docs/manual-trials/first-agent-user-trial-guide.md` — 手动试用操作手册
- `docs/audit/b1-b8-current-stage-close-out-audit.md` — B1-B8 close-out 审计
