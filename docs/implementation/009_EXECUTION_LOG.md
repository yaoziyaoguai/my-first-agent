# 009 Execution Log

本文件是 009 的可恢复证据索引，不是完成声明。
只有命令 exit code 已知、输出未截断且行为 oracle 覆盖目标 finding 时，才能把 unit 标为 `verified`。
executor（本会话）只记录 provisional per-unit verdict 与 gate receipt；`locally-verified` 晋级与
`--control-seal` 由非本 agent/session 的 reviewer 完成。

## Baseline

- Plan: `docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md`
- Audit (reopen): `docs/audits/2026-07-21-009-u8a-executor-report-audit.md`（A1-A5）
- Shared proof contract: `docs/architecture/CAPABILITY_EVIDENCE_CLOSURE_CONTRACT.md`
- Starting claim: Kernel foundation retained; six capabilities are implementation candidates with independent closure blockers; none accepted.
- Historical automated result: 286 tests passed in the audited dirty worktree; this is not 009 Green evidence.
- External calls authorized: no（测试只用 fake/fixture/temp state + 强制禁网边界）。
- Private data access authorized: no.
- Commit/push authorized: no.
- 008 artifacts mutable: no（只读历史）。
- 009 delivery manifest: frozen by U1/U8A；936 entries，无 generate mode。

## Allowed states

`not started`、`Red confirmed`、`Green focused`、`verified`、`blocked`。

`verified` requires all named unit tests, focused boundary suite and execution-log evidence；它是 executor-owned unit state，不是 capability promotion。
`blocked` requires a concrete unresolved condition, not merely unfinished work。

## Unit ledger

| Unit | State | Red evidence | Green evidence | Boundary verification | Notes |
|---|---|---|---|---|---|
| U1 evidence/delivery | verified | A1/A4: verifier best-effort deny-network、admission TOCTOU（open/close fd 再按 path 重开 hash）、`--content` 用 PYTHONPATH 指向复制树且 `--ignore` 两个 delivery 测试、`--control-seal` 对未封存 controls 返回 0 | verifier 重写：schema 绑定 baseline/operation/owner/Git-mode、单一 no-follow descriptor 同时做 metadata+digest、tracked delta+explicit untracked+ops 三方对账、`GIT_INDEX_FILE` 临时索引、`--content` non-editable 安装+origin 断言+sandbox deny-network+不忽略 delivery 测试、`--control-seal` 拒绝 missing/null/unsealed/drifted；8 个 v2 nodeid oracle + 4 保留回归 | `--check-membership` exit 0（936 entries）；A15/A16/A17/A19 Green；manifest git_mode 冻结；`.claude-runtime/` 等按路径拒绝 | 008 artifacts 未触碰；denied 路径永不 read/hash |
| U2 MCP | provisional | F3: oversized canonical args 截断后执行 | 保留 008 fix（canonical args 不截断 + binding overflow → known-not-executed）；本轮不扩写 matrix | mcp suite 43 passed | deeper receipt/transport/latch matrix 是后续 closure，本轮保持 implemented-candidate |
| U3 Memory | provisional | F4: stale content_digest/unknown field 接受 | 保留 008 strict decode fix | memory suite 21 passed | strict durability / governed recall closure 后续；保持 implemented-candidate |
| U4 SubAgent | provisional | F5: no receipt contract；unconfirmed 展平为 string | 保留 008 structural receipt contract + UNCONFIRMED→recovery | subagent suite 14 passed | 保持 implemented-candidate + safe-unavailable + E3-blocked（无 supported provider E2） |
| U5 Scheduler | provisional | F8: impossible UTC 接受 | 保留 008 calendar-valid UTC | scheduler suite 13 passed | busy/conflict reconciliation fault matrix 后续；保持 implemented-candidate |
| U6 Skill | provisional | F7: same-content inode replacement 接受 | 保留 008 identity+digest revalidation | skill suite 34 passed | identity/metadata closure 后续；保持 implemented-candidate |
| U7 TUI/lifecycle | verified | A2: 仅 submit→approve Pilot；renderer 作 runtime sink；TUI 分支在 finally close-stack 前 return | render.project EXECUTING→"interrupted unknown effect" resume-only；approval/recovery form_fields；projection-driven action gating（Cancel on EXECUTING 不 dispatch）；同一 QueueingEventSink 注入 Runtime+TuiAdapter；stdlib ExitStack 统一 close-stack（正常/optional-dep/startup 失败逆序各一次）；active-worker close→closing_requested、deadline→shutdown_blocked；non-blocking worker（call_from_thread 刷新） | tui suite 25 passed；cli/scheduler lifecycle 测试 Green；Enter 不默认批准 | RecoveryRequest 只展示 request/tool/binding/summary；未扩 checkpoint schema |
| U8A materialize/provisional verdicts | verified | A1: `--content` best-effort deny-network、忽略 delivery 测试、无 non-editable install | `--content` exit 0：临时索引 materialize（真实 index 未触碰）→ non-editable no-deps install → neutral-cwd origin（install prefix，排除 dirty tree）→ sandbox-exec loopback 负向探针 DENIED → ruff → pytest 322（不 `--ignore`）；deny-network 不可用/未阻断 fail closed | `--content` exit 0；receipt 见下；`--control-seal` exit 1（controls 未封存，executor 不封存） | executor 不编辑 reviewer controls、不写 sealed |
| U8B independent review/seal | sealed | n/a | n/a | reviewer 独立重跑 `--content` exit 0（322 passed，deny-network DENIED，未截断）；exact manifest admission、F1-F9 oracle test body、residual limitation 已核；不晋级任何 capability，无 E3 | distinct reviewer/session 已完成（见 `009_INDEPENDENT_REVIEW.md`） |

## Finding trace

| Finding | Owner | Required observable Red | State | Evidence |
|---|---|---|---|---|
| F1 manifest auto-admission | U1 | denied runtime-state path admitted/read | verified | verifier 无 generate mode；v2 oracle `test_denied_and_unknown_paths_fail_before_content_read_or_hash` 证明 deny 先于 read/hash；`--check-membership` exit 0 |
| F2 final modes unimplemented | U1/U8 | content/control mode best-effort 或 imports dirty tree | verified | `--content` exit 0（materialize+install+origin+deny-network+ruff+pytest 322，不忽略 delivery 测试）；`--control-seal` exit 1（拒绝未封存） |
| F3 MCP prepared effect mismatch | U2 | preview/env/identity differs or error flattens | provisional | `_canonical_arguments` 不截断 + binding overflow → known-not-executed；mcp 43 passed（matrix 未完整闭合） |
| F4 Memory false strictness | U3 | stale digest/unknown/coerced load | provisional | strict decode；memory 21 passed |
| F5 SubAgent false closure | U4 | unsupported/unconfirmed → success | provisional | structural receipt contract；subagent 14 passed；保持 safe-unavailable |
| F6 TUI submit-only/lifecycle | U7 | pending/recovery 不可键盘完成或 close 绕过 stack | verified | submit/approve/reject/recovery/resume/cancel 全键盘；reopen 零调用；shared queue sink；reverse-close exactly once；closing_requested/shutdown_blocked；tui 25 passed |
| F7 Skill identity drift | U6 | same-content replacement readable | provisional | identity+digest revalidation；skill 34 passed |
| F8 Scheduler UTC/busy gap | U5 | impossible UTC accepted | provisional | calendar-valid UTC；scheduler 13 passed |
| F9 unverifiable log claims | U1-U8 | unit lacks same-oracle Red/Green/boundary | verified（U1/U7/U8A）/provisional（U2-U6） | 本 log 逐项记录可核对 command/exit/observable；统计一致（322） |

## Per-unit evidence record

### U1 evidence/delivery

- **Finding/requirements:** R1-R5、R21-R24；A1/A3-A5。
- **Named behavior test:** `tests/architecture/test_delivery_manifest_v2.py` 8 个 nodeid。
- **Observable oracle:** schema/baseline/operation/owner/Git-mode 绑定、单一 descriptor metadata+digest、tracked delta+untracked+ops 对账、denied 先于 read/hash、临时索引不触碰真实 index、non-editable install+dirty-tree origin、deny-network+完整 suites、control-seal 拒绝未封存。
- **Red command:** `.venv/bin/python -m pytest tests/architecture/test_delivery_manifest_v2.py`（旧 verifier：无 git_mode、TOCTOU admission、忽略 delivery 测试、best-effort 探针、control-seal 恒 0 → 行为缺失）。
- **Red summary:** 行为在旧 verifier 不存在/被绕过。
- **Green change:** 重写 `scripts/verify_materialized_tree.py`；冻结 manifest git_mode。
- **Green command:** `.venv/bin/python -m pytest tests/architecture/test_delivery_manifest_v2.py -q`。
- **Green exit:** 0；`12 passed`。
- **Boundary command:** `.venv/bin/python scripts/verify_materialized_tree.py --check-membership`。
- **Boundary exit:** 0；`membership ok: 936 entries`。
- **Files owned:** `scripts/verify_materialized_tree.py`、`tests/architecture/test_delivery_manifest.py`、`tests/architecture/test_delivery_manifest_v2.py`、`docs/implementation/009_DELIVERY_MANIFEST.json`。
- **Deviation/residual risk:** denied 前缀路径（`.claude-runtime/` 等）按路径拒绝、不进 manifest；materialize 后剥离 baseline 残留的 denied 前缀文件。

### U7 TUI/lifecycle

- **Finding/requirements:** R19-R20；A2。
- **Named behavior test:** `tests/tui/test_render.py::test_projection_reopened_executing_is_unknown_effect_resume_only`、`test_app.py::test_pilot_reopens_durable_approval_without_calls_and_focuses_form`、`…recovery…`、`…reopened_executing_dispatches_resume_only`、`test_cli/test_entrypoint.py::test_tui_composition_and_adapter_share_one_queue_sink_without_terminal_events`、`…normal_exit_reverse_closes_resources_once`、`…optional_dependency_error_reverse_closes_resources_once`、`…startup_failure_after_closeable_construction_reverse_closes_once`、`test_scheduler/test_cli.py::…scheduler_startup_failure…`、`test_app.py::test_pilot_active_close_enters_closing_requested_and_stops_actions`、`…close_deadline_violation_is_shutdown_blocked_without_force_exit`。
- **Observable oracle:** projection action 集合、provider/tool call 计数、close 计数、closing_requested/shutdown_blocked。
- **Red command:** `.venv/bin/python -m pytest tests/tui`（旧：submit-only、renderer 作 sink、close 绕过）。
- **Green change:** `agent/tui/{render,app}.py`、`agent/composition.py`、`main.py`、`agent/cli/actions.py`。
- **Green command:** `.venv/bin/python -m pytest tests/tui tests/cli/test_entrypoint.py tests/scheduler/test_cli.py -q`。
- **Green exit:** 0；tui 25 + cli 22 + scheduler 4。
- **Boundary verification:** reject 键盘旅程执行计数为 0；reverse-close 每路径恰好 1 次。
- **Files owned:** `agent/tui/adapter.py`、`agent/tui/app.py`、`agent/tui/render.py`、`agent/cli/actions.py`、`agent/composition.py`、`main.py`、`tests/tui/*`、`tests/cli/test_entrypoint.py`、`tests/scheduler/test_cli.py`。
- **Deviation/residual risk:** 单 conversation；active worker 不 force-cancel（保持 closing_requested/shutdown_blocked）。

### U8A materialize/provisional verdicts

- **Finding/requirements:** R5、R22、R24；AE10。
- **Observable oracle:** `--content` exit 0 + 未截断 summary；origin 排除 dirty tree；deny-network 先证明阻断。
- **Green command:** `.venv/bin/python scripts/verify_materialized_tree.py --content`。
- **Green exit:** 0；`content gate: ALL CHECKS PASSED`；pytest `322 passed`。
- **Boundary command:** `.venv/bin/python scripts/verify_materialized_tree.py --control-seal`。
- **Boundary exit:** 1（controls 未封存；executor 不写 sealed）。
- **Files owned:** `scripts/verify_materialized_tree.py`、`docs/implementation/009_DELIVERY_MANIFEST.json`、`docs/implementation/009_EXECUTION_LOG.md`。
- **Deviation/residual risk:** Darwin sandbox-exec profile 需 `(allow default)` 以允许 ruff(Rust) 运行时；`(deny network*)` 仍生效（loopback 探针 DENIED）。

## Delivery manifest record

- Baseline commit: `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`（存在、完整 40-char SHA）。
- Schema: `my-first-agent/delivery-manifest/v2`。
- Exact ordinary entry count: 936（138 add / 20 modify / 778 delete）。
- Exact control files: `docs/implementation/009_DELIVERY_MANIFEST.json`（self-digest-forbidden）、`docs/implementation/009_EXECUTION_LOG.md`、`docs/architecture/CURRENT_CAPABILITY_STATUS.md`、`docs/implementation/009_INDEPENDENT_REVIEW.md`（后三者 `sha256:null, seal_state:unsealed-u8`，待 reviewer 封存）。
- Denied runtime/private path test: `test_denied_and_unknown_paths_fail_before_content_read_or_hash`（deny 先于 read/hash）。
- Unknown untracked fail-closed test: 同上 + `test_membership_reconciles_tracked_delta_explicit_untracked_and_operations`。
- Real Git index unchanged proof: `test_materialization_uses_temporary_index_without_touching_real_index`（`GIT_INDEX_FILE` 临时索引；before/after sha256 相等）。
- Manifest final ordinary digest freeze: 158 个 add/modify 的 sha256 + git_mode 在 U8A 冻结（手工 admission，非自动 generate）。
- No-follow regular-file/link-count/Git-mode admission proof: `admit_descriptor` 单一 fd；v2 oracle `test_manifest_validation_uses_one_no_follow_descriptor_for_metadata_and_digest`。

Never record denied/private file contents or hashes.

## Final gate record

| Gate | Exit | Result summary | Evidence level |
|---|---:|---|---|
| `git diff --check` | 0 | OK | formatting |
| `.venv/bin/ruff check .` | 0 | All checks passed | E0/E1 |
| architecture/kernel/tools/provider | 0 | 150 passed（arch 23 / kernel 75 / tools 13 / provider 39） | E1/E2 |
| capability focused suites | 0 | mcp 43 + memory 21 + subagent 14 + scheduler 13 + skill 34 + tui 25 + cli 22 = 172 | E1/E2 |
| `.venv/bin/python -m pytest -q -rx` | 0 | 322 passed | E1/E2 |
| `scripts/verify_materialized_tree.py --check-membership` | 0 | membership ok: 936 entries | E2M |
| `scripts/verify_materialized_tree.py --content` | 0 | ALL CHECKS PASSED；pytest 322 under sandbox-exec deny-network | E2M |
| `scripts/verify_materialized_tree.py --control-seal` | 1 | controls unsealed（executor 不封存；reviewer 待 seal） | n/a（正确拒绝） |

## Materialized origin proof

- Temporary tree/prefix: 限定 `/var/folders/.../009-tree-*`、`009-prefix-*`、`009-neutral-*` basenames（`tempfile`，退出即清）。
- Product module origins: non-editable install prefix site-packages（`agent.__file__` 在 prefix 内）。
- Console entrypoint origins: `first-agent` 由 prefix 安装。
- Neutral cwd: `009-neutral-*` 临时目录（非 REPO）。
- Import-injection variables cleared: `PYTHONPATH`/`PYTHONHOME` 清除后设为 prefix site-packages + materialized tree（prefix 优先）。
- Original dirty-tree origin negative assertion: `assert <REPO> not in agent.__file__/main.__file__`。
- Network/package-index access: 无（`PIP_NO_INDEX=1`；sandbox-exec `(deny network*)`）。
- OS deny-network boundary and DNS/TCP negative preflight: sandbox-exec loopback listener 探针 → `DENIED`（EPERM）；不可用/未阻断 fail closed。

## Capability verdicts

executor 填 E1/E2/E2M 与 provisional claim；`Final claim` 由 reviewer 审查后填写。
reviewer（U8B）已审查并填写 `Final claim`：本轮不晋级任何 capability 到 `locally-verified`。
E2 诚实性纠正（N3）：MCP/Memory/SubAgent/Scheduler/Skill 的完整 production boundary journey/fault matrix 本轮未闭合，
准确值为 `partial`（focused suite 通过 ≠ E2 闭合），故保持 `implemented-candidate`。

| Capability | E1 | E2 | E2M | E3 | Provisional verdict | Final claim | Limitation |
|---|---|---|---|---|---|---|---|
| Minimal Runtime Kernel | pass | pass | pass | n/a | implemented-candidate | implemented-candidate（reviewer-sealed） | foundation only；非闭合 capability 集 |
| MCP | pass | partial | pass | pending | implemented-candidate | implemented-candidate（reviewer-sealed） | receipt/transport/latch matrix 未完整闭合；无 E3 |
| Memory | pass | partial | pass | pending | implemented-candidate | implemented-candidate（reviewer-sealed） | durability/recall closure pending |
| SubAgent | pass | partial | pass | blocked unless supported provider exists | implemented-candidate + safe-unavailable + E3-blocked | implemented-candidate + safe-unavailable + E3-blocked（reviewer-sealed） | current HTTP adapters unsupported；无 supported provider E2 |
| Scheduler | pass | partial | pass | pending | implemented-candidate | implemented-candidate（reviewer-sealed） | busy/conflict reconciliation matrix pending |
| Skill | pass | partial | pass | pending | implemented-candidate | implemented-candidate（reviewer-sealed） | identity/metadata closure pending |
| TUI | pass | pass* | pass | pending | implemented-candidate | implemented-candidate（reviewer-sealed） | one conversation；active worker 不 force-cancel；event-fault oracle pending（N2） |

`*` TUI 的 R19-R20 闭合已验证（5/6 fault-matrix 组），但 event loss/duplicate/reorder 注入 oracle 缺失（N2），不满足 `locally-verified` 的完整 fault matrix 要求。

## Deviations and blockers

| Unit | Type | Evidence | Decision/next action |
|---|---|---|---|
| U8A | environment | Darwin sandbox-exec 自定义 profile 默认拒绝 ruff(Rust) 的 stack guard page；需 `(allow default)`，`(deny network*)` 仍阻断（loopback 探针 DENIED） | 已作为 verifier profile 固化；非产品变更 |
| U1 | environment | 隔离副本工作树含 `.claude-runtime/`（sandbox 基础设施，untracked） | 按 `.claude-runtime/` 前缀路径拒绝，永不 read/hash；不进 manifest |
| — | — | 无 true blocker | — |

## E3 handoff

All E3 tasks remain pending during 009。
SubAgent remains E3-blocked unless a provider satisfying R14-R16 exists and was verified without weakening the contract。

## Independent promotion handoff

- Reviewer distinct from implementation agent/session: pass（独立 reviewer session，2026-07-23）。
- Exact manifest path/type admission reviewed: pass（936 entries；baseline 存在；无 denied/control 路径漏入；no-follow descriptor；temp index；无 generate/self-hash）。
- F1-F9 observable-oracle test bodies reviewed: pass（读 test body 非 test name；F1 v2 8 oracle、F6 Pilot 全键盘+lifecycle、F9 log 一致；F3-F5/F7-F8 诚实 provisional）。
- Full gate receipts and origin/network proof reviewed: pass（materialize+install+origin+ruff+pytest 322+deny-network DENIED）。
- Independent reviewer reran `--content` before control edits: pass（exit 0；`322 passed in 24.36s`；未截断）。
- Per-capability limitation and claim decision: done（全部 implemented-candidate；SubAgent + safe-unavailable + E3-blocked；无 locally-verified；无 accepted；residual N1/N2/N3 见 independent review）。
- `docs/implementation/009_INDEPENDENT_REVIEW.md` completed: done。
- Independent reviewer authorized control seal: done（三个 reviewer control digest 已冻结并写 `sealed-u8`）。

The later `--control-seal` exit code and untruncated summary belong only in the out-of-repository final report；do not edit this file after the seal。
