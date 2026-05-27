# Post Red-Team Cleanup Remediation Plan

- **Date:** 2026-05-25
- **Source:** `docs/audit/global-red-team-product-architecture-audit-2026-05-25.md` (strict re-audit of first remediation)
- **Status:** active
- **Principle:** cleanup-only — 不新增 capability，只修 P1/P2/P3 cleanup 问题

## Context

第一轮 remediation（RT-01 到 RT-18）完成了 6 个 phase，但 strict re-audit 发现多项仅为 PARTIAL 解决：

- RT-01 dispatcher/evidence parity: RESOLVED
- RT-12 FakeProvider filesystem side effect: RESOLVED
- RT-02 command shortcut runtime boundary: PARTIAL — typed boundary 已加但缺 freeze/allowlist
- RT-06 secret fragment redaction: PARTIAL — lint 仅覆盖 docs/dogfood
- RT-05 docs source-of-truth: PARTIAL — 索引已更新但状态描述仍有冲突
- RT-07 SubAgent fixture leakage: PARTIAL — core.py 已修但 phase1_hook.py:117 仍未修
- RT-16 handler vs E2E evidence labeling: PARTIAL — tests/README.md 已重写但测试文件中的 E2E overclaim 未全面清理

本轮目标：修完所有 PARTIAL 项 + 新增 P1 (PF-01, PF-02)，准备 manual human dogfood。

## Findings Breakdown

### PF-01 — Startup / Provider Mode Contract (P1)

| Field | Value |
|---|---|
| **Severity** | P1 |
| **Current evidence** | `main.py:429` 调用 `load_legacy_dotenv_config()` 在 provider 初始化之前；`config.py` (legacy) 与 `agent/provider/config.py` (authority) 并存；用户启动时无显式 provider mode banner |
| **User impact** | 用户不清楚当前是 fake/local 还是 real provider；manual dogfood 第一 blocker |
| **Architecture impact** | provider/model 初始化顺序依赖 import-time 副作用，不确定性强 |
| **Remediation action** | 1. 确认 main.py → core.py → provider factory 启动顺序；2. 新增显式 startup provider mode banner；3. 补 contract tests 锁定 fake/default/real explicit mode 行为 |
| **Scope** | main.py startup banner, provider mode preflight, contract tests |
| **Out of scope** | 大启动框架重构；real provider 设为默认；读取 .env |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 需要真实 .env 才能确认 behavior |
| **Tests/gates** | fake/default startup 不读真实 API；startup banner 输出当前 mode；import order 不导致 config stale |
| **Commit suggestion** | `fix(startup): clarify provider mode contract before dogfood` |

### PF-02 — Command Shortcut Freeze + Boundary Hardening (P1)

| Field | Value |
|---|---|
| **Severity** | P1 |
| **Current evidence** | `agent/cli_commands.py` 已有 `CommandCategory`/`CommandIntent` typed boundary；`agent/core.py` 已有 CLI-ONLY/DEMO-ONLY 标签；但无 freeze/allowlist 机制防止新增 shortcut |
| **User impact** | command shortcuts 可能继续膨胀为第二 capability runtime |
| **Architecture impact** | 新 shortcut 可能绕开 Tool Pipeline / Memory runtime / SubAgent delegation |
| **Remediation action** | 1. 列出现有 shortcuts；2. 新增 command router allowlist 或文档级硬边界；3. 补 characterization tests；4. 标注 transitional boundary + TODO/sunset |
| **Scope** | freeze/allowlist 机制，characterization tests，sunset 注释 |
| **Out of scope** | 大迁移 command shortcuts 到 dispatcher；新增命令 |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 改变现有 shortcut 行为 |
| **Tests/gates** | allowlist prevents accidental new shortcuts；existing behavior unchanged；no direct handler/dispatcher bypass |
| **Commit suggestion** | `docs(core): freeze command shortcuts as transitional affordances` |

### PF-03 — Secret Redaction Lint Expansion (P2)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Current evidence** | RT-06 第一轮仅修了 `docs/dogfood/real-provider-dogfood-report.md` 一处；`test_dogfood_reports_contain_no_secret_fragments` 仅扫描 `docs/dogfood/` |
| **User impact** | 其他 docs 目录中可能存在 partial secret fragments |
| **Architecture impact** | secret 泄漏风险未全面覆盖 |
| **Remediation action** | 1. 搜索 docs/plans、docs/audit、docs/dogfood、docs/README、reports/json 中 secret-like fragments；2. 替换为 CONFIGURED/REDACTED/PRESENT/SET；3. 扩展 lint 覆盖范围 |
| **Scope** | docs/dogfood, docs/plans, docs/audit, docs/README*, reports/json |
| **Out of scope** | .env 读取；真实 API 调用 |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 发现需要真实 .env 才能确认的 secret |
| **Tests/gates** | lint catches partial secrets in docs/plans and docs/audit；allows CONFIGURED/REDACTED/PRESENT/SET；no false-positive on commit hashes |
| **Commit suggestion** | `test(security): expand redaction lint beyond dogfood docs` |

### PF-04 — Source-of-Truth Cleanup (P2)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Current evidence** | RT-05 第一轮更新了 `docs/audit/README.md` 和 `docs/plans/README.md`；`docs/README.zh.md` 增加了导航；但 README 状态描述可能仍指向旧 remediation |
| **User impact** | 新用户读到 stale next steps |
| **Architecture impact** | source-of-truth 冲突导致 agent 和 human 走错误路径 |
| **Remediation action** | 1. 确认 README 不继续说"下一步是 remediation"如果已完成；2. docs/plans/README 不把已完成 plan 写成当前执行计划；3. docs/dogfood/README 说明 manual human dogfood 是当前最高价值下一步；4. 推荐阅读路径：README → docs/README.zh.md → dogfood checklist → current audit |
| **Scope** | README, docs/README.zh.md, docs/plans/README.md, docs/dogfood/README.md, docs/audit/README.md |
| **Out of scope** | 大量移动历史文件；runtime 改动 |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 不确定的历史声明冲突 |
| **Tests/gates** | git diff --check |
| **Commit suggestion** | `docs: align source of truth after red-team remediation` |

### PF-05 — SubAgent Fixture Boundary Cleanup (P2)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Current evidence** | `agent/runtime_integration/phase1_hook.py:117` 仍引用 `Path("tests/fixtures/subagents")` — 第一轮 RT-07 只修了 core.py 的两处，遗漏了 phase1_hook.py |
| **User impact** | runtime product path 依赖 test fixtures |
| **Architecture impact** | test fixtures 泄漏到 product registration |
| **Remediation action** | 1. 将 `phase1_hook.py:117` 的 `Path("tests/fixtures/subagents")` 改为 `Path("agent/subagent_system/descriptors")`；2. 确认 tests/fixtures/subagents 不再被任何 product path 读取；3. 更新相关 tests |
| **Scope** | phase1_hook.py:117, 相关 tests |
| **Out of scope** | 新增 SubAgent 能力；SubAgent L1；multi-agent orchestration |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 改变 SubAgent L0 delegate behavior |
| **Tests/gates** | runtime integration does not read tests/fixtures/subagents；demo descriptors are demo-only；no behavior regression |
| **Commit suggestion** | `fix(subagent): remove runtime dependency on test fixtures` |

### PF-06 — Direct-call E2E Label Cleanup (P2)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Current evidence** | RT-16 第一轮重写了 `tests/README.md` taxonomy；但测试文件中的类名/函数名/docstring 可能仍有 E2E overclaim |
| **User impact** | 证据膨胀风险 |
| **Architecture impact** | direct handler tests 被误标为 E2E |
| **Remediation action** | 1. 搜索 test 文件中 E2E/e2e 字样；2. direct handler/service/dispatcher tests 重命名为 integration/handler/service/characterization；3. 保留真正 core.chat/main.py/CLI user path E2E 名称；4. 特别检查 TestDelegateOnceE2E |
| **Scope** | test file/class/function/docstring 命名 |
| **Out of scope** | 降低测试覆盖 |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 改变测试语义 |
| **Tests/gates** | focused tests for renamed tests |
| **Commit suggestion** | `test(evidence): rename direct-call E2E labels` |

### PF-07 — Approval Not Sandbox-Grade (P2, deferred)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Status** | **deferred** — 需要 product decision on security posture |
| **Note** | 当前 confirmation-based approval 对 shell/network tools 不够；但 sandbox 实现需要 OS-level 隔离，超出 cleanup scope |

### PF-08 — Dogfood Scripts Bespoke/Stateful (P2, deferred)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Status** | **deferred** — 需要更大 script consolidation effort |
| **Note** | Phase 10 会准备 manual dogfood record template，但不重构现有 dogfood scripts |

### PF-09 — Core/Loop/Evidence Files Too Large (P2, deferred)

| Field | Value |
|---|---|
| **Severity** | P2 |
| **Status** | **deferred** — 需要专门的 code boundary slimming loop |
| **Note** | core.py 1100+ 行，loop.py 800+ 行；slimming 需要 characterization tests first，不能在 cleanup loop 中仓促做 |

### PF-13 — Legacy Aliases Lack Sunset (P3)

| Field | Value |
|---|---|
| **Severity** | P3 |
| **Current evidence** | `agent/core.py:51-55` 已有 DEPRECATED 标记的 `_looks_like_*` re-exports；`agent/memory.py` 仍有 legacy import；`config.py` 仍是 legacy compatibility module |
| **User impact** | 向后兼容别名隐藏架构漂移 |
| **Architecture impact** | 长期兼容路径阻碍清理 |
| **Remediation action** | 1. 搜索 legacy_adapter、_looks_like_*、legacy config paths；2. 添加 why kept / sunset condition / removal criteria 注释；3. 不删除代码 |
| **Scope** | 注释和文档 |
| **Out of scope** | 删除代码；改变行为 |
| **Safe-to-auto-run** | yes |
| **Stop condition** | 无 |
| **Tests/gates** | git diff --check |
| **Commit suggestion** | `docs(legacy): add sunset labels for compatibility paths` |

### PF-15 — Full Gate Re-run (P3)

| Field | Value |
|---|---|
| **Severity** | P3 |
| **Current evidence** | 上一轮 strict audit 未重新运行 full gate |
| **User impact** | 不知道当前所有改动后 full gate 是否仍 green |
| **Architecture impact** | 未检测到的 regression |
| **Remediation action** | 运行 git diff --check + ruff check + full pytest |
| **Scope** | 全量 gate |
| **Out of scope** | 新增 tests |
| **Safe-to-auto-run** | yes |
| **Stop condition** | pre-existing HOME sandbox failure 需要真实 API/private data 才能修 |
| **Tests/gates** | 本身就是 gate |
| **Commit suggestion** | `test(gate): full gate re-run after cleanup phases` |

## Execution Order

```
Phase 1: Write this plan → commit/push                              [当前]
Phase 2: PF-01 Startup/Provider Mode Contract                       [P1]
Phase 3: PF-02 Command Shortcut Freeze + Boundary Hardening         [P1]
Phase 4: PF-03 Secret Redaction Lint Expansion                      [P2]
Phase 5: PF-04 Source-of-Truth Cleanup                              [P2]
Phase 6: PF-05 SubAgent Fixture Boundary Cleanup                    [P2]
Phase 7: PF-06 Direct-call E2E Label Cleanup                        [P2]
Phase 8: PF-13 Legacy Sunset Labels                                 [P3]
Phase 9: PF-15 Full Gate Re-run                                     [P3]
Phase 10: Manual Human Dogfood Record Template                      [P3]
```

## Files Expected to Change

| Phase | Files |
|-------|-------|
| PF-01 | `main.py`, `agent/provider/config.py`, `tests/test_provider_contract.py` |
| PF-02 | `agent/cli_commands.py`, `agent/core.py`, `tests/test_command_boundary_characterization.py` |
| PF-03 | `tests/test_local_trial_readiness.py` (+ 搜索 docs/plans, docs/audit 中的 secret fragments) |
| PF-04 | `README.md`, `docs/README.zh.md`, `docs/plans/README.md`, `docs/dogfood/README.md`, `docs/audit/README.md` |
| PF-05 | `agent/runtime_integration/phase1_hook.py`, `tests/` |
| PF-06 | `tests/test_subagent_user_facing.py`, 其他含 E2E overclaim 的 test 文件 |
| PF-13 | `agent/core.py`, `config.py`, `agent/memory.py` |
| PF-15 | 无代码改动，仅运行 gate |
| PF-10 | `docs/dogfood/manual-human-dogfood-record-template.md` (新建) |

## Gates Per Phase

Minimum per phase:
- `git diff --check`
- `.venv/bin/ruff check agent tests scripts`
- Relevant focused tests

Phase 9 full gate:
- `HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q`

## Stop Conditions (全局)

只有以下情况才停：
- HARD_STOP_GIT_UNSAFE_STATE
- HARD_STOP_SECRET_UNSAFE
- HARD_STOP_REAL_API_UNSAFE
- HARD_STOP_PRIVATE_DATA
- HARD_STOP_SECOND_RUNTIME_FLOW
- HARD_STOP_FAKE_REAL_SPLIT
- HARD_STOP_ANCHOR_REGRESSION
- HARD_STOP_P0
- HARD_STOP_P1_RETRY_EXCEEDED
- HARD_STOP_PRODUCT_DECISION_REQUIRED
- HARD_STOP_CONTEXT_LOW_HANDOFF_WRITTEN

不会因为以下情况停：
- plan written
- one phase completed
- docs updated
- focused tests passed
- need commit/push
- one P2 fixed
- full gate initially fails with fixable stale assertion
