# Industry Capability Gap Remediation Plan

- **Date:** 2026-05-26
- **Status:** active
- **Authoritative source:** [Industry Agent Capability Gap Audit](../audit/industry-agent-capability-gap-audit-2026-05-25.md)

## 执行原则

1. 以审计文档 Section J/K/L 为唯一授权源
2. 优先 safe-to-auto-run、无需 human dogfood、无需真实 API 的 loops
3. 每个 loop：SPEC/Plan → Implementation → TDD → Gates → Commit → Push → Continue
4. 不做 broad capability expansion、不通第二条 runtime flow
5. blocked/deferred 不停止 workflow，继续下一个 safe loop

## Top 5 Capability Gaps (from audit §D)

| # | Gap | Safe-to-auto-run | Needs real API | Needs human dogfood |
|---|---|---|---|---|
| 1 | Packaging / install / startup readiness | yes | no | yes (验证) |
| 2 | Provider auth/config diagnostics | yes | no | yes (验证) |
| 3 | Provider tool-call normalization contract | yes | no | later yes |
| 4 | Memory recall UX | yes (skeleton) | no | yes |
| 5 | Tool approval / run summary UX | yes | no | yes |

## Big Loop Execution Order

按审计 §K.1 建议顺序：先降低 human dogfood 启动失败率，再提高证据/合同可信度，再做 polish。

| Order | Loop | Category | Safe-to-auto-run | Complexity |
|---|---|---|---|---|
| 1 | Packaging / Install / Startup Readiness | packaging | yes | medium |
| 2 | Provider Auth/Config Diagnostics | UX | yes | low |
| 3 | Provider Tool-Call Normalization Contract | architecture | yes | medium |
| 4 | Dogfood Harness De-Stateful Consolidation | eval/dogfood | yes | medium |
| 5 | Trace / Run Summary Debug Report Polish | UX | yes | low-medium |

---

## Loop 1: Packaging / Install / Startup Readiness

- **Category:** packaging
- **Why now:** 用户能否启动是所有 dogfood 前置条件。当前只有 `requirements.txt` + 手工 `pip install`，无 `pyproject.toml`，无 console_scripts entry point，无 startup readiness check
- **User outcome:** 新用户按 README 能稳定安装、启动、确认当前模式（fake/local），并在出错时获得 actionable next step
- **Scope:**
  - `pyproject.toml` with `[project.scripts]` console entry point `first-agent` → `main:main`
  - `scripts/check_startup_readiness.py` — temp HOME / no .env / fake startup smoke
  - README startup flow audit + update
  - CLI help/onboarding clarity about provider mode
- **Out of scope:**
  - PyPI/Homebrew release
  - Real release tag
  - Real API call
  - .env reading
  - Architecture changes
- **Implementation risk:** low — all changes are static/additive
- **Architecture risk:** low — no runtime behavior change
- **Safe-to-auto-run:** yes
- **Requires real API:** no
- **Requires human dogfood:** no (implementation), yes (verification that users understand)
- **Docs/spec/tests to create/update:**
  - `pyproject.toml` (create)
  - `scripts/check_startup_readiness.py` (create)
  - `tests/test_startup_readiness.py` (create)
  - `README.md` (update install section)
- **Gates:** ruff, test_startup_readiness.py, focused docs tests
- **Stop conditions:** 需要外部发布凭据时停止
- **Commit message:** `feat(startup): add packaging and startup readiness checks`

## Loop 2: Provider Auth/Config Diagnostics

- **Category:** UX
- **Why now:** Active docs 记录 real provider 401 config/auth concern。下一步不是盲测 API，而是静态诊断配置状态和失败原因，降低人工试用成本
- **User outcome:** `python main.py status` / `first-agent status` 输出脱敏的 provider 配置状态，含 actionable remediation hints
- **Scope:**
  - Static config diagnostics: provider type, model, base_url, key presence (yes/no only), all redacted
  - Known error mapping: 401/403/timeout/provider_unavailable → user-facing message
  - `main.py status` subcommand or extend health
  - `scripts/check_provider_config.py`
  - Tests: missing key, present key redacted, invalid provider name, missing model, 401 maps to actionable message
- **Out of scope:**
  - Reading .env content
  - Calling real API
  - Printing secrets
  - Verifying key validity
  - Provider-specific hacks
  - Making real provider default
- **Implementation risk:** low — static checks only
- **Architecture risk:** low — no provider adapter changes
- **Safe-to-auto-run:** yes
- **Requires real API:** no
- **Requires human dogfood:** no (implementation), yes (verification)
- **Docs/spec/tests to create/update:**
  - `scripts/check_provider_config.py` (create)
  - `agent/provider/diagnostics.py` (create — diagnostic mapping)
  - `tests/test_provider_diagnostics.py` (create)
  - `docs/design/provider-diagnostics-spec.md` (maybe, or inline docstrings)
- **Gates:** ruff, test_provider_diagnostics.py, redaction tests
- **Stop conditions:** 需要真实 key 判断 reachability 时停止
- **Commit message:** `feat(provider): add provider auth config diagnostics`

## Loop 3: Provider Tool-Call Normalization Contract

- **Category:** architecture
- **Why now:** Tool-use 是行业 Agent 核心，当前 adapter 有骨架但缺 golden fixture matrix、streaming tool_use contract、invalid input handling
- **User outcome:** 跨 provider tool-call 行为差异降低，provider-specific bug 不易漏到 runtime
- **Scope:**
  - AD: `docs/design/provider-tool-call-normalization-contract.md`
  - Define internal normalized shape: tool name, arguments, call_id, provider source, streaming/non-streaming, invalid handling
  - Contract tests using fake/stub: Anthropic tool_use, OpenAI tool_calls, missing args, malformed JSON, namespaced names, streaming partial
  - If normalization code exists, supplement tests; if missing and small, add minimal implementation
- **Out of scope:**
  - New providers
  - Real API calls
  - Prompt tuning
  - Tool Pipeline semantics changes
  - Text→tool_call hard-parsing
- **Implementation risk:** medium — touching provider normalization code
- **Architecture risk:** medium — could grow scope if adapter code needs refactoring
- **Safe-to-auto-run:** yes
- **Requires real API:** no
- **Requires human dogfood:** later yes (to verify real model behavior)
- **Docs/spec/tests to create/update:**
  - `docs/design/provider-tool-call-normalization-contract.md` (create)
  - `tests/test_provider_tool_call_normalization_contract.py` (create)
  - May touch `agent/provider/` normalization code
- **Gates:** ruff, contract tests, existing provider tests
- **Stop conditions:** 需要真实 provider behavior 判定时降级为 AD+tests only
- **Commit message:** `test(provider): define tool-call normalization contract`

## Loop 4: Dogfood Harness De-Stateful Consolidation

- **Category:** eval/dogfood
- **Why now:** 当前 dogfood scripts bespoke/stateful — 会写 `workspace/demo` 和 `docs/dogfood` report，重跑可能有残留影响
- **User outcome:** 可复现、tmp-root-first、不自动覆盖 active report 的 dogfood harness
- **Scope:**
  - Audit current `scripts/dogfood*` statefulness
  - `docs/design/dogfood-harness-contract.md` — report schema, step result dataclass
  - Lightweight shared helpers: `StepResult` dataclass, report writer, redaction helper, temp workspace helper
  - Migrate 1 low-risk script to prove pattern
  - Tests for shared helpers
- **Out of scope:**
  - Executing dogfood
  - Real API calls
  - Reading real sessions/runs/memory
  - Full rewrite of all scripts
  - Complex runner
- **Implementation risk:** medium — changing script behavior
- **Architecture risk:** medium — touching dogfood evidence infrastructure
- **Safe-to-auto-run:** yes
- **Requires real API:** no
- **Requires human dogfood:** no
- **Docs/spec/tests to create/update:**
  - `docs/design/dogfood-harness-contract.md` (create)
  - `agent/dogfood_harness.py` (create — shared helpers)
  - `tests/test_dogfood_harness.py` (create)
  - Touch 1 `scripts/dogfood*` file
- **Gates:** ruff, dogfood harness tests, existing dogfood boundary tests
- **Stop conditions:** 迁移风险高时停止在 contract + helper tests
- **Commit message:** `refactor(dogfood): define de-stateful harness contract and helpers`

## Loop 5: Trace / Run Summary Debug Report Polish

- **Category:** UX
- **Why now:** Human dogfood 前需要可读 debug evidence。当前 `run.summary` 偏工程计数，需更 user-actionable
- **User outcome:** 每 turn 后的 run summary 更可读：provider mode, model, tool calls, memory actions, errors, next suggested action
- **Scope:**
  - Audit current run summary / debug report fields
  - Design user-facing compact report schema
  - Add/improve CLI output if existing debug/report path exists
  - Tests: no secret leakage, missing info = "unavailable" not fake, tool/memory/subagent sections appear when relevant, concise for ordinary chat
- **Out of scope:**
  - New observability backend
  - UI / dashboard
  - Reading real traces
  - RuntimeAction semantics changes
- **Implementation risk:** low-medium
- **Architecture risk:** low — display layer only
- **Safe-to-auto-run:** yes
- **Requires real API:** no
- **Requires human dogfood:** yes (to verify usefulness)
- **Docs/spec/tests to create/update:**
  - May update `agent/cli_renderer.py` / `agent/display_events.py`
  - `tests/test_run_summary_polish.py` (create)
- **Gates:** ruff, run summary tests, redaction tests
- **Stop conditions:** 需要 visual/product design 选择时停止
- **Commit message:** `fix(trace): polish compact run summary output`

---

## Deferred / Will Not Start

Per audit §H:
- FakeProvider intelligence — frozen
- Memory consolidation — frozen
- SubAgent L1 — gated
- Full Hook lifecycle — deferred
- MCP confirmation pipeline — deferred
- Sandbox-grade execution — deferred
- RAG/embedding/plugin marketplace — deferred
- Broad core/loop rewrite — deferred

## Final Recommendation (from audit §L)

1. 先跑 Loop 1+2 — 不依赖 real API/human dogfood，直接提升人工试用成功率
2. 再跑 Loop 3 — 架构合同，预防 provider 差异 bug
3. 然后 Loop 4+5 — 证据可信度和 debug 可读性
4. 所有 loops 完成后仍需要 manual human dogfood
5. AutoRun 可继续但限于 cleanup/readiness/contract/testing polish
