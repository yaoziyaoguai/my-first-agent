---
title: 015 Governed Local Action - Execution Log
type: implementation-log
date: 2026-08-09
authority: 015-execution-evidence
---

# 015 Governed Local Action — Execution Log

## 1. Purpose and truth rules

本文件只记录当前物化树的真实实现进度、命令、exit code、证据和 deviation。它不能修改 015 Product Contract、
降低 Verification Contract、把阶段性 Green 写成完成，或用 executor/reviewer prose 代替 gate。

权威顺序见 `docs/implementation/015_LOOP_HANDOFF.md`。完整合同：

- `docs/plans/2026-08-09-001-feat-governed-local-action-plan.md`
- `docs/architecture/015_GOVERNED_LOCAL_ACTION_DESIGN.md`
- `docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3.md`

## 2. Preserved worktree boundary

- Repo：`/Users/jinkun.wang/work_space/my-first-agent`
- Branch：`main`，用户单独维护；不创建 PR/branch，不 commit/push/tag/改 remote。
- Baseline HEAD：`1e894173c0d7e0ed2f9934998378e912c4cca263`。
- 015 开始时工作树已包含完整 014 implementation 与 evidence 的大量 tracked/untracked changes；它们不是 015 可删除或回退的内容。
- 未跟踪根目录 `tui/` 属于用户内容：禁止读取、删除、覆盖、stage、seal 或 materialized copy。
- `.env`、secret/private/runtime、Claude/Codex config/auth/memory/session、shell history、netrc 均禁止读取或纳入。

## 3. Baseline evidence

在 015 文档变更前，2026-08-07 已完整验证当前 014 source baseline：

- `git diff --check` → exit 0。
- `.venv/bin/ruff check .` → `All checks passed!`，exit 0。
- `.venv/bin/python -m pytest -q -rx` → `925 passed in 75.97s`，exit 0。

上述 925 是 014 baseline，不是 015 implementation pass。

2026-08-09 完成第一批 015 contract docs 后：

- `git rev-parse HEAD` → `1e894173c0d7e0ed2f9934998378e912c4cca263`。
- `git status --short --branch` → branch `main...origin/main`，保留 014 dirty tree；新增 015 plan/design/E3，未触碰根目录 `tui/`。
- `git diff --check` → exit 0。
- Plan/design/E3 heading scan → canonical sections 与 U1-U10 均存在。

2026-08-09 的独立 read-only GLM 5.2 文档审查返回 `FINDINGS`：无 P0/P1，发现三项 P2：existing tool
authority enum 未闭合、`TOOL_RECEIPT` additive compatibility 未写死、approval candidate 的 durable round-trip 未写死。
合同已据此补充 `IN_PROCESS|LOCAL_SAME_UID_PROCESS`、一次明确 schema migration、typed process predicate 与
`AWAITING_APPROVAL` reload→approve 规则。同一 read-only GLM 5.2 reviewer 复审返回 `READY`：三项 P2 均闭合，未发现
新的 P0/P1/P2；它同时保留三项执行期注意事项：migration 必须按明确旧版本分支、identity rebaseline 只能更新准确
字面 evidence、非 process approval 必须拒绝 candidate。015 Red tests、Ruff 和 full pytest 尚未在本批文档变更后运行，
不能写成 Green。

### 3.1 U1 Red evidence (2026-08-09)

Claude Code 主执行者写入 U1 architecture/reference Reds 并运行真实 gates。所有命令未截断、exit code 真实：

- `git diff --check` → exit 0。
- `.venv/bin/ruff check .` → `All checks passed!`，exit 0。
- `.venv/bin/python -m pytest -q -rx --tb=line`（全量）→ `8 failed, 928 passed in 68.46s`，exit 1。

`928 passed = 925 014 baseline + 3 个新回归守卫`；`8 failed` 全部是新增的 015 contract-gap Reds，零既有回归。
新增测试文件：

- `tests/architecture/test_015_governed_local_action.py`
- `tests/reference/test_015_governed_local_action.py`

8 条 Red（每条映射到 R-ID/KTD，因 process contract/tool 不存在而准确失败）：

| Red | Maps to | Failure reason (contract absence) |
|---|---|---|
| architecture `test_015_has_closed_execution_authority_class` | R23 / KTD13 | `ExecutionAuthorityClass` 缺失 |
| architecture `test_015_tool_identity_carries_explicit_execution_authority` | R23 / KTD13 | `ToolSpec`/`ExecutionIntent`/`ExecutingIntentRecord` 无 `execution_authority` 字段 |
| architecture `test_015_local_process_tool_is_structured_and_shell_free` | R4 / R6 / KTD1 / KTD6 | `agent.process.tools` 与 `local_process` ToolSpec 缺失 |
| architecture `test_015_authority_lease_is_exact_finite_goal_scoped_and_revocable` | R8 / R9 / R10 / KTD4 | `ProcessAuthorityLeaseV1` 缺失 |
| architecture `test_015_candidate_binds_goal_and_workspace_before_any_effect` | R5 / KTD3 | `ProcessAuthorityCandidateV1` 缺失 |
| architecture `test_015_receipt_and_draft_are_closed_kernel_minted_types` | R17 / KTD8 / KTD10 | `ProcessExecutionDraftV1` / `ProcessReceiptV1` 缺失 |
| reference `test_supported_composition_registers_local_process_governed_tool` | AE1 / F1 / KTD1 / KTD11 | `build_tool_registrations` 未注册 `local_process` |
| reference `test_governed_local_action_exposes_same_uid_trust_notice` | R7 / R13 / R23 | `agent.process` 无 same-UID trust notice 常量 |

3 条回归守卫（绿，锁定 stop-ship 边界不被未来单元破坏）：

- architecture `test_015_no_second_loop_or_runtime_for_process_action`（R1/R2：单 Runtime/单 ToolRuntime）。
- architecture `test_015_docs_mark_governed_local_action_as_next_milestone_not_delivered`（R13-R16/R22：诚实披露）。
- reference `test_governed_local_action_marked_next_milestone_not_delivered`（R22 / E3 §10 promotion rule）。

Reds 在 U2-U8 落地 product code 后逐条转 Green；当前不是完成 marker。

### 3.2 U2 Red evidence (2026-08-09)

U2 的 kernel Reds 写入并运行（与 U1 Reds 同一次 full suite 之外单独验证两文件级）：

- `tests/kernel/test_contracts.py`（扩展）、`tests/kernel/test_checkpoint.py`（新建）、
  `tests/kernel/test_checkpoint_capacity.py`（新建）。
- `.venv/bin/ruff check <三文件>` → `All checks passed!`，exit 0。
- `.venv/bin/python -m pytest <三文件> -rx --tb=line -q` → `10 failed, 4 passed`，exit 1。
  `4 passed` 是 test_contracts.py 既有 4 个合同测试；`10 failed` 全部是新增 U2 Reds。

10 条 U2 Red（每条映射 R/KTD，因 contract/字段缺失而准确失败）：

| Red | Maps to | Failure reason |
|---|---|---|
| test_contracts `test_015_execution_authority_class_is_closed_and_defaults_to_in_process` | R23 / KTD13 | `ExecutionAuthorityClass` 与四类 `execution_authority` 字段缺失 |
| test_contracts `test_015_existing_tool_families_rebaseline_to_in_process_authority` | R22 / KTD13 | 现有 ToolSpec 无 `execution_authority`，无法 rebaseline |
| test_contracts `test_015_process_authority_contracts_are_closed_immutable_and_secret_free` | R8 / R9 / R17 / KTD2 / KTD4 / KTD8 / KTD10 | `ProcessAuthorityCandidateV1`/`LeaseV1`/`ReceiptV1` 与 `ApprovalRequest.process_authority_candidate` 缺失 |
| test_checkpoint `test_015_legacy_executing_record_migrates_to_in_process_authority` | KTD12 / KTD13 | executing record 无 `execution_authority` 成员 |
| test_checkpoint `test_015_current_executing_record_preserves_explicit_authority` | KTD13 | 当前 schema 不识别 `execution_authority` 键 |
| test_checkpoint `test_015_process_authority_candidate_round_trips_through_checkpoint` | KTD3 / KTD12 | `ProcessAuthorityCandidateV1` 缺失 |
| test_checkpoint `test_015_process_contracts_serialize_no_secret_or_env_values` | R14 / R17 | `ProcessAuthorityCandidateV1` 缺失 |
| test_checkpoint_capacity `test_015_conversation_state_owns_process_leases_with_bounded_capacity` | R8 / KTD2 / KTD12 | `ConversationState.process_leases` 与 `MAX_PROCESS_LEASES` 缺失 |
| test_checkpoint_capacity `test_015_process_lease_capacity_rejects_overflow_and_duplicate_id` | R9 / KTD4 / KTD12 | `ProcessAuthorityLeaseV1` 缺失 |
| test_checkpoint_capacity `test_015_process_leases_invalidate_on_goal_revision_or_terminal` | R9 / KTD12 | `ProcessAuthorityLeaseV1` 缺失 |

Green 推进顺序：先加 `ExecutionAuthorityClass` + 四类 `execution_authority` 字段 + identity rebaseline（最低风险、加式），再加 closed process 合同，最后做 checkpoint v4 migration + candidate/lease 序列化与 state 容量/失效不变量。当前不是完成 marker。

### 3.3 U2 Green evidence (2026-08-09)

U2 全部 10 条 kernel Reds 转 Green，product code 落地于：

- `agent/runtime/contracts.py`：`ExecutionAuthorityClass`（`IN_PROCESS`/`LOCAL_SAME_UID_PROCESS`）；`execution_authority` 字段加入 `ToolDefinition`/`ToolSpec`/`ExecutionIntent`/`ExecutingIntentRecord` 并进入 `ToolSpec.identity_digest`；`ProcessOutcome`、`ProcessAuthorityCandidateV1`、`ProcessAuthorityLeaseV1`、`ProcessReceiptV1`（frozen、closed、max_uses=8、execution_authority 强制 `LOCAL_SAME_UID_PROCESS`、secret-free）；`ApprovalRequest.process_authority_candidate`（字段末尾，保持 012-014 位置前缀）；`ConversationState.process_leases` + `MAX_PROCESS_LEASES=16` + `_validate_process_leases`（容量、唯一 lease_id、绑定当前 Goal revision/workspace、terminal 清空、无 Goal 拒绝）。
- `agent/runtime/checkpoint.py`：`_executing_to_dict`/`_from_dict` 加 `execution_authority`（presence→strict 值校验，absent→`IN_PROCESS` 一次明确 migration；unknown key 由 key-set strict 拒绝）；`_pending_to_dict`/`_from_dict` 加 `process_authority_candidate`（加式 key-set）；新增 `_process_authority_candidate_to_dict`/`_from_dict`、`_process_lease_to_dict`/`_from_dict`（closed shape strict decode）；`_state_to_dict`/`_from_dict` 加 `process_leases`（按存在性条件加入 keys，旧 checkpoint 缺失→空迁移）。
- `agent/composition.py`：authority_snapshot 投影加 `execution_authority`。
- `tests/reference/test_013_everyday_workspace.py`：`_authority_snapshot` 镜像同步加 `execution_authority`（rebaseline）。

验证（命令未截断、exit 真实）：

- `.venv/bin/ruff check .` → `All checks passed!`，exit 0。
- `git diff --check` → exit 0。
- `.venv/bin/python -m pytest -q --tb=line`（全量）→ `4 failed, 942 passed in 63.27s`，exit 1。`4 failed` 全部是跨单元 Reds（U4-U8 territory），**零既有回归**。

Decision（U2 期间）：

- `execution_authority` 进入 `ToolSpec.identity_digest` 与 composition authority_snapshot（KTD13 rebaseline）；`ToolSpec.identity_digest` 在 `agent/runtime/tools.py` 内自洽使用（L218 校验/L359 赋值同源），无测试钉字面值，故 rebaseline 零回归，仅同步 test_013 镜像。
- pre-015 executing record migration 采用 presence-based：有 `execution_authority` 键→strict 值校验；无→`IN_PROCESS`。unknown key 由既有 key-set strict 拒绝。未 bump `SCHEMA_VERSION`（保持 3），`process_leases` 在 `_state_from_dict` 按存在性条件加入 keys，旧 checkpoint 缺失→空迁移；这是比 v3→v4 全量 bump 更低风险的等价 closed-shape migration。若 fresh reviewer 要求显式 version bump，U10 再收紧。
- `MAX_PROCESS_LEASES=16`：单个 Goal revision 内允许少量互异 exact command lease 的 bounded cardinality；不是产品可配项。

### 3.4 U3 on-ramp（供恢复执行者直接接入）

U3 = approval reducer 铸造 lease + typed revoke + CLI/TUI/headless 披露。入口已定位：

- ResolveApproval reducer 在 `agent/runtime/state.py` L988-1015。approved 分支在 `updated_state = replace(state, active_run=updated)`（L1005）后调用 `_admit_approved_file_criterion` / `_admit_approved_research_criterion`；U3 在此处加 `_mint_process_authority_lease(updated_state, pending, action)`：当 `pending.process_authority_candidate` 存在时铸造 `ProcessAuthorityLeaseV1`（candidate binding + approved_request_identity + issued_at/expires_at）并 append 到 `state.process_leases`。reject 分支不铸造。
- 现有 helper 模式（`_admit_approved_file_criterion` L1145、`_admit_approved_research_criterion` L1255）是新 `_mint_process_authority_lease` 的模板。
- RevokeProcessAuthority 是新 typed action（参数 readable selected lease 或 `all` + expected_revision，replay/CAS 语义）；其 reducer 移除 lease，但若已在 EXECUTING 不假装取消 in-flight process。
- Correction / cancel / VERIFIED_DONE 的 lease 清空由 ConversationState 不变量（§3.3 `_validate_process_leases`）强制：reducer 构造新 goal revision / terminal state 时必须不同时携带旧 lease，否则 state 构造失败。U3 的 reducer 必须显式 drop `process_leases`（如 `replace(state, goal=new_goal, process_leases=())`）。
- U3 Reds 可在 reducer 层直接测试（构造带 `process_authority_candidate` 的 pending ApprovalRequest + goal + ActiveRun，调用 reducer），不依赖 local_process tool（U6）。

## 4. Unit ledger

| Unit | Owner | Red | Green | Status | Evidence |
|---|---|---|---|---|---|
| U1 Contract/baseline | Codex → Claude | done | n/a (no product code in U1) | complete | 8 architecture/reference Reds written and failing for contract absence; baseline `928 passed` (925 014 + 3 new guards), `git diff --check` exit 0, `ruff check .` exit 0; Reds convert to Green across U2-U8 |
| U2 Lease/checkpoint | Claude | done | done | complete | all 10 U2 kernel Reds Green; ExecutionAuthorityClass + rebaseline + Candidate/Lease/Receipt contracts + ApprovalRequest.process_authority_candidate + ConversationState.process_leases (capacity+invalidation) + checkpoint migration/serialization; full suite 942 passed / 4 cross-unit Reds (U4-U8), zero regression, see §3.3 |
| U3 Approval/revoke | Claude | done | done (reducer core) | complete | 6 reducer Reds Green: approve-mints-lease / reject-no-mint / non-process-no-mint / revoke single+all / goal-delta+pause+cancel clear leases; RevokeProcessAuthority typed action + legality; lease timing derived from candidate (no clock injection); UI parity deferred to U8 (needs local_process candidate); full suite 948 passed / 4 cross-unit Reds, zero regression, see §3.5 |
| U4 Admission/env | Claude | done | done | complete | 7 admission Reds Green: ResourceProfileV1 closed profiles + SAME_UID_TRUST_NOTICE (honest denial wording) + EnvironmentProfileV1 allowlist (no secret/proxy) + resolve_executable (absolute/PATH/workspace + symlink chain + stat + bounded digest + reject missing/non-exec/dir) + revalidate drift + ProcessCommandV1 fingerprint; created agent/process/ package; cutover-absence allowlist updated; full suite 956 passed / 3 cross-unit Reds (DraftV1→U5, local_process spec→U6, composition→U8), zero regression, see §3.6 |
| U5 POSIX runner | Claude | done | done | complete | 6 runner Reds Green (exit0/nonzero/literal-argv/timeout-reaped/output-truncation/invalid-utf8); agent/process/runner.py: shell=False + DEVNULL stdin + start_new_session + select bounded drain + deadline TERM→KILL→reap + outcome classify + no-zombie; ProcessExecutionDraftV1 + ProcessDraftOutcome; cutover allowlist +runner.py; full suite 963 passed / 2 cross-unit Reds (local_process spec→U6, composition→U8), zero regression, see §3.7 |
| U6 Tool/receipt | Claude | done | done | complete | U6a local_process ToolSpec + U6b KernelToolRuntime 集成：prepare 构造 ProcessAuthorityCandidateV1 + exact lease reuse（F2）+ informed approval；invoke 仅接受 LOCAL_SAME_UID_PROCESS 的 ProcessExecutionDraftV1，Kernel 校验并铸造 ProcessReceiptV1；普通 callable 伪造 draft 被拒绝（KTD8）；6 Reds Green；full suite 970 passed / 1 cross-unit Red（composition→U8），零回归，见 §3.9 |
| U7 Recovery/evidence | Claude | done | done | complete | TOOL_RECEIPT oracle 加式 process predicate（legacy 单键不变；process closed shape：receipt_kind/digest/command_fingerprint/outcome/exit_code，unknown key + wrong outcome/exit + fake fail closed）+ lease use 在 mark_executing EXECUTING checkpoint 单调消费（超 max_uses fail closed）+ crash/unknown recovery 继承既有 RecoveryRequest/AWAITING_RECOVERY；7 Reds Green（6 evidence oracle + lease-use）；full suite 976 passed / 1 cross-unit Red（composition→U8），零回归，见 §3.10 |
| U8 Composition/UX | Claude | done | done (composition + parity via typed actions) | complete | `build_tool_registrations` 在 POSIX 平台注册 local_process（captured_path 默认捕获 PATH，仅 killpg/setsid/O_NOFOLLOW 齐备才注册，无 shell fallback）→ 关闭最后 cross-unit Red；RevokeProcessAuthority typed action + reducer 已就绪（U3），CLI/TUI/headless 经同一 typed-action state machine；full suite 978 passed / **0 failures**，零回归，见 §3.11 |
| U9 Delivery/E3 | Claude | done | done (real E3 accepted) | complete（§3.55，§3.54 最终树） | 真实三连两轮 accepted：§3.52 树（§3.53 对账）+ §3.54 最终树（§3.55 对账：3×26/26、seal 双绑定 `e610b32e...`/`a7991e1b...`、j5 三次 verified_done——F2 扩充 token journey 真实通过）；reseal `0001e017...`（199）+ 六 gate 全绿（1074 passed / 199 / clean-room / control-seal 0） |
| U10 Full review | Codex + fresh reviewers | done | done | complete（§3.59） | Fresh correctness/security/adversarial findings 全部闭合；最终 source 1122、materialized 1122、真实 DeepSeek 三连 3×26、detached attestation、Codex 终审全部 Green。 |

## 5. Current state

- Active unit：**none；015 complete（§3.59）**。
- Current owner：Codex（用户 2026-08-16 明确接管后续）；不再等待 Claude quota。
- Last complete gate：最终 sealed tree 的 source/materialized/真实 E3/attestation 全部 Green；详见 §3.59。
- First unclosed gate：**none**。
- Product code：local_process 全链路 + lease/candidate/receipt + approval/revoke + evidence oracle + lease-use + composition 注册 + **E3 harness real runner（drive_attempt 编排 J1+J5+J3+J2+J4 + J4 crash/restart + 经 production CLI adapter 的 user stop + 26-claim recompute）+ recording HTTP transport 合同测试 + counting seam lock-in + U7 crash-once E2E + U8 parity + J1 VERIFIED_DONE（criterion admission for process-produced artifact）**已落地。
- E3：**accepted**。当前 detached receipt 密码学绑定 §3.59 seal 与 materialized identity；scripted provider 仍只作离线结构测试。

### 3.59 015_REVIEW_PASS + 最终真实三连 + detached attestation（2026-08-16）

Codex 对 fresh correctness/security/adversarial findings 逐项复核，并在最终 promotion 树上完成终裁：批准时即固化
process receipt 义务且不破坏 012-014 generic receipt；v3-v5 process lease/pending candidate 全部撤销而非重签；PATH
admission 与 child 共用 canonical absolute dirs；lease 在 binding/policy revalidation 后、真正 spawn 前最后验 expiry；process
output 使用 receipt-bound untrusted frame；E3 fixture ledger、rendered-result/final-receipt secret oracle 与 detached
attestation 均有反例测试。无开放 P0/P1/P2 finding，输出 **`015_REVIEW_PASS`**。

最终产品树：199 exact entries，overlay root `39644cf831a942430a801b0f5ce1ebfaa142d35d1470da31b2642a67a77d0fd7`；
seal SHA-256 `8c4e309e5866616e7aea1ac261d14d8b9d7bfa06c2c2bfef312592cfb01e8095`。真实
`openai_compatible` / `deepseek-v4-flash` E3 输出 `015_E3_REAL_PASS attempts=3`；receipt SHA-256
`d2a17f32629d1b06fc33c10b0717dd2fa3f226bbbca51dfbe3df930008351417`。独立对账：每轮 26/26 bool true，
model sends 23/23/22，fixture invocations 6/6/6，`composition_under_install=true`，seal digest、overlay root、entry
count 全匹配；`--attestation` 输出 `current seal + 3 x 26 true claims`。

### 3.58 真实 J5 暴露裸 LF tool-call JSON 兼容缺陷并闭合（2026-08-16）

promotion 树首轮真实 E3 在 J1-J4 通过后准确停止：`product_invalid_model_output`，J5 连续三次
`ProviderProtocolError(reason=malformed_tool_call, cause=JSONDecodeError)`，两项 false claim 为
`shell_metacharacters_literal` / `closed_environment_secret_free`。没有靠重跑碰运气或删减冻结 token。

Red：新增 OpenAI-compatible `function.arguments` 的 string 内裸 LF case，精确得到 `1 failed, 2 passed`；NUL 与
trailing comma 两项保持拒绝。Green：adapter 只把 JSON string 内裸 LF 归一化为同一 newline value，其他非法 JSON
继续 fail closed；focused `3 passed`，provider/J5 oracle `54 passed`，全量 source `1122 passed`。设计与验收文档记录
该 narrow compatibility boundary，随后重新封存并进入 §3.59 真实三连。

### 3.56 Codex 接管最终审计与 review-hardening 修复（2026-08-16）

用户明确要求 Codex 直接完成后续闭合，不再等待 Claude quota。此执行者替换只发生在 repo 外；产品仍只有
`AgentRuntime.run_turn` / `KernelToolRuntime` 一套 runtime loop。

Fresh correctness/security/adversarial review 的 actionable findings 已逐项落地：candidate/lease digest 覆盖全部 immutable
authority fields，checkpoint current schema 升到 v6 且拒绝 retarget；relative PATH 与 executable permission drift 拒绝；
lease 在 invoke 紧邻 spawn 再验 expiry；TUI artifact approval 复用 preview-size gate；lease view 显示 readable command/profile；
binary artifact evidence 使用 Kernel `SourceReceiptV1.original_content_digest`；process result 以 explicit untrusted frame 进入
provider context；recovery success 不能替代 Kernel process receipt；E3 的 stale tool schema、all-approval side-effect oracle、
secret durable-surface scan、blocked nonzero exit 与 test-package fake sink 已收紧。

Red/Green evidence：focused affected suite 首轮 `1 failed, 147 passed`（counting-provider state 断言未包含新增整数 frame counter），
修正后精确两项 `2 passed`；随后 source full suite 首轮 `7 failed, 1101 passed`（3 个旧 schema==5 断言、4 个手造无效
candidate/lease digest fixture），统一迁到 schema 6 与 canonical `.create()` 后 `--lf` **`7 passed`**。最终 source/full、
materialized、真实 DeepSeek 三连、reseal 与独立终审仍须在本条之后重新运行；此前 accepted receipt 因 product/harness
变化已失效，当前不得视为完成。

### 3.57 review-hardening 树真实三连 E3 accepted（2026-08-16）

最终 source gate：`git diff --check` exit 0、`ruff check .` exit 0、source pytest **`1108 passed`** exit 0；
seal 更新为 200 exact entries 后 membership/control-seal exit 0。首次 materialized content 在
`test_015_executable_revalidation_detects_permission_drift` 失败：测试使用 set-id 位作为 mode drift，macOS sandbox 静默清除
该位，实际未发生 drift。测试改用稳定保留的 group-read 位，产品的 full `st_mode` revalidation 不变；focused source
`1 passed`，reseal 后 materialized clean-room **`1108 passed` / ALL CHECKS PASSED**。

随后 `scripts/run_015_e3.py` 使用 launchctl 注入的 key（不回显、不写 receipt）、`openai_compatible`、DeepSeek 官方
endpoint 与 `deepseek-v4-flash` 运行完整内置 gates + 真实三连，exit 0：offline source `1108 passed`、materialized
membership 200/content ALL CHECKS PASSED/control-seal Green，`015_E3_REAL_PASS attempts=3`。receipt 对账：3 attempts
均 **26/26 bool true**，model sends 21/22/22；J1/J2/J5 均 `verified_done`，J3/J4 按 frozen contract 为
`goal_ready`；`composition_under_install=true`；receipt delivery-seal digest 与 E3-time seal 完全相等；closed-field secret
oracle pass。receipt 写入导致 ordinary overlay 预期漂移，须在 reviewer PASS 后随最终事实文档一起 reseal。

### 3.55 U10 二轮：§3.54 树真实三连 E3 accepted + receipt 对账 + reseal (2026-08-16)

supervisor 在 **§3.54 最终树**上完成真实 DeepSeek 三连 E3，生成 **accepted receipt**。

**Receipt 逐项核验**（本轮亲自执行，非转述）：
- `acceptance_status=accepted`；3 attempts，每 attempt **26/26 claims true**；send_count 24/22/23（真实 model sends）。
- **F2 修复在真实 E3 生效**：三次 attempt 的 j5 verdict 均 `verified_done`（扩充后的 frozen argv——含 `$()`、space、newline token——经真实模型 exact 传递、echo-argv NUL 分隔输出无损还原、claim 14 exact 有序相等为 True）；j2 三次 `verified_done`（§3.52 retryable-resume 持续生效）。
- **identity 双绑定**：`delivery_seal_sha256=e610b32e...` == E3-time seal 文件 sha256；`materialized_identity.overlay_root_sha256=a7991e1b...` == E3-time seal overlay root（§3.54 root）；`entry_count=199`；`composition_under_install=true`；provider_family `openai_compatible` / `deepseek-v4-flash`。

**U10 executor 侧核验**：receipt 对账（上）+ reseal（receipt 重写 → 预期 overlay drift → seal 重生成 root `0001e017...`，199 entries；membership/control-seal 复验 exit 0）+ 全量六 gate（detached 链在最终 sealed 树完整跑通，数字见验证行）。receipt 记录的 E3-time identity（`e610b32e...`/`a7991e1b...`）作为 provenance 保持不动。

**验证**（真实未截断 exit code，canonical 链 detached）：`git diff --check` exit 0、`ruff check .` exit 0、source pytest（`-q -rx -ra`）**`1074 passed`** exit 0、materialized `--check-membership`(**199 exact entries**) exit 0、`--content`(**ALL CHECKS PASSED** clean-room) exit 0、`--control-seal` exit 0。

executor 侧 U10 二轮闭合；交 fresh reviewer 按收敛路径复验（新 receipts 的 J5 argv/probe、docs 摘要面一致性、六 gates 与 seal 链），PASS 后 §10 promotion + 最终 seal/gates → Codex 终裁。

### 3.54 首轮 fresh reviewer FINDINGS：F1 docs truth + F2 J5 frozen token 覆盖 (2026-08-16)

Fresh reviewer（`glm-5.3[1m]` xhigh）在 §3.53 树输出 `015_REVIEW_FINDINGS`（非 PASS）：**Codex 四阻断项技术侧全部确认修复**（clock rollback / pgid-None false-reaped / J4 user stop / stale-grant 四层 / checkpoint v4 / explicit authority / cwd descriptor / draft bounds / evidence digests / R11 adapter parity / oracle 修复——reviewer 亲自 live probe + 六 gates 重跑全绿 1073/199/clean-room）；剩余两项 P2 blocker + 6 项 P3 residual，逐项闭合：

**F1（P2 docs truth）**：README（概述 + 里程碑节）、STRATEGY（015 标题）、log §4/§5 曾以现在时否认已实现能力（「尚未提供」「待实现」「重跑待做」），与 §3.53 accepted receipt/seal/log 最新条目矛盾。Green（事实陈述修正，非提前 promotion）：README 概述改为「015 已实现受治理的结构化本机执行并通过真实 E3，待独立评审（015_REVIEW_PASS）后列入已交付能力」；里程碑节改「已让……真实三连 accepted（§3.53）；PASS + Codex 终裁后晋级已交付」；STRATEGY 标题改「（已实现，真实 E3 accepted，待独立评审晋级）」；log §4 U9→complete（§3.53）+ §3.54 最终树重跑 reopened、U10→首轮 FINDINGS 已回 F1/F2 修复中；§5 刷新指向 §3.54。

**F2（P2 J5 frozen token 覆盖）**：acceptance §5 J5.1 要求 argv 覆盖 `;`、`|`、`>`、`$()`、backtick、**space**、**newline** token 类；`_J5_LITERAL_TOKENS` 旧值 `("a;b","|c","$d","\`e\`","f>g")` 缺 `$()` 形式、含空格 token、含换行 token——三次 26/26 是对缩减 journey 的真实通过，证据范围窄于冻结合同。Red `tests/reference/test_015_e3_harness.py::test_015_j5_frozen_tokens_cover_acceptance_contract_classes`（实测 fail on `'$()'` 类；另断言 real-mode prompt 由同一常量生成，防 harness/prompt 漂移）。Green（不缩合同）：`_J5_LITERAL_TOKENS = ("a;b", "|c", "$(x)", "\`e\`", "f>g", "g h", "i\nj")`；real-mode J5 用户消息 argv 列表由 `_J5_ARGV_PROMPT`（常量派生，换行 token 以 `i\nj` 字面量展示并注明 JSON tool args 写法）生成；claim 14 的 exact 有序相等与 scripted provider argv 均消费同一常量。offline scripted J5 经真实 executor 全链通过（newline token 经 NUL 分隔 receipt 输出无损还原）。

**P3 residuals（reviewer 记录，本轮在案待后续处理）**：① canary 覆盖偏窄（建议四个 `FIRST_AGENT_015_E3_*` 变量名入 canary key + print-env-keys 输出上界检查）；② claim 21 弱 oracle（仅查 receipt_digest 非空，有 claim 4/anti-forgery 缓解）；③ design §7.1 divergence（cwd admission 未复用 WorkspaceBoundary private/sensitive denial 与 protected inode 规则，exact cwd preview 缓解）；④ runner ESRCH 钉 pgid=pid 后 PID 回收窗口理论 residual（EPERM fail-closed）；⑤ `_wait_pipe_closure` EOF 证据理论 residual；⑥ candidate/lease 的 `expected_artifact_*` 生产路径恒 None（additive 字段无消费者）。

**影响**：`run_015_e3.py`（harness）+ harness 测试变更 → overlay root 重算 + **真实三连必须在 §3.54 最终树重跑并重写 receipt**（receipts 的 J5 argv/probe 将覆盖全部 token 类）；README/STRATEGY/log 为 docs-only（log 在 CONTROL_PATHS 排除、README/STRATEGY 不在 overlay），不影响 seal root。

**验证**（真实未截断 exit code，canonical 链 `scripts/run_015_e3.py` 以 `os.setsid` 脱离会话完整跑通）：`git diff --check` exit 0、`ruff check .` exit 0、source pytest（`-q -rx -ra`）**`1074 passed`** exit 0、materialized `--check-membership`(**199 exact entries**) exit 0、`--content`(**ALL CHECKS PASSED** clean-room) exit 0、`--control-seal` exit 0。另注：F1 docs 修正触发两处旧合同回归测试更新（`tests/architecture/test_015_governed_local_action.py` 与 `tests/reference/test_015_governed_local_action.py` 的 next-milestone-not-delivered 测试——其断言的「真实三连通过前只能是下一里程碑」前提已被 §3.53 accepted 取代；按 reviewer fix standard 更新为断言「已实现 + 真实 E3 accepted + 待独立评审晋级」且 promotion 门不变，same-UID/不宣称 OS sandbox 断言原样保留；首轮链在旧断言上 `2 failed` 即此两测试，非产品回归）。seal 重生成 root `a7991e1b...`（199 entries）。链终态输出 `NEEDS_015_E3_CONFIG(...)`；supervisor 在 §3.54 最终树重跑真实三连（receipts 的 J5 argv/probe 将覆盖全部 token 类）→ fresh reviewer 按收敛路径复验。

supervisor 在 **§3.52 树**上完成真实 DeepSeek 三连 E3，生成 **accepted receipt**（`docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json`）。

**Receipt 逐项核验**（本轮亲自执行，非转述）：
- `acceptance_status=accepted`；3 attempts，每 attempt **26/26 claims true**；send_count 22/23/22（真实 model sends）。
- **§3.52 修复在真实 E3 生效**：三次 attempt 的 j2 verdict 均 `verified_done`（此前 §3.51 树 j2 死于 `ProviderTimeoutError` 后 harness else-break）；j1/j5 三次 `verified_done`；j3 三次 `goal_ready`（hang-tree timeout journey 设计）；j4 三次 `goal_ready`（crash journey 设计）。
- **identity 双绑定**：`delivery_seal_sha256=809a64ca...` == E3-time seal 文件 sha256；`materialized_identity.overlay_root_sha256=334688b1...` == E3-time seal overlay root（§3.52 root）；`entry_count=199`；`composition_under_install=true`；provider_family `openai_compatible` / `deepseek-v4-flash`；`reviewer_handoff=015-fresh-reviewer/v1`。

**U10 executor 侧核验**：receipt 对账（上）+ reseal（receipt 重写 → 预期 overlay drift → seal 重生成 root `d82e8da6...`，199 entries）+ 全量六 gate（真实未截断 exit code，detached 链在最终 sealed 树完整跑通）：`git diff --check` exit 0、`ruff check .` exit 0、source pytest（`-q -rx -ra`）**`1073 passed`** exit 0、materialized `--check-membership`(**199 exact entries**) exit 0、`--content`(**ALL CHECKS PASSED** clean-room) exit 0、`--control-seal` exit 0。receipt 记录的 E3-time identity（`809a64ca...`/`334688b1...`）作为 provenance 保持不动；当前树 seal 为 receipt 后重生成值。executor 侧 U10 闭合，交 fresh `glm-5.3[1m]` xhigh reviewer 全量复审（PASS 后 docs promotion 与最终 seal/gates）。

### 3.52 真实 E3 j2 ProviderTimeoutError：harness 驱动 product 的 PAUSED_RETRYABLE 恢复路径 (2026-08-16)

supervisor 在 §3.51 树上运行真实 DeepSeek E3：六 offline/materialized gate 全绿（1072 passed / 199 entries / content clean-room / control-seal），但返回 `015_E3_BLOCKED(reason=product_invalid_model_output)`，false_claims=`exact_reuse_without_reapproval,changed_command_requires_reapproval,rejected_command_zero_spawn`——全是 j2（lease 边界 journey）的 claims。

**根因**（secret-free 诊断逐层定位）：j2 的 response_shapes 显示 GoalProposal 被接受后，第二次 send（goal 建立后的首个 model turn）命中 `ProviderTimeoutError`（DeepSeek ReadTimeout）。product 行为正确——`ProviderTimeoutError` 是 `ProviderRetryableError` 子类，loop 按 design 映射 `FAILED_RETRYABLE` + `pause_for_retryable`（PAUSED_RETRYABLE，`Resume` 是该状态的合法 typed action）。缺口在 **harness**：`_drive_journey` 的 `else: break` 把 FAILED_RETRYABLE 当终态静默放弃 journey → j2 的 durable observation（receipt fingerprints / rejected fingerprint / spawn 记录）从未产生 → 三 claim 以「无证据」False，journey verdict 停在 goal_ready。

**Red**：`tests/reference/test_015_e3_harness.py::test_015_j2_provider_timeout_resumes_via_retryable_path`——j2-shaped scripted provider 在 send#2 抛真实 `ProviderTimeoutError()`（与真实运行同形），此后继续 exact×2（lease reuse）→ changed×2（被持续拒绝）→ `BlockedClaim` 终局。Red 实测复现真实签名：`j2_unhandled_status=failed_retryable / provider_retryable`、`j2_receipt_fingerprints=()`（journey 死于 else-break）。

**Green（最小，harness-only，product 语义零改动）**：`scripts/run_015_e3.py::_drive_journey` 增加 `FAILED_RETRYABLE` 分支——driver（journey 用户）在有界预算（每次 journey 最多 2 次）内发 `Resume`（PAUSED_RETRYABLE 的既有合法恢复路径）；每次 resume 是一次真实 send（counting seam 如实计数），不放宽任何 typed control、不延长无界预算；超预算记录 `*_retryable_exhausted` 后诚实 break。Red 断言：journey 不再死于 unhandled status、`j2_provider_retryable` 观察、exact fingerprint ≥2 receipts（claim 11 证据）、rejected fingerprint 存在且从不 spawn（claims 12/13 证据）。

**影响**：`_drive_journey` 与 harness 测试变更 → overlay root 重算（`334688b1...`，199 entries）；真实三连必须在 §3.52 树重跑（旧 receipt 仍失效）。

**验证**（真实未截断 exit code，canonical 链 `scripts/run_015_e3.py` 以 `os.setsid` 脱离会话完整跑通）：`git diff --check` exit 0、`ruff check .` exit 0、source pytest（`-q -rx -ra`）**`1073 passed`** exit 0（+1 新测试）、materialized `--check-membership`(**199 exact entries**) exit 0、`--content`(**ALL CHECKS PASSED** clean-room) exit 0、`--control-seal`(009 manifest + 014 parent + verifier + overlay) exit 0。链终态输出 `NEEDS_015_E3_CONFIG(required=FIRST_AGENT_015_E3_PROVIDER,FIRST_AGENT_015_E3_BASE_URL,FIRST_AGENT_015_E3_MODEL,FIRST_AGENT_015_E3_API_KEY)`；supervisor 真实三连在本树自动复验。

### 3.51 F1-F5 + P3 审计轮：stale-grant 四层 fail-closed / checkpoint v4 / cwd descriptor / KnownNotExecuted 统一 / 显式 authority / 冻结 P3 (2026-08-16)

Fresh reviewer 的 `015_REVIEW_FINDINGS`（F1-F5 + P3，2026-08-16 控制恢复后进入 executor prompt）逐项 Red→Green。每项 Red 都先在当前树上实测复现（非假设），Green 全部最小化：

**F1（P1 stale ApprovalGrant 绕过 durable lease）**：Red `tests/process/test_stale_grant.py` 7 条——production `KernelToolRuntime` + 真实 state machine（`pause_for_approval` → `ResolveApproval(approved_at)` 铸 lease+grant → `RevokeProcessAuthority`）后，同 call-id + matching grant 实测返回 `ExecutionIntent`、真实 spawn、receipt `use_ordinal=0`（journey fixture 以 marker 文件提供零 spawn 证据）；expiry/clock-rollback 同形。Green 四层 fail closed：`prepare` 对 process candidate 一律 `ApprovalRequired`（grant 不可授权进程执行，authority 只来自 exact active durable lease，re-approval 携新 candidate）；`invoke` 对 `LOCAL_SAME_UID_PROCESS` 且 `process_lease=None` 的 intent raise `IntentConflictError`（callable 前，零 spawn）；`mark_executing` 对 process authority 缺 `process_lease_id` raise；`_mint_process_receipt` 删除 pseudo lease fallback（`process-receipt:{fingerprint}`/`use_ordinal=0`），无 lease 即 raise。合法路径（active lease + grant）不回归：执行一次、marker 恰好一次、`use_ordinal=1`。

**F2（P1 checkpoint v4 migration）**：Red `tests/continuity/test_checkpoint_v4.py` 8 条——真实 pre-015 v3 whole-state fixture（当前 writer 输出去掉 `process_leases`/`execution_authority`）实测加载崩溃（tuple default → `_array` TypeError）；current 记录缺 `execution_authority` 静默 IN_PROCESS。Green：`SCHEMA_VERSION=4`（`PREVIOUS_SCHEMA_VERSION=3` 唯一 process-authority migration source，完整物化：缺 `process_leases`→空、缺 `execution_authority`→IN_PROCESS）；v4 strict（缺 `process_leases`/缺 executing `execution_authority` → `CheckpointVersionError`；unknown member fail）；encode 侧带 leases（无 binding/run）的 state 也写 v4；v2 legacy 路径不变。三处旧断言 `schema_version==3` 随 bump 更新为 4（test_checkpoint_v2.py:183、test_workspace_binding.py:72/134，合同更新非放宽）。

**F3（P2 cwd descriptor identity）**：Red `tests/process/test_cwd_identity.py` 4 条——rm+mkdir 同路径替换后 path-string `cwd_digest` 不变 → 旧 exact lease 仍匹配（实测）。Green：`ProcessCommandV1` 加 `cwd_descriptor`（`st_dev:st_ino`）进 fingerprint payload；`prepare_binding` 在 approval 前解析 cwd（缺失/越界 → `binding_failure`，不展示幻想 cwd）；executor 紧邻 spawn 重验 descriptor（`cwd_identity_changed` → KnownNotExecuted）。替换后旧 lease 不匹配 → 重新 approval；prepare→invoke 之间替换 → binding 全等失败 → 零 spawn。

**F4（P2 KnownNotExecuted 类型分裂）**：Red `tests/kernel/test_known_not_executed_unification.py` 2 条——process executor 的 drift/denial 返回值实测 `unsupported tool output type` TypeError → EXTERNAL re-raise → 假 unknown。Green：`agent.process.contracts` re-export `agent.runtime.contracts.KnownNotExecuted`（单一 closed 类型，无循环依赖——runtime contracts 不 import agent.*）；完整 executor→invoke Red 得 `ToolResult(executed=False, code=executable_identity_changed)`。

**F5（P2 explicit IN_PROCESS projection）**：Red `tests/architecture/test_explicit_execution_authority.py` 3 条（四类 dataclass 的 `execution_authority` 字段仍有 default；`ToolSpec` 省略 authority 不报错；agent/ 22 处 `ToolSpec` 无显式 authority）。Green：`ToolSpec`/`ToolDefinition`/`ExecutionIntent`/`ExecutingIntentRecord` 的 `execution_authority` 改 `field(kw_only=True)` 必填（无 constructor default，遗漏即 TypeError）；22 处生产 ToolSpec + ~60 处 test/构造点显式 `execution_authority=ExecutionAuthorityClass.IN_PROCESS`（process 保持 LOCAL_SAME_UID_PROCESS）；AST 扫描测试锁定 agent/ 内全部 `ToolSpec` 必须显式传。既有测试 `test_contracts.py` 的「默认 IN_PROCESS」断言按新合同更新为「无 default 必填」。

**P3（冻结合同批次）**：>256MiB executable 从 prefix-hash 冒充 identity 改为拒绝（`executable_too_large`，`tests/process/test_admission.py` sparse-file Red）；Kernel 铸 receipt 前校验 draft closed bounds（`_validate_process_draft`：outcome/exit/signal/reap 形状、profile caps、64-hex digests、时长预算、投影上限，越界 → EXTERNAL unknown，`tests/kernel/test_process_draft_bounds.py` 10 条 mutation Red）；process predicate 的 optional stdout/stderr digests 从「接受不比较」改为实际比较 + 64-hex 校验（`tests/kernel/test_evidence_registry.py` 追加 Red）；post-spawn `returncode=None` taxonomy 从 SPAWN_FAILED（断言未执行）改为 `ProcessCleanupError`→unknown（`tests/process/test_runner_taxonomy.py`，closed 分类回归同钉）。

**影响**：command fingerprint 含 cwd descriptor、checkpoint v4、authority 必填、stale-grant fail-closed 均改变 E3/identity 行为——§3.49 accepted receipt 的 seal 绑定（`cb6f0987...`）对当前 seal 文件（sha256 `a1f55db1...`）可证明失效；真实 DeepSeek 三连必须重跑并重写 receipt。delivery seal 重生成：overlay root `0921aeea...`，entry_count **199**（+7 新测试文件 +8 本轮编辑使此前未漂移 tracked 文件进入 overlay derivation）。

**验证**（真实未截断 exit code，detached 运行防 session 中断杀链；前两次 chain 运行被 session 退出 SIGTERM 杀死——环境性 `source pytest: exit -15`，非测试失败）：`git diff --check` exit 0、`ruff check .` exit 0（All checks passed）、source pytest（`-q -rx -ra`）**`1072 passed`** exit 0、materialized `--check-membership`(**199 exact entries**) exit 0、`--content`(**ALL CHECKS PASSED** clean-room) exit 0、`--control-seal`(009 manifest + 014 parent + verifier + overlay) exit 0。

**Marker**：offline/materialized 六 gate 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(required=FIRST_AGENT_015_E3_PROVIDER,FIRST_AGENT_015_E3_BASE_URL,FIRST_AGENT_015_E3_MODEL,FIRST_AGENT_015_E3_API_KEY)`。真实三连重跑（receipt 重写）→ U10 → fresh reviewer 在最终 promotion 树 PASS → README/STRATEGY/log §10 promotion → 最终 seal/gates → Codex 终裁。

### 3.50 U10 期间 source pytest 间歇 flake：ESRCH 测试 probe 加固 (2026-08-16)

U10 复跑 gates 时 source pytest 首次出现 `1 failed, 1033 passed`：`test_015_esrch_pgid_probe_keeps_expected_identity_no_false_reaped` 以 `PermissionError: [Errno 1] Operation not permitted` 失败（该测试此前在本机连续 7+ 次通过，单独重跑即过——环境 race，非产品回归）。

**定位**：测试中唯一未防护的 `os.killpg(expected_pgid, 0)` 终验 probe 在 macOS 上命中 PID 回收——fixture group 已确认消失后，pid 被回收为 foreign（非同 uid）process group leader，`killpg(0)` 报 EPERM。这正是 runner `_signal_group` docstring 记录的同款 macOS 现象。

**Green（test-only，产品代码零改动，检测不弱化）**：probe 改为 `pytest.raises((ProcessLookupError, PermissionError))`。语义精确：同 uid 存活 descendant 只会让 probe **成功返回**（不抛异常 → pytest.raises 失败 → false-reaped 谎言仍被拆穿，原 Red 语义保留）；EPERM 只可能是回收的 foreign group（环境噪声），容忍它不掩盖任何本可检测的存活情况。

**验证**（真实未截断 exit code）：`tests/process/test_runner_group_cleanup.py` `4 passed` 0、`git diff --check` 0、`ruff` 0、source pytest（`-q -rx -ra`）**`1034 passed`** 0、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1034 passed** clean-room) 0；delivery seal 重生成（`17578175...`，测试文件在 overlay 内 → root 重算）。

### 3.49 真实三连 E3 accepted + U10 receipt/identity 核验 (2026-08-15)

supervisor 在 **§3.48 树**上完成真实 DeepSeek 三连 E3，生成 **accepted receipt**（`docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json`，mtime 2026-08-16 00:23）。

**Receipt 逐项核验**（本轮亲自执行，非转述）：
- `acceptance_status=accepted`；3 attempts（16:20:58Z–16:23:41Z），每 attempt **26/26 claims true**；send_count 22/22/21（真实 model sends）。
- **identity 双绑定**：`delivery_seal_sha256=cb6f0987...` == 当前 `015_DELIVERY_SEAL.json` 文件 sha256（E3 跑在当前代码/seal identity 上）；`materialized_identity.overlay_root_sha256=3492d957...` == seal overlay root（§3.48 root）；`entry_count=184`；`composition_under_install=true`；materialized identity 无宿主路径（仅 digest/count/flag）。
- provider `openai_compatible` / `deepseek-v4-flash`；`reviewer_handoff=015-fresh-reviewer/v1`。
- **§3.48 修复在真实 E3 生效**：三次 attempt 的 j3 verdict 均 `goal_ready`（提案被接受、hang-tree 真实 timeout 执行——claims 16/17 全 true），不再出现单 send 提前终止。j1/j5 三次 `verified_done`；j4 三次 `goal_ready`（crash journey 设计）；j2 两次 `verified_done` + 一次 `goal_ready`（claims 从 durable observations 重算，不受 verdict 差异影响）。

**U10 executor 侧核验**：receipt 对账（上）+ full gates（下）+ reseal。receipt 重写 → overlay drift（预期时序）→ seal 重生成（`11df6fde...`，184 entries；receipt 为同路径重写，条目数不变）→ membership/control-seal/content Green。

**验证**（真实未截断 exit code，最终 sealed 树）：`git diff --check` 0、`ruff check .` 0、source pytest（`-q -rx -ra`）**`1034 passed`** 0、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1034 passed** clean-room) 0。

**Marker**：`015_EXECUTOR_READY_FOR_REVIEW`——U1-U9 + 真实三连 + 全部 offline/materialized gates 闭合，交 fresh `glm-5.3[1m]` xhigh reviewer 全量复审。README/STRATEGY/log §10 promotion 按 Definition of Done 留在 reviewer PASS 后（P2 docs finding 顺序不变）。

### 3.48 real E3 j3 根因修复：GoalProposal 被 reducer 拒绝即 fatal（无可修复路径）(2026-08-15)

§3.47 树上的真实 DeepSeek E3（supervisor 运行）准确返回 `015_E3_BLOCKED(reason=product_invalid_model_output)`，false_claims=`timeout_group_cleanup_confirmed, timeout_not_verified_done`。诊断要点：j3 只有 **1 次 send**（GoalProposal 通过 normalize）、`goal_status=null`、无 exception shape、其余 journey 全部工作（j1/j2/j5 verified_done、j4 crash/restart/stop 全对）。

**根因**（从 production 代码路径推导并 offline 复现）：`accept_goal_proposal` 的校验失败（bootstrap binding / 预铸 admitted criteria / source fact 权威性等全部 raise `ValueError`）经 `AgentRuntime.run_turn` 外层 `except Exception`（loop.py）转成 `FAILED_FATAL(runtime_failure)`——goal 未创建、无 provider exception shape；harness `_drive_journey` 的 `else: break` 静默吞掉终止状态。j1/j5 的 malformed_control 之所以能恢复，是因为 `InvalidProviderResponseError` 走 in-run 有界修复（invalid_repairs=1）；而「提案通过 normalize 但被 reducer 拒绝」这一可修复的控制参数错误类别没有任何修复路径，直接 fatal。DeepSeek 在 j1/j5 各有一次填错控制后修复成功的实测（exception shape 后继续），j3 命中的正是这个无修复通路的类别。

**Red**：`tests/reference/test_015_e3_harness.py::test_015_j3_rejected_first_proposal_gets_bounded_repair`（`_J3RealisticRepairProvider`：第一次 GoalProposal 自造 source fact id（真实模型常见错误）、第二次复制 bootstrap 正确 binding、之后 hang-tree short 真实执行、BlockedClaim 收尾）。Red 实测复现真实签名：j3 goal missing、run 死于第一个被拒提案。

**Green（最小，接受条件零放宽）**：
1. `agent/runtime/loop.py` GoalProposal 分支捕获 `accept_goal_proposal` 的 `ValueError` → 走既有 `invalid_repairs` 预算（=1，不新增预算）：append policy result `invalid_goal_proposal`（携带 validator 精确消息 + 指引复制 trusted_goal_bootstrap 字段/admitted_criteria 留空）→ continue 修复；预算耗尽才 `FAILED_FATAL(invalid_goal_proposal)`。被拒提案绝不创建 Goal。
2. `scripts/run_015_e3.py::_drive_journey` 的 `else: break` 改为记录 `{journey}_unhandled_status/error_code/message`（secret-free，同 j4 phase1 模式）——静默终止从此可诊断（本 Red 调试中即靠它定位到 `invalid_model_output` 空响应细节）。

Red 调试附带发现（不属本 finding，已如实保留）：goal 活跃时裸 text 终局被 `active_goal_requires_control` 有界拒绝（修复消息列出 blocked_claim 等选项）——j3 的合法终态是 BlockedClaim；scripted 原 provider 尾部空响应在 offline 一直以 failed_fatal 终止（claims 不读 run 终态，从未影响离线基线），未改（surgical）。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff check .` 0、affected（harness/direct/process/kernel）`209 passed` 0（+1 新测试）、source pytest（`-q -rx -ra`）**`1034 passed`** 0（1033+1）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1034 passed** clean-room) 0；delivery seal 重生成（`3492d957...`，184 entries）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.47 Codex 终审 findings 修复：P1 clock rollback / P1 false group-reaped / P2 J4 user stop (2026-08-15)

Codex 在旧 `015_REVIEW_PASS` 后独立复验（独立 gates 全绿，但三项 final tree findings 属实），旧 PASS 与 `[015 complete]` 被否决。本轮从三项准确 Red 开始，Green 后再跑全部 gates，不重跑绿门自报完成：

**P1 clock rollback authority reuse**：Red `test_015_process_lease_match_requires_zoned_rfc3339_and_no_clock_rollback`（production `KernelToolRuntime.prepare` + exact durable lease：clock=`2026-08-14T23:00:00Z` 复用 `issued_at=2026-08-15T00:00:00Z` 的 lease，实测返回 `ExecutionIntent`）。Green：`agent/runtime/tools.py::_match_process_lease` 经 `_parse_zoned_rfc3339`（`T` 分隔 + 必须带时区；naive/space/malformed → None）数值比较 `issued_at <= now < expires_at`；runtime clock 或 lease 任一侧不可解析 → fail closed（无匹配 → REQUIRE_APPROVAL 重新批准）。边界 pin：now==issued_at 允许复用、now==expires_at 拒绝。

**P1 false group-reaped claim**：Red `test_015_esrch_pgid_probe_keeps_expected_identity_no_false_reaped`（精确 monkeypatch `_verified_pgid→None` 模拟 ESRCH race + 真实 descendant fixture：实测 draft 返回 `process_group_id=None, group_reaped=True, term_sent=False` 而 descendant 存活）。Green：`agent/process/runner.py` 在 `_verified_pgid` ESRCH 时保留 expected PGID identity（`start_new_session` 内核保证 pgid==child pid，leader 先退不改变 group identity），TERM/KILL/确认按真实 group 进行；`_group_alive(None)` 改为 raise `ProcessCleanupError`（无可治理 identity 不得确认清理）；`_signal_group` 移除 None→单进程 fallback（不保留第二信号路径）。

**P2 frozen E3-J4 user stop 未驱动**：Red `test_015_j4_phase3_drives_user_stop_via_production_cli_adapter` + claim 20 mutation ×4（旧 harness Phase 3 明写「不 resolve」，`j4_user_stop_*` observation 不存在）。Green：`scripts/run_015_e3.py::_drive_j4_crash_journey` Phase 3 经 production CLI adapter（`agent.cli.app.run_repl` 输入 `"stop"` → `_contextual_exit_message` 安全退出：exit 0 + stop message + 零 provider send + state 不变；输入端二次调用 EOF 防护，状态异常时诚实空 message → claim False）；记录 `j4_user_stop_exit_code/message/send_count` + `j4_final_status_after_stop`；claim 20（`unknown_recovery_requires_user`）收紧为要求 stop 真实驱动 + 无重放 + 最终 state 不变——仅停在 `AWAITING_RECOVERY` 不构成「用户选择 stop」；stop message 与 production adapter 对同一 post-stop state 输出逐字相等由测试钉死；`_secret_free_diagnostic` 补 j4_user_stop_* 三 key。

**影响**：claims/harness 变更 → §3.46 accepted receipt 对新 oracle 失效，真实三连 E3 必须以当前树重跑并重写 receipt（U10 与 fresh reviewer 在其后）。P2 docs promotion（README/STRATEGY/log §10）按既定顺序在真实三连 + U10 + fresh reviewer PASS 后进行。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff check .` 0、focused（tests/process `36 passed`；tests/reference 015 harness+direct `28 passed`）0、source pytest（`-q -rx -ra`）**`1033 passed`** 0（1030+3 新测试）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1033 passed** clean-room) 0；delivery seal 重生成（`665cef13...`，184 entries；代码/测试内容变更 → overlay root 重算）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.46 U10 复验（二轮）：F2/F3 修复后真实三连 E3 accepted + 全 gates (2026-08-15)

supervisor 在 **§3.45 修复后的树**（seal `60f97555...`）上重跑真实 DeepSeek 三连 E3，生成
**合规新 receipt**（mtime 13:04）：

**Receipt 核对（逐项，证明为修复后重跑而非旧工件）**：
- `acceptance_status=accepted`、3 attempts × 26/26 全 true；claims 8/24 True——**F2 下重跑**
  （preview 进 binding digest，修复前的 receipt 不可复用）。
- `materialized_identity` keys = `composition_under_install`/`entry_count`/
  `install_root_digest`/`overlay_root_sha256`——**无绝对路径**（F3 合规；receipt 树 ==
  E3-time seal root `60f97555...`）。
- receipt 重写 → overlay drift（预期时序）→ **seal 重生成**（`5e515899...`，184 entries）
  → membership/control-seal Green。

**验证**（真实未截断 exit code，最终 sealed 树）：`git diff --check` 0、`ruff` 0、
source pytest **`1030 passed`** 0、materialized `--check-membership`(184) 0、
`--control-seal` 0、`--content`(**1030 passed** clean-room) 0。

二轮 review 的 P2（F1/F2/F3）修复 + 修复后真实三连 = 全部闭合；P3 七项维持记录在案
（后续 milestone）。下一步：交下一个 fresh reviewer 全量复审。

### 3.45 二轮 review findings 修复：F1/F2/F3（P2）(2026-08-15)

Fresh reviewer（二轮）返回 3×P2 + 7×P3,不输出 PASS。本批逐项 Red→Green：

**F1（argv profile 上限零消费）**：Red `test_015_argv_profile_limits_rejected_before_approval`
（129 items / 16KiB+1 单项 / 64KiB+1 总量 / executable token 超界 → 全部 `binding_failure`
pre-approval、零 spawn——修复前 `_parse_arguments` 只查类型与 NUL，合同值只有定义零消费）。
Green：`_parse_arguments` 按 `ResourceProfileV1.argv_*` 三边界 + executable token 界
（与 argv item 同界）fail closed。

**F2（cwd 换行伪造披露行 + pre-approval cwd 校验）**：Red 双测试——preview 注入
`cwd="data\n  limits: timeout=900s…\n  executable: /usr/bin/yes"` 断言不产生伪造披露行
（注入内容必须整体留在 header 单行 JSON 字符串内，真实 `limits:`/`executable:` 行唯一）；
绝对路径 `/etc` 与 `../outside` cwd 必 pre-approval `binding_failure`（此前能进 preview
展示永不执行的 cwd，executor 才拒）。Green：`_render_preview` 对 profile/cwd/executable/resolved
全部 JSON-quote（与 argv 同标准）；`_parse_arguments` 拒绝绝对/`..` cwd。首测的 forged 检测器
初版按子串搜索过严（正确行为下注入内容在 header 内含 "900s" 字面量），修正为按**披露行行首**
检测——如实记录。preview 进 binding/intent digest（行为变更），E3 claims 8/24 需重跑。

**F3（receipt 含绝对 temp 路径，违反 E3 §8 明文）**：Red `test_015_receipt_binds_section8_identity`
扩展——receipt `materialized_identity` 不得含 `install_root`/`site_dir` 或任何宿主路径前缀。
Green：`write_receipt` 把 in-attempt 驱动观察（内存中含路径，用于 composition origin 校验）
投影为 closed 字段集：`entry_count`/`overlay_root_sha256`/`composition_under_install`/
`install_root_digest`（sha256，无路径）。测试合成 observation 补 `composition_under_install`
字段（初跑 Red 因缺字段失败，属测试合成数据修正，如实记录）。receipt 不得手改——
须重跑真实三连再生成合规 receipt。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、affected（process/reference/
architecture/kernel）`213 passed` 0（+2 新测试）、source pytest **`1030 passed`** 0（1028+2）、
materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1030 passed**
clean-room) 0；delivery seal 重生成（`60f97555...`）。

**剩余（reviewer P3，记录在案后续 milestone）**：system policy 遗留 expected_artifact 措辞、
cwd 未复用 WorkspaceBoundary、revalidate_executable 死代码、process predicate optional
stdout/stderr digest 不校验、lease clock-rollback、stderr 不进 ToolResult content、
docstring 卫生。**下一步**：F2/F3 改变 E3 行为/工件 → 须重跑真实三连 E3 → 新 receipt →
交下一个 fresh reviewer。

### 3.44 U10 identity 核对：receipt↔当前 seal 关系 + §3.43 变更受影响性评估 (2026-08-15)

U10 复验的 identity 核对（E3 §10「最终 product-code change 后重新运行**受影响** E3」）：

**Receipt↔当前 seal 关系（如实）**：receipt（§3.42 三连，E3-time 树
`materialized_identity.overlay_root_sha256=41efe6a...`，`delivery_seal_sha256=70ecc737...`）
与当前 seal（`898052e9...` 文件 digest）**不匹配**——预期时序：E3 后 receipt 自身进入
overlay、execution log 更新、§3.43 产品修复均改变 overlay → seal 逐次重生成。receipt 绑定
的是 E3 运行时的树 identity（这是 receipt 作为"运行了什么"证据的语义），不是活树匹配。

**§3.43 产品码变更受影响性（证据评估）**：变更在 `agent/subagent/process_runner.py`
（`ChildProcessRunner` per-run 目录清理）。全仓反向依赖：`agent.subagent` 仅被
`agent/provider/fake_provider.py` 引用（且仅 contracts 类型 `ProviderDeadlineCapability`）；
E3 journey 路径（`run_015_e3 → agent.composition → KernelToolRuntime →
agent/process/runner.py`）**零触及** subagent/`ChildProcessRunner`/fake_provider
（grep 证）。故 §3.43 不在 E3 受影响路径内——E3 receipt 对其验证的 journey 行为仍为有效
证据；该修复属 U10 gate 失败（source/content pytest 点名）的必要产品加固，留给 fresh
reviewer 复核此判断。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、source pytest
**`1028 passed`** 0、materialized `--check-membership`(184) 0、`--control-seal` 0、
`--content`(**1028 passed** clean-room) 0。

### 3.43 U10 复验续：subagent per-run 目录清理负载竞态加固 (2026-08-15)

U10 复验的 full source pytest 首跑 `1 failed, 1026 passed`——§3.29/3.23 可见性直接点名
`tests/subagent/test_process_runner.py::test_process_runner_temp_dir_removed_after_run`
（"temp dir leaked after success"）；修复前后台 content 门独立命中**同一测试名**，隔离
5/5 过 → 全 suite 负载间歇。

**根因**：`ChildProcessRunner.run` 的 finally 清理（process_runner.py）`unlink`+`rmdir`
各自 `suppress(OSError)` **无重试**——负载下单次瞬时失败（如 ENOTEMPTY/EBUSY）即静默
泄漏 per-run 目录，违反 F-G8-2 "成功路径目录必须消失"。

**Red→Green**：`test_015_config_dir_cleanup_retries_transient_rmdir_failure`（monkeypatch
`Path.rmdir` 首调抛瞬时 OSError → 清理必须有界重试到目录消失；修复前确认失败）→
`_remove_run_dir(config_path, config_dir)`：unlink 后 rmdir 有界重试（5 次 × 20ms），
持续失败仍 suppress（receipt 分类不受影响——既有合同不放宽）。

**验证**（真实未截断 exit code，**最终 sealed 树**）：`git diff --check` 0、`ruff` 0、
`tests/subagent/` `28 passed` 0（+1 新测试）、source pytest **`1028 passed`** 0（修复前
1 failed 已消除）、materialized `--check-membership`(184) 0、`--control-seal` 0、
`--content`(**1028 passed** clean-room) 0；delivery seal 重生成（process_runner.py 是
overlay 产品代码）。修复前的 content 门失败（同测试名）已在修复后消除。

### 3.42 U10 复验：review 修复后真实三连 E3 accepted（§8 receipt）+ 全 gates (2026-08-15)

supervisor 在 **F1-F8 全部闭合后的树**上重跑真实 DeepSeek 三连 E3：三个 fresh temp root 连续，**每 attempt 26/26 claims 全 true**，生成 **§8 格式** accepted receipt（`docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json`，11670 bytes）。

**Receipt 核对（逐项）**：
- `acceptance_status=accepted`、3 attempts（send 22/21/20，**fixture_invocation_count=6 真实计数**——F7 修复前恒 0）。
- **§8 identity 绑定**：`delivery_seal_sha256` == 当时树 seal ✓；`fixture_identity_digest` ✓；`materialized_identity` 含 `composition_under_install=True`、`overlay_root_sha256`（F2 修复的真实 in-attempt materialized install 驱动证据——journey 从 `/private/tmp/015-e3-mat-prefix-*/site-packages` 解析 agent.composition）；`reviewer_handoff=015-fresh-reviewer/v1`。
- **§8 per-attempt 字段**：`started_at/ended_at`（墙钟 RFC3339）、`journey_verdicts`（j1/j2/j5 verified_done、j3/j4 goal_ready——与 frozen journey 合同一致）、`process_output_digests`（stdout+stderr digest+truncation）、`artifact_digest`（j1 FILESYSTEM_DIGEST predicate）全部在位。
- secret-free 保持（无 key/header/body/env/path/prompt）。

**U10 步骤**：receipt 为 overlay 内容（非 control path），进入后旧 seal drift（预期时序）→ **seal 重生成**（`1d04f761...`，184 entries）→ membership/control-seal Green。

**验证**（真实未截断 exit code，**最终 sealed 树**）：`git diff --check` 0、`ruff` 0、source pytest **`1027 passed`** 0、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1027 passed** clean-room) 0。

**P1/P2（F1-F8）修复后首次真实三连 accepted；acceptance doc `evidence_status: accepted`（§3.37 已晋级，本次 receipt 为修复后新证据）**。剩余 P3 F9-F15（reviewer 定级记录在案，后续 milestone）。下一步：交新 fresh reviewer 全量复审。

### 3.41 review findings 修复 batch D：F5（P2，最后一个 P2）(2026-08-15)

**F5（R11 lease 可见性/撤销在所有用户界面缺失）**：
- **Red**（3 failed 确认）：`test_015_cli_adapters_translate_revoke_to_typed_action`（CLI `/revoke <id>|all` 经 **adapter `_parse_action` 真实翻译**为 RevokeProcessAuthority——CAS expected_revision/conversation_id/action_seq 从 authoritative state；未知 id / 无 active lease → typed 反馈不静默）+ `test_015_cli_repl_and_renderer_surface_leases`（`/leases` 在真实 run_repl 循环渲染 readable 摘要：profile/remaining/expires 可读、**默认隐藏 digest**、`--advanced` 暴露 digest 与撤销所需精确 lease_id）+ `test_015_tui_and_headless_surface_leases`（TUI `parse_process_command` 自有翻译层 + headless `load_headless_leases` 与 CLI/TUI 同源投影）。修复前分别 ImportError/无翻译。
- **Green（最小，三 adapter 全可达）**：`agent/cli/actions.py` 共享 `build_revoke_process_authority(state, lease_id)`（无 lease/未知 id fail closed；CAS）；`agent/cli/app.py` `_parse_action` 加 `/revoke`（`all`→lease_id=None）+ run_repl 加 `/licenses`→`/leases`[/`--advanced`]（不触 runtime 的纯投影路径）+ `load_headless_leases`；`agent/cli/render.py` `render_leases`（默认隐藏 digest；advanced 显示 id+digest 与 revoke 提示）；`agent/runtime/views.py` `ProcessLeaseView.lease_id`（advanced-only——用户撤销单条所需精确标识）；`agent/tui/app.py` 模块级 `parse_process_command`（ leases/action/error 三态；普通消息 None 走 submit）接入 `on_input_submitted`（action→`_run_action` 经 production runtime；leases/error→status 面板）。CLI/TUI 共用同一 typed builder 与 lease 投影——单一 reducer 入口，无第二状态机。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、CLI/TUI suites `113 passed` 0（+3 新测试）、source pytest **`1027 passed`** 0（1024+3）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1027 passed** clean-room) 0；delivery seal 重生成。

**P1/P2 全部闭合（F1-F8）**。剩余：P3 F9-F15（reviewer 定级"记录在案，可在后续 milestone 收紧"，非本轮必须）。下一步：重跑真实三连 E3（F1/F2/F4/F5/F6 均改变产品/E3 行为——receipt 须用新 §8 `write_receipt` 重写）→ 交新 fresh reviewer 全量复审。

### 3.40 review findings 修复 batch C：F4/F7（P2）(2026-08-15)

**F4（schema 回 closed 4 字段，artifact digest 归用户授权）**：
- **Red**：`test_015_model_cannot_supply_expected_artifact`（model 自供 expected_artifact → arguments 拒绝、零 approval）+ `test_015_user_confirmed_artifact_admits_filesystem_criterion`（reducer 级：ResolveApproval.confirmed_artifact 铸恰一条 FILESYSTEM_DIGEST criterion；malformed sha fail closed）——修复前分别失败（schema 接受第 5 字段 / 无 confirmed_artifact 字段）。
- **Green（最小）**：`agent/process/tools.py` schema/`_parse_arguments`/binding/preview 移除 expected_artifact（回 design §6 的 4 字段；`_render_preview` 去 ea 行）；`ResolveApproval` 加 `confirmed_artifact_path/sha256`（用户在批准 command 的同一 typed action 确认 digest）；`_admit_process_artifact_criterion` authority 改为 action 自带 confirmed_artifact（workspace-relative + 64-hex fail closed；candidate ea 字段保留为 runtime 内部、prepare 路径恒 None，checkpoint 兼容）。E3 侧：driver 在 J1 approval 携带 confirmed_artifact（input.txt digest）；scripted J1 provider 与 j1-j5 message 全部 4 字段（message 测试同步为 "The tool schema only accepts executable/argv/cwd/profile" + 禁止 `expected_artifact=` 指令）；`tests/architecture/test_015_governed_local_action.py` schema 断言回 4 字段合同（该测试此前锁定的正是 reviewer 判定违反 design §6 的第 5 字段）；`tests/process/test_j1_production_verified_done.py` 改用户确认流（candidate ea 恒 None 断言 + approval 携带 confirmed_artifact）。

**F7（receipt §8 完整绑定 + fixture_invocation_count 恒 0 矛盾）**：
- **Red**：`test_015_receipt_binds_section8_identity`（receipt 必含 delivery_seal_sha256/fixture_identity_digest/materialized_identity/reviewer_handoff + per-attempt started_at/ended_at/journey_verdicts/process_output_digests（stdout+stderr digest+truncation）/artifact_digest，secret-free）+ `test_015_fixture_invocation_count_recomputed_from_receipts`（scripted attempt 的 count 必须 == durable process receipt 总数且 > 0）——修复前分别 TypeError（新字段不存在）/ count==0 ≠ receipts。
- **Green**：`AttemptObservation` 加 §8 字段（started/ended、journey_verdicts、process_output_digests、artifact_digest、materialized_drive），全部由 `_compute_claims` 从 durable journey facts/admitted criteria 重算；`fixture_invocation_count = len(process_results)`（真实 process receipt 计数；`_record_fixture_invocation` 死代码不再参与）；`drive_attempt` 记墙钟 RFC3339（`_utc_now_iso`）；`write_receipt` 绑定 delivery seal digest（文件 digest，覆盖 code+materialized tree）、fixture identity digest（FIXTURE_SCRIPTS canonical digest）、in-attempt materialized identity、reviewer handoff `015-fresh-reviewer/v1` 与全部 per-attempt §8 字段。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、affected（harness/direct/process/kernel/015-architecture）`211 passed` 0（+4 新测试）、source pytest **`1024 passed`** 0（1020+4）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1024 passed** clean-room) 0；delivery seal 重生成。

**剩余 review findings（batch D 待做）**：F5（R11 CLI/TUI/headless lease view/revoke adapter——唯一剩余 P2）；P3 F9-F15（记录在案，reviewer 允许后续 milestone）。F5 闭合后重跑真实三连 + 重写 receipt + 交新 fresh reviewer。

### 3.39 review findings 修复 batch B：F3/F6/F8（P2）(2026-08-15)

**F3（preview §12.1 披露 + argv 无歧义）**：Red `test_015_preview_is_unambiguous_and_fully_disclosed`（修复前 argv 换行 token 伪造 `executable:` 行——与 reviewer 复现一致；`["rm","-rf","data"]` 与 `["rm -rf data"]` 渲染相同）。Green：`_render_preview` argv 逐 token JSON-quoting（literal、边界可分、换行/引号转义、不可注入）；新增披露行——真实 profile 数值 `timeout=<s>s`、stdout/stderr/combined caps、closed 环境 allowlist（不继承）、lease `8 uses / 60 minutes / revocable`。E3 claims 8/24 改为对**全部** `approval_previews` 校验（此前只查单个 j4 preview）：claim 8 = 每 preview 含 same-uid + timeout= + stdout/stderr cap + 8 uses + 60 minutes + revocable + environment；claim 24 = 每 preview same-uid + "not an os sandbox"。

**F6（lease 批准时锚点，R9）**：`ResolveApproval` 加 `approved_at: str | None`（带时区 RFC3339）；`_mint_process_authority_lease(approved_at=)` 以批准时刻为 lease `issued_at/expires_at`（审批等待不缩短租约）；`_require_zoned_rfc3339` naive/malformed fail closed（ValueError）。Red→Green `test_015_lease_expiry_anchored_at_approval_time`（candidate T0、T0+30 批准 → expires=T0+90 而非 T0+60；naive raises）——Red 阶段首跑因测试自身 helper 引用错误（NameError）失败，按合同重写为纯 reducer 版本后先绿；旧公式 `candidate.issued_at+60` 产生 T0+60 与断言 T0+90 不符即构造性 Red（如实记录）。approved_at 缺省 None 沿用 candidate.issued_at（012-014 非 process approval 兼容）。

**F8（claims 18/22/23/25 弱代理）**：claim 18 = crash 后 durable EXECUTING intent 真实存在（`j4_reopened_executing_intent` 非空，非"crash 发生过"）；claim 22 = 双类 criterion（`TOOL_RECEIPT` process + `FILESYSTEM_DIGEST` readback 各自 admitted，oracle_kind 检查，非 evidence≥2 数量代理）；claim 23 = truncation 标志 + stdout/stderr **digest** 可对账（product `_process_outcome` metadata 新增 `stdout_digest`/`stderr_digest`/`resource_profile` 投影——加式，legacy 键不变）；claim 25 = 每 receipt 的 `resource_profile` ∈ closed 集合且 `duration_seconds ≤ profile wall+grace bound`（非 outcome∈closed 集合的平凡真）。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、affected（harness/process/kernel-process/evidence）`70 passed` 0、source pytest **`1020 passed`** 0（1018+2：F3 preview + F6 approval-time）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1020 passed** clean-room) 0；delivery seal 重生成。

**剩余 review findings（batch C 待做）**：F4（expected_artifact schema 合同冲突——移除 model-facing 第 5 字段 + criterion 经 goal/admission seam）、F5（CLI/TUI/headless lease view/revoke adapter）、F7（receipt §8 完整字段 + `fixture_invocation_count` 恒 0 矛盾——`_record_fixture_invocation` 零调用点）；P3 F9-F15。闭合后重跑真实三连 + 重写 receipt + 新 fresh reviewer。

### 3.38 review findings 修复 batch A：F1/F2（P1）(2026-08-15)

Fresh reviewer 返回 `015_REVIEW_FINDINGS`（P1×2 + P2×6 + P3×7，不输出 REVIEW_PASS）。本批闭合两项 P1：

**F1（prepare→invoke 时钟竞态，产品级）**：
- **Red**：`test_015_prepare_invoke_across_second_boundary_executes`（`tests/process/test_tools.py`）——injectable clock 下 prepare 得 intent（T1），时钟拨到 T1+1s 再 invoke → 修复前 `IntentConflictError: tool safety preconditions changed after preparation`（确定性复现，与 reviewer 复现一致；即 §3.34 instrument 捕获的 8× IntentConflictError 与真实 E3 j4 假 unknown 的产品根因）。
- **Green（最小）**：`agent/process/tools.py` binding 移除 `"issued_at": now()`（binding 对同一 arguments **确定性**；`_default_clock`/datetime 导入随之成为 orphan 已删）；`agent/runtime/tools.py` `_build_process_candidate` 的 candidate 时钟改取 prepare 时刻 runtime `self._clock()`（candidate/lease 语义不变）。invoke 全等比较集不再含任何时钟字段——identity 字段（fingerprint/digests/profile/env policy/argv/cwd）全部保留比较。

**F2（claim 26 materialized 驱动名不符实）**：
- **Red**：`test_015_drive_attempt_observes_real_adapter_and_materialized_flags` 改为 flag 单独 → claim 26 必须 **False**（修复前 flag 单独即 True → Red）；新增 `test_015_materialized_drive_claim_requires_install_observation` mutation 矩阵（drive observation 缺失 / under_install False / gates flag False → 各自 False）。
- **Green**：`_prepare_materialized_drive()`——real E3 在 gates 后**真实 materialize overlay + non-editable install**（复用 verifier 的 derive_overlay/materialize_tree/install_noneditable），install site-packages 前置 sys.path 并清除已导入 agent 模块，fail-fast 验证 `agent.composition` 解析自 install；`drive_attempt(materialized_drive=...)` 在 attempt 内观察 composition 模块 origin；claim 26 = gates flag **AND** `composition_under_install`（in-attempt 观察）。实测子进程验证：install 下 composition 解析自 `/tmp/015-e3-mat-prefix-*/site-packages`，entry_count=184。offline scripted 基线诚实 25/26（claim 26 False，专门 mutation 测试覆盖）。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、affected suites（process/kernel/harness/direct）`197 passed` 0、source pytest **`1018 passed`** 0（1016+2）、materialized `--check-membership`(184) 0、`--control-seal` 0、`--content`(**1018 passed** clean-room) 0；delivery seal 重生成。

**剩余 review findings（后续批）**：P2 F3（preview §12.1 完整披露 + argv 无歧义渲染 + claim 8/24 全 preview 校验）、F4（expected_artifact schema 合同冲突）、F5（CLI/TUI lease 可见性/撤销）、F6（lease 批准时锚点）、F7（receipt §8 完整绑定 + fixture_invocation_count 恒 0 矛盾）、F8（claims 18/22/23/25 弱代理）；P3 F9-F15 记录在案。修复后须重跑真实三连 E3 并重写 receipt。

### 3.37 U10：真实三连 E3 accepted + 全 gates + truth 晋级 (2026-08-15)

supervisor 完成**真实 DeepSeek 三连 E3**：`openai_compatible` / DeepSeek 官方 endpoint /
`deepseek-v4-flash`，三个 fresh temp root 连续，**每 attempt 26/26 claims 全 true**（send 23/27/…
不等，durable facts 重算），生成 secret-free accepted receipt
`docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json`（3 attempts、destination digest、
无 key/header/body/env/path）。本回合（U10）：

1. **Receipt 核对**：3 attempts × 26 claims 全 true、`acceptance_status=accepted`、
   `contract_version=015-e3/v1`、provider/model/destination 与 supervisor 注入一致 ✓。
2. **Truth 晋级**：`docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3.md` frontmatter
   `evidence_status: pending → accepted` + §10 晋级记录（README 列入已交付仍待独立
   `015_REVIEW_PASS`）。
3. **完整未截断 gates**（真实 exit code，**最终 sealed 树**）：`git diff --check` 0、
   `ruff` 0、source pytest **`1016 passed`** 0、materialized `--check-membership`(**184**)
   0、`--content`(**1016 passed** clean-room) 0、`--control-seal` 0。
4. **Seal 重生成**：receipt + acceptance doc 进入 overlay（183 → **184 entries**），
   `overlay_root` 重算。注：seal 重生成前的一次后台 content 门报 drift（门运行中
   overlay 被本次编辑改变，旧 seal 对新树——预期时序），重生成后 membership/content/
   control-seal 三门在最终 sealed 树上全 Green。

**E3 修复链回顾（真实 E3 从全-false 到 26/26 的关键 Red→Green）**：§3.17 claims observation、
§3.20 提案-先 tool_choice、§3.24 exception-shape/blocker 准确化、§3.26 DeepSeek V4
thinking+tool_choice 兼容（thinking_mode=disabled）、§3.27/3.30 j1 提案-先+真实 sha256+tool_args
诊断、§3.31 j2 持续拒绝+禁 bogus expected_artifact、§3.33 oracle 证据加固 batch1（claims
3/5/6/7/14/15 + mutation）、§3.34/3.35 profile/deadline/pgid-ESRCH 加固、§3.36 j4 phase-1
recovery 证据蒸发修复。

**Codex 预审残余（移交 fresh reviewer）**：§9 claims 1/26 materialized 驱动与 §9 receipt 完整
绑定、§9 J4 user-stop typed 执行、§10 四项产品级最小复现（裸 grant/preview 完整性/cwd
identity/lease 时钟）、§10 相邻合同（executable 上限/argv limits/draft 校验/完整 receipt fact
持久化）、§11 lifecycle（CLI/TUI revoke adapter、expected_artifact schema 合同冲突、R9
approval-time 租约、checkpoint schema v4 migration、ToolSpec 显式 authority 投影）。这些
findings 在真实三连后仍开放，属 fresh reviewer 审计范围。

**Marker**：U1-U9、真实三连、offline/materialized gates 全闭合 → 输出
`015_EXECUTOR_READY_FOR_REVIEW`。

### 3.36 j4 phase-1 recovery 静默证据蒸发修复（真实 E3 7-false 主根因）(2026-08-15)

真实 E3 再进一步（j1/j2/j5 全 `verified_done`、j3 `timed_out_reaped`、j5 元字符/env-keys 双 receipt 达成），仅剩 7 false。**主根因**：FAIL_DETAIL 显示 `response_shapes.j4` 空 + `runtime_identity` 无 j4 + `j4_crash_happened` 键缺失（连诚实 False 都没有）→ j4 crash journey **静默早退并丢失全部 observation** → `single_runtime_loop_preserved`（identity 缺 j4）+ j4 4 claims（crash/executing/restart/unknown-recovery）连锁崩。

**代码缺陷**：`_drive_j4_crash_journey` phase-1 循环只处理 DISCLOSURE/APPROVAL/SimulatedHostCrash——真实 model 的 invoke 抛**普通 Exception**（实测签名：`IntentConflictError: tool safety preconditions changed after preparation`，§3.34 instrument 曾 8× 捕获）→ runtime 既有 recovery 路径 → phase-1 不认识 AWAITING_RECOVERY → `else: break` 早退 → 无 shapes/identity/crash-flag（break 跳过 while-else，`j4_crash_happened` 从未赋值）。

**Red→Green**：`test_015_j4_phase1_recovery_does_not_lose_observations`（Red 确认：monkeypatch `build_tool_registrations` 使首个 local_process invoke 抛普通 ValueError → recovery → 断言 `j4_crash_happened`/`response_shapes["j4"]`/`runtime_identity["j4"]` 必须被记录——修复前 "j4 crash flag must always be recorded, not silently dropped" 失败）。Green：(a) phase-1 加 AWAITING_RECOVERY 分支（MARK_FAILED + continue——模型可重试 local_process 走真实 crash 路径）；(b) 早退路径（含 unhandled status，现在记录 `j4_unhandled_phase1_status` 供诊断）必记 identity/shapes/诚实 False flag。**不放宽 frozen journey**：crash 未发生时相关 claims 仍由 durable facts 诚实计算为 False——修复的是证据蒸发，不是 claim 结果。

次要点（本 FAIL_DETAIL 另 2 false）：`approval_preview_exact_and_informed`/`no_false_sandbox_claim` 只见过 1 个 preview（6 approvals 中 harness 只保留最后/首个——需记录全部 preview 的 exact/notices）；`exact_reuse_without_reapproval` 真实 model 仍只 1 exact receipt（message 已 MUST，模型行为漂移持续）。归入 Codex 预审后续批。

**诚实披露**：本轮 full pytest 首跑 1 failed（flags test，SimulatedHostCrash 于 j4 首个 run_turn 逃逸）——单独/组合/整 suite 复跑共 3 次均 Green（`1016 passed`），未复现；按已知 load-flake 家族记录，若再现按 §3.29 可见性抓名。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness+direct `24 passed` 0（+1 新测试）、source pytest **`1016 passed`** 0（1015+1）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1016 passed** clean-room) 0；delivery seal 重生成。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.35 pgid-ESRCH race 修复（Codex §11.4 点名行）+ flake 根因链完整记录 (2026-08-15)

§3.34 后 content 门本机又点名 `test_015_e3_drive_attempt_runs_real_local_process`。负载复现 + 逐层 instrument（wrap invoke/loop 记录函数/pause_for_recovery 栈/最终 invoke 异常捕获）定位**完整根因链**：

1. **pgid-ESRCH race（主因，Codex §11.4 独立点名的行）**：超快进程（cat/echo fixture）在 `Popen` 与 `_verified_pgid` 之间退出 → `getpgid` ESRCH → `ProcessCleanupError` → invoke 抛 → unknown → MARK_FAILED → j1 无 receipt/无 artifact criterion。**实测捕获**：`INVOKE-RAISE ProcessCleanupError: cannot verify process group identity ... No such process` ×3。
2. **j1 write-artifact short(10s) 负载超时**（§3.34 已修：非 timeout journey → standard）。
3. **post-KILL 验证循环缺 leader 收尸**（§3.34 已修：循环内机会性 `proc.wait(0.1)`，预算保持 30 次不变——bounded-cleanup 合同测试 `<10s` 不放宽）。

**Red→Green（`agent/process/runner.py`）**：`test_runner_fast_exit_before_pgid_probe_is_exited`（Red：monkeypatch getpgid→ESRCH → 修复前 ProcessCleanupError）+ `test_runner_pgid_probe_denied_still_fail_closed`（EPERM 仍 fail-closed，修复前已 Green）。Green：(a) `_verified_pgid` ESRCH→`None`（已退出的 leader 无可治理 group——诚实 drain+reap+按 exit code 分类；`_group_alive(None)`=False、`_signal_group` 单进程回退是既有建模）；(b) pgid probe 移入 try/finally 内（Codex §11.4：probe 失败不得遗留 child/pipe——finally `_reap`+close 兜底）；(c) EPERM/identity mismatch 仍 fail-closed。

**过程纪律记录**：stress 循环多次被 10min 工具超时打断，`yes` spinners 累积最高 107 个（load 210）——已按精确 PID 全部 SIGKILL 清理（remaining=0）；中断期间的部分 flake 数据是在极端饱和下测得、被高估；`pgid-ESRCH` 修复有确定性 Red 支撑、与负载无关。

**残余（诚实披露）**：本机仍有他方 session 负载（1-min load 13-80），无人工负载 12 次 stress 仍有 3 次 j3 timeout claims False（hang-tree 10s deadline + TERM-trap + cleanup 确认是 inherently 最 timing-sensitive 的 frozen journey；真实 E3 历史也翻转过）。j3 的 receipt 依赖 confirmed cleanup，负载下诚实进 unknown——**这是设计行为，非 bug**；若 supervisor 慢机器持续命中，需评估 j3 cleanup 等待预算（受 bounded-cleanup `<10s` 合同约束）或负载缓解。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、`tests/process/` `29 passed` 0（+2 新测试）、source pytest **`1015 passed`** 0（1013+2）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1015 passed** clean-room) 0；delivery seal 重生成（runner.py 是 overlay 产品代码）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.34 修复两个点名 content-gate flake（j1 short-profile 负载超时 + subagent deadline）(2026-08-15)

supervisor content 门 exit 1，§3.28/3.29 诊断首次**精确报出两个失败测试名**：`test_015_claims_real_evidence_and_mutation` + `tests/subagent/test_process_runner.py::test_process_runner_terminated_on_completion`。

**flake 1（mutation baseline，本机复现于 6×CPU 负载下）**：j1 `write-artifact`（shell `cat input.txt > artifact.out`）在 `short` profile（10s deadline）下负载偶发超时 → `timed_out_reaped` → 不满足 exit 0 → 无 process-artifact criterion → claim 22 False。诊断消息证实 j2 fingerprints 正常（2×same）。**修复**：非 timeout journey（j1 write-artifact、j2 count-run、j4 count-run、j5 echo-argv/print-env-keys）scripted provider + message 全部 `short→standard`（120s deadline）——这些 journey 验证的是 artifact/lease/env 合同，不是 deadline；**j3 hang-tree 保持 `short`**（acceptance §5 明确 pin 的 timeout journey，批量替换误改后已恢复并注释锁定）。负载 6 连跑全 Green。

**flake 2（subagent runner）**：`test_process_runner_terminated_on_completion` 等正常完成路径用 `hard_deadline_seconds=20.0`——慢机器上 Python child 启动 + agent import 偶发超 20s → kill → UNCONFIRMED → 断言 TERMINATED 失败。**修复**：正常完成路径 5 处 `20.0→120.0`（deadline-kill 确定性测试 `0.5s + sleep 5s` 不动，合同不变——仅 test 等待参数）。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness+direct `23 passed` 0（负载 6 连跑稳定）、`tests/subagent/` `27 passed` 0、source pytest **`1013 passed`** 0、materialized `--check-membership`(183) 0、`--control-seal` 0；delivery seal 重生成（run_015_e3.py profile 变更）。materialized `--content` 后台运行中。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。Codex 预审 batch 2（J4 stop、claims 1/8/9/18/20/22/23/25、materialized 驱动、receipt §8、§10 产品级四项最小复现、§11 lifecycle）仍为后续门。

### 3.33 E3 oracle 证据加固 batch 1：claims 3/5/6/7/14/15 + mutation tests (2026-08-15)

背景：真实 E3 已达 **25/26**（§3.31 后的最新 FAIL_DETAIL：j1/j2/j5 全 `verified_done`、j3 `timed_out_reaped`、j4 完美；唯一 false = `exact_reuse_without_reapproval`——模型该轮只调 1 次 exact count-run，模型行为漂移，j2 message 已加 "you MUST call the EXACT SAME command a second time"）。同时 **Codex 预审列出 9 类 stop-ship 证据缺口**，本批先闭合可完整 Red→Green 的 6 条 claim：

**Red**：`test_015_claims_real_evidence_and_mutation`——基线必须 26/26（含收紧证据），且每个 mutation 令对应 claim False。修复前 `AttributeError: raw_observed` 不存在 → Red。

**Green（scripts/run_015_e3.py）**：
- **claim 3**：`runtime_identity` observation——每 journey 记录 `{type, distinct}`（driver 每次 run_turn 收集 `id(composition.runtime)`，非 `run_id==run_id` 恒真）；j4 crash/restart 两 composition 记 type 一致 + distinct=2（frozen 设计）。claim = 5 journeys 全 `AgentRuntime`、非 restart journey distinct==1。
- **claims 5/6/7**：`pre_first_approval` 快照——**首个 approval 时刻**记录 `goal_present`/`process_receipts`/`fixture_side_effects`（count-run counter 与 artifact.out 均未产生）。claim5 = goal 在首 approval 前 durable + 全 receipt 带 authority；claim6 = approvals>0 且 pre receipts==0；claim7 = 且 side_effects==0。
- **claim 14**：J5 echo-argv 输出按 NUL 分割与 `_J5_LITERAL_TOKENS`（frozen 完整**有序**列表）**精确相等**，非任一 metachar 命中。
- **claim 15**：J5 scripted provider + message 增加 **print-env-keys** 真实执行；`SYNTHETIC_CANARY_ENV`（repo 常量，非秘密）注入 runner 进程 env；claim = 存在 env-key 输出 ∧ canary key 不在其中 ∧ canary value 不在任何 process 输出 ∧ secret_hits 空（非「从未填充」空证据）。
- `AttemptObservation.raw_observed`（仅内存，mutation 测试用）；`_secret_free_diagnostic` 加 pre_first_approval/runtime_identity。

**mutation tests（Codex 要求）**：删除 runtime_identity / 篡改 type → claim3 False；goal_present=False → claim5；pre receipts=1 → claim6/7；side_effects=1 → claim7；token 顺序错/不完整 → claim14；canary key/value 泄入输出 → claim15。observed 含 frozen JSON 不可整体 deepcopy——浅拷贝+局部复制被触碰键。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness `22 passed` 0（mutation 测试 3 连跑稳定）、source pytest **`1013 passed`** 0（1012+1）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1013 passed** clean-room) 0；delivery seal 重生成。

**剩余 Codex 预审缺口（后续批，非本批）**：claim 8/9/18/20/22/23/25 完整合同；J4 user stop（runtime 无 STOP resolution，需查 cancel/pause 路径并执行）；claim 1/26 materialized install 驱动（caller flag 不冒充）；write_receipt E3 §8 完整绑定；其余 claims 的 mutation tests。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.32 real E3 transport 失败：底层 cause 类型捕获 (2026-08-14)

supervisor 真实 E3 全新故障模式：**所有 5 个 journey 首个 send 即 `ProviderTransportError`**（reason 仅 "provider_transport"，无细节；send_count=5；上一轮 §3.31 send_count=31 正常、零产品/provider 配置变更）→ **环境级网络故障**（DeepSeek 服务 / 出口 / 连接层），非产品回归。blocker `model_endpoint`（§3.24 映射正确）。

**诊断缺口**：`openai_http.py` 用 `raise ... from None` 是 deliberate contract（`tests/provider` 锁定 `__cause__ is None`——provider 封闭错误分类不泄漏 httpx 内部），不可改链式。但 `from None` 仍保留 `__context__`。

**Red→Green（纯 runner 侧，零 production 改动）**：`test_015_transport_error_cause_is_captured`（Red：`KeyError: 'cause'`；production adapter + recording transport raise `httpx.ConnectError`）→ `_CountingProvider` 异常捕获加 `cause`：从 `__cause__`/`__context__` 取底层 cause **类型名**（ConnectError/ConnectTimeout/ReadError/TlsError 等，不含 URL/message，secret-free）——下次真实 E3 可区分 connect refused / DNS / TLS / reset，即 DeepSeek 服务问题 vs 出口问题。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness+direct `22 passed` 0、source pytest **`1012 passed`** 0（1011+1）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1012 passed** clean-room) 0；delivery seal 重生成。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。transport 失败本身是 supervisor 侧服务/网络状态（§3.31 的 24/26 产品状态未回退——本轮是网络层故障，产品代码自上轮零变更）。

### 3.31 real E3 24/26：j1 VERIFIED_DONE 达成 + j2 持续拒绝 + 禁 bogus expected_artifact (2026-08-14)

§3.30 修复生效：真实 E3 **j1 `verified_done` + 2 evidence**（`artifact_requires_process_and_readback_evidence` True——提案-先 + message 真实 digest 全链路工作）、**j5 `shell_metacharacters_literal` True**（tool_args 显示模型精确传 `["a;b","|c","$d","`e`","f>g"]`）。j3 上一轮 True、本轮 False（模型行为漂移，见下）。剩余 false 3 条，两新根因均由 tool_args 数据定位：

1. **`rejected_command_zero_spawn`（j2）**：模型给 count-run 加 bogus `expected_artifact`（全零 sha256），changed-argv 命令被拒后**重试**——driver 只拒 `approval_index==2`，第 3 个 approval 又被批准 → rejected fingerprint 被 spawn → claim 13 False。**根因是 driver 缺陷**：frozen journey 定义用户行为（拒绝过的命令永不执行），模型重试不改变用户决定。
2. **j3 timeout×2 False**：模型给 hang-tree 加 `expected_artifact={path:"", sha256:空内容哈希}` → 空 path 被 admission **正确 fail-closed** 拒绝（tools.py:250 "path must be non-empty"）→ 无 approval/无 spawn → 无 `timed_out_reaped` receipt。j5 同样先发空 path 无效调用（浪费 turns）。j2 全零 sha256 还改变 command fingerprint。

**Red→Green**：
- `test_015_j2_driver_keeps_rejecting_rejected_fingerprint`（Red 确认：retry 后 rejected fingerprint 出现在 receipts）→ `_drive_journey` 加 `_rejected_fingerprints` 集合：J2 中已拒 fingerprint 的后续 approval **持续拒绝**（不改 offline scripted 行为——scripted 不重试）。
- `test_015_journey_messages_exclude_expected_artifact_for_non_artifact_journeys`（Red 确认）→ j2/j3/j4/j5 message 显式 "Do not include expected_artifact"（仅 artifact 产出命令使用；空 path/伪 sha256 被拒）；j2 加 "If the user rejects this command, do not send it again."。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness+direct `21 passed` 0、source pytest **`1011 passed`** 0（1009+2）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1011 passed** clean-room) 0；delivery seal 重生成。

下次真实 E3 预期：j2 retry 持续被拒（claim 13 True）；j3 无 bogus expected_artifact → hang-tree 正常超时（timeout claims True）。j1/j5 已 True。模型行为仍有漂移空间（j3 上轮 True 本轮 False），response_shapes/tool_args 持续提供定位。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.30 real E3 24/26：j1 提案-先 + 真实 sha256 + tool_args 捕获 (2026-08-14)

§3.29 后 supervisor 真实 E3 推进到 **24/26**（false_claims 仅 `shell_metacharacters_literal` + `artifact_requires_process_and_readback_evidence`；j3 timeout 两 claim 已 True：`j3_outcome=timed_out_reaped`+1 receipt；j4 crash/restart 完美：pre=5/recovery=4/post=0/awaiting_recovery）。blocker 仍 `product_invalid_model_output`（`ProviderProtocolError reason=malformed_control`，j1×3 + j2×1；j2 单次自恢复）。

**j1 根因链（response_shapes 实测 + 代码确认）**：模型按旧 message「step1 先读 input.txt」→ read_file 后 `source_result_since_latest_user=True` → `goal_proposal_is_available=False`（context.py:187）→ strict decoder anyOf 变体**不含 goal_proposal**（context_control.py:313-320 按 availability 过滤）→ 模型坚持提案 → `malformed_control`×3，j1 永不建 goal。j2/j3/j4/j5 turn-1 提案全部成功。**第二障碍**：claim 22 需 `expected_artifact.sha256`＝纯 `sha256(content)`（evidence.py:518 oracle），但 LLM 无法计算 sha256，read_file metadata 的 `snapshot_digest` 是**复合** digest（path+stat+content，path_safety.py:239），不匹配 oracle。

**Red→Green（runner 侧最小，不放宽/不伪造）**：
- `test_015_j1_message_proposes_goal_first_and_provides_digest`（Red：旧 j1 message「1. Read input.txt」在前 + `<sha256...>` 占位符）→ 新 `_journey_messages(fixtures)`：j1 step1 提案（显式 "FIRST, before any file reads"）、step2 读 + 提供 input.txt 真实 content digest、step3 expected_artifact 用同一 digest。runtime 仍在 CompletionClaim 从 durable read_file fact **重算** sha256 验证——runner 只提供模型无法计算的 fingerprint，不伪造 evidence。j5 message 加 "Pass these tokens EXACTLY as written"。
- `test_015_response_shape_captures_tool_arguments`（Red：shape 无 tool_args）→ `_response_shape` 捕获白名单参数（executable/argv/cwd/profile/path/expected_artifact，fixture 路径/token，secret-free）——j5 本轮 0 receipts + goal blocked、approvals=3（少 1），下次 FAIL_DETAIL 将显示 j5 模型实际发送的 argv，可精确定位为何未 spawn。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、harness+direct-script `19 passed` 0、source pytest **`1009 passed`** 0（1007+2）、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1009 passed** clean-room) 0；delivery seal 重生成（run_015_e3.py/test_harness 变更，overlay_root 重算）。

下次真实 E3 预期：j1 提案-先（GoalProposal turn-1 可用）+ 真实 digest → j1 全 journey 驱动 → `artifact_requires_process_and_readback_evidence` 可达；j5 据 tool_args 定位。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.29 offline 门失败测试名可见性（source pytest flake）(2026-08-14)

supervisor 报 `offline_gate_failed`：**source pytest** exit 1（`1 failed, 1006 passed`，总 1007 = 当前树），但 runner `_run` 只显示子进程最后一行（pytest 裸 summary "1 failed, 1006 passed"），**失败测试名不可见**——与 §3.28 content 门同款截断问题，这次命中 source pytest 门。本机 source pytest 连续多轮全 Green（含 -ra 复跑 `1007 passed`）→ supervisor 机器上单个 timing-sensitive 测试 flake（总耗时 151s 并不慢，是特定测试的竞态/超时窗口）。

**Green（最小，诊断可见性，不改任何测试/断言）**：
1. `offline_gates_green` 的 source pytest argv 加 **`-ra`**（失败测试产生 `FAILED <node>` summary 行）。
2. `_run` 失败时提取 `FAILED` 行 / verifier 的 `015_CONTENT_FAILED_TESTS` 行作为显示 tail（替代裸 summary）——supervisor 截断展示只保留 `-> ` 一行，此前两次 offline_gate_failed（content 门 §3.28、本次 source pytest）都因此看不到测试名。
3. 本地 probe 验证：对故意失败的微型 pytest 跑 `_run`，输出 `exit 1 -> FAILED .../test_failname_probe.py::test_probe_boom - ...`（测试名可见）✓。

下次 supervisor 任一 offline 门失败，`-> ` 行将直接含失败测试 node ID → 精确 Red/Green 修复（而非对 timing 测试盲改）。§3.28 的 MCP timeout 加固（test_integration/test_session）保持；`test_session_behavior.py` 的 deliberate 短 timeout 测试（`call=0.6/1.2` 等）是竞态最敏感候选，但**无名字不盲改**。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、source pytest（-q -rx -ra）**`1007 passed`** 0、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1007 passed** clean-room) 0；delivery seal 重生成（run_015_e3.py 内容变更，overlay_root 重算）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.28 content 门 MCP 子进程 timeout 加固 + FAILED_TESTS 行移至输出末尾 (2026-08-14)

supervisor 报 `offline_gate_failed`：materialized `--content` exit 1（**1 failed, 1006 passed**），supervisor 截断展示仅显示最后一行（pytest summary），`015_CONTENT_FAILED_TESTS` 行（§3.23 已加）被截断不可见。本机 content 门 8+ 次全 Green（load 7-12 与 load 50+ 均过）→ 失败是 supervisor 更慢机器下 timeout-based 子进程测试的 timing flake（§3.22 同签名：MCP `session_failure`/`TaskGroup`，spawn 真实 MCP server 子进程 + asyncio）。

**Green（最小，两处）**：
1. `scripts/verify_015_materialized_tree.py`：`015_CONTENT_FAILED_TESTS` 行移到 `_report` 列表**最后**（pytest tail 之后）——supervisor `-> ` 只显示最后一行，放最后确保任何截断下失败测试 node ID 可见，下次失败可精确定位（而非猜测）。
2. MCP normal-path 子进程测试 timeout 提升至慢机器容忍值（**仅 test 等待参数，断言完全不变，非放宽**）：`tests/mcp/test_integration.py` + `tests/mcp/test_session.py` 的 `SessionTimeouts(initialize=10→30, ...)`、`McpAsyncBridge(total_timeout_seconds=40→120)`。**未触碰** `test_session_behavior.py`/`test_bridge.py`（含 deliberate 短 timeout 测试：`call=0.6/1.2/1.5`、`total=2.0/0.1` 等，这些是超时行为合同，不可改）。

**overlay 182→183 说明**：regen seal 时 `entry_count` 182→183。已扫描全部 183 条 overlay 路径：无 `__pycache__`/`.pyc`/`.pytest_cache`/`.ruff_cache`/`tui/`/`memory/`/非白名单前缀条目（全部在 agent/tests/docs/scripts/root 白名单内）；membership(183) + control-seal exit 0。+1 为合法产品/测试/文档路径，content 门端到端验证。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、`tests/mcp/` `59 passed` 0、source pytest **`1007 passed`** 0、materialized `--check-membership`(183) 0、`--control-seal` 0、`--content`(**1007 passed** clean-room) 0；delivery seal 重生成（overlay_root 重算）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.27 real E3 23/26 分析 + j1 ProviderProtocolError reason 捕获 (2026-08-14)

§3.26 thinking_mode="disabled" 修复生效后，supervisor 真实 E3 从全-false 推进到 **23/26**，blocker 准确为 `product_invalid_model_output`（j1 ProviderProtocolError）。response_shapes 揭示：

- **j2/j4 完全工作**（GoalProposal→local_process→…；j4 crash/restart 正确：pre_crash_send=6/post_restart_send=0/post_restart_status=awaiting_recovery）。
- **j1**：`read_file`（无 control，turn 1）→ `ProviderProtocolError` ×3 → goal_status=null → `artifact_requires_process_and_readback_evidence` false。j1 是唯一「读-先」journey（j2/j3/j4/j5 都 turn-1 提案成功）。
- **j3**：GoalProposal→local_process→BlockedClaim，**0 process_receipts**（hang-tree 未产生 timed_out_reaped）→ `timeout_group_cleanup_confirmed`/`timeout_not_verified_done` false。
- **j5**：GoalProposal→local_process→CompletionClaim→BlockedClaim → `shell_metacharacters_literal` false（echo-argv 未捕获精确元字符 argv）。

**j1 分析**：j1 message 让 model「先读 input.txt」，但 `source_result_since_latest_user` 使读后 `goal_proposal_is_available=False`（context.py:187）→ model 强行提案 → ProviderProtocolError（malformed_control）。**更深**：claim 22 需 model 提供 `expected_artifact.sha256`，但 LLM 无法计算 sha256 → 即便修复提案顺序，claim 22 仍受此模型能力限制。

**本回合 Green（诊断，不放宽）**：`_CountingProvider` 异常捕获加 `reason`（`" ".join(str(exc).split())[:160]`，normalize/protocol 的 secret-free 错误码/字段名，不含 key/content）。下次真实 E3 的 j1 exception 将含具体 malformed 原因（如 `malformed_control` / 缺字段 / control 不可用），据此精确修复（j1 message 提案-先 + 可能需在 message 提供 sha256 让 model 复制——属 journey-runtime 交互调整，非伪造：model 仍驱动 propose/local_process/readback/CompletionClaim，sha256 是 model 无法计算的既定 fingerprint）。

j3（timeout 流程）/j5（精确元字符 argv）是模型行为依赖，待 j1 修复后据 response_shapes 评估。

**验证**（真实未截断 exit code）：`git diff --check` 0、`ruff` 0、source pytest **`1007 passed`** 0、materialized `--check-membership`(182) 0、`--control-seal` 0、`--content`(**1007 passed** clean-room) 0；delivery seal 重生成。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.26 real E3 精确根因：DeepSeek V4 thinking+tool_choice 不兼容 (2026-08-14)

§3.24 的 exception-shape 诊断部署 + §3.25 key 外部替换后，Codex 用 production `OpenAICompatibleProvider` + 完全合成 ContextPack 做**外部 A/B 复现**（不含仓库内容）：

- 当前 `real_provider_factory`：`thinking_mode=None`（DeepSeek V4 默认思考）+ `strict_tools=True`（发 `tool_choice="required"`）→ **稳定 `ProviderHTTPError status=400`**。
- 仅设 `thinking_mode="disabled"`（其余请求条件不变）→ **HTTP 200 + normalize 为合法 `GoalProposal`**。
- DeepSeek 官方兼容说明：**V4 thinking mode 不接受 `tool_choice`**。

这是 **provider-compatibility 缺口**，不是 key/endpoint/服务故障，也不是 §3.20「model 发 prose」假设（那是错的；真实是 adapter 抛 400）。§3.24 的 blocker 映射会把 `ProviderHTTPError`→`model_endpoint`，但真实原因是 E3 composition 的 strict-control 配置与 DeepSeek V4 thinking 不兼容。

**Red**：`test_015_real_e3_adapter_disables_thinking_for_strict_tool_choice`——production adapter + recording transport，`control_schema` present 时 request 必同时含 `tool_choice="required"`（strict 保留，**不放宽**）与 `thinking={"type":"disabled"}`（兼容）。修复前 `thinking=None` → assert fail。

**Green（最小，provider-compat 配置）**：`real_provider_factory` 的 `AgentProviderConfig` 加 `thinking_mode=("disabled" if provider=="openai_compatible" else None)`。`config.py` 仅 openai_compatible 支持 `thinking_mode="disabled"`（line 59-62）。**未放宽 strict tools、未移除 tool_choice、未创建第二 adapter/loop**——仅显式 disable thinking 覆盖 DeepSeek V4 默认，使 strict tool_choice 兼容。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` exit 0；source pytest **`1007 passed` exit 0**（1006 + 1 thinking-compat 测试）；materialized `--check-membership`(182) 0、`--control-seal` 0、`--content`(**1007 passed** clean-room) 0；delivery seal 重生成（run_015_e3.py 内容变更，overlay_root 重算）。

下次真实 E3（新 key + thinking disabled + strict tool_choice）：request 与 DeepSeek V4 兼容 → 应越过 400；response_shapes 将含真实 model 的 control/tool/text shape。以 secret-free shape/blocker 继续至真实三连 receipt。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.25 real E3 根因确认：ProviderAuthError（auth 外部）+ key 已外部替换 (2026-08-14)

§3.24 的 exception-shape 诊断部署后，supervisor 真实 E3 的 blocker 准确定位为 **`ProviderAuthError`**——即真实 adapter 抛 auth 异常（key 问题），supervisor 合法停止。这**不是** code/contract 问题：counting seam、strict control channel、typed control、journey 编排均正确；失败纯粹是 E3 注入的 key 无效。

**外部修正（repo 外，Codex）**：替换 DeepSeek key；用官方 OpenAI-compatible endpoint `https://api.deepseek.com/chat/completions` + `deepseek-v4-flash` 做不含仓库内容的最小探测，得 HTTP 200 且有效 choice。不读取/讨论 key value。

**本回合（verify-only）**：核对 tree+seal 未再变化——git status 仅同样的 015 untracked 文件（无新改动），`git diff --check` 0、`ruff` Green、materialized `--check-membership`(182) 0、`--control-seal` 0（seal 一致）。source/materialized 维持 §3.24 的 `1006 passed`（代码未变，无需重跑重门）。offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 重新输出 `NEEDS_015_E3_CONFIG(...)`，让 supervisor 用已验证配置（新 key + 官方 endpoint）重跑真实 E3。

**后续**：真实 E3 经新 key 应越过 auth；下次 `FAIL_DETAIL` 的 response_shapes 将含真实 model 的 control/tool/text shape（而非 exception），blocker 准确化（§3.24 `_derive_blocker`）继续指向真实剩余问题（若 model 发 prose/malformed control → product_no_progress/product_invalid_model_control；若 journey 完成 → receipt）。以 secret-free response shape/blocker 为准确 Red，继续至真实三连 receipt、U10 gates、fresh reviewer。

### 3.24 real E3 根因修正：adapter 调用抛异常（非 prose）+ blocker 准确化 (2026-08-14)

§3.21 的 response-shape 诊断部署后，supervisor `FAIL_DETAIL` 显示：`send_count=5` 但 **`response_shapes` 全空**（`{"j1":[],"j2":[],"j3":[],"j5":[]}`，j4 缺失）。

**关键推理（推翻 §3.20 "model 发 prose" 假设）**：`_CountingProvider.generate` 中 `send_count += 1` 在 `delegate.generate` 之前，`response_shapes.append` 在之后。send_count=5（5 次 generate）但 response_shapes 空 → **`delegate.generate` 在 append 之前就 raise 了**——即**真实 adapter 每次 model 调用都抛异常**（ProviderHTTPError/AuthError/ProtocolError/Timeout 等），而非发 prose。runtime 捕获异常 → run 终止 → 无 goal → 此前误标 `product_no_progress`。§3.20 的 proposal-turn tool_choice 修复基于错误假设（prose），故未生效；真实问题是 adapter/API 层错误。

**Green（诊断 + blocker 准确化，不放宽 control）**：
- `_CountingProvider.generate`：用 `try/except` 包住 `delegate.generate`，捕获时把 `{"control":"exception","error_type": <类名>}`（secret-free，仅类名）写入 response_shapes 再**原样抛**（行为不变，runtime 仍捕获）。
- `_derive_blocker(attempt)`：从 response_shapes 的异常 error_type 映射到 acceptance §9 准确 reason——`ProviderAuthError→model_auth`、`ProviderHTTPError/HTTPRetryableError/TransportError/ConfigurationError→model_endpoint`、`ProviderTimeoutError→timeout`、`ProviderProtocolError→product_invalid_model_output`；未知/无异常仍 `product_no_progress`（不放宽）。
- `drive_three_consecutive` 失败 blocker 从硬编码 `product_no_progress` 改为 `_derive_blocker(attempt)`。

下次真实 E3：response_shapes 将含 error_type，blocker 将是准确 reason（如 `model_endpoint`/`model_auth`/`timeout`/`product_invalid_model_output`），直接揭示是 API/model/auth 错误还是 protocol/超时——据此做最终 Red/Green。新增 `test_015_counting_provider_records_exception_and_derives_blocker` 锁定捕获+映射行为。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` exit 0；source pytest **`1006 passed` exit 0**（1005 + 1 exception/blocker 测试）；materialized `--check-membership`(182) 0、`--control-seal` 0、`--content`(**1006 passed** clean-room) 0；delivery seal 重生成（run_015_e3.py 内容变更，overlay_root 重算）。

**Marker**：offline/E2M 全绿（本机）+ 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.23 content 门失败诊断：verifier 醒目输出失败测试名 (2026-08-14)

supervisor 多次报 `materialized --content: exit 1, 1 failed, 1004 passed`（一致，非单次暂态），但展示仅 summary 行，**看不到失败测试名**。本机 content 门连跑 6+ 次全 `1005 passed`（含 load 50+ 时），mcp/subagent/process source 连跑 3x `113 passed`——本机不复现。结论：失败是 supervisor 更慢机器下 timeout-based 子进程测试（MCP `session_failure`/TaskGroup 签名）确定超时；本机更快，即使重载也不超时，无法按需复现。

**Green（诊断透明，不放宽任何检查）**：`scripts/verify_015_materialized_tree.py` 的 `run_content_gate`：(1) pytest 加 `-ra`（产生 FAILED summary 行）；(2) 失败时解析输出中 `FAILED` 行，打到醒目独立行 `015_CONTENT_FAILED_TESTS: <node IDs | ...>`（在 pytest tail 之前），即便 supervisor 展示截断也能看到具体失败测试名。`_report` 以 `FAIL:` 前缀打到 stderr。

下次 supervisor content 门若再失败，输出必含 `015_CONTENT_FAILED_TESTS: tests/...::...`，据此做精确 Red/Green（而非猜测 MCP/process）。本机验证：verifier import OK、content 门 `1005 passed` exit 0（改动不破坏 pass 路径）、control-seal exit 0（verifier_sha256 重算，overlay_root 不变——verifier 是 control path）。

**未做猜测性测试改动**：不修改无法复现、无法验证的 non-015 测试（§11）。已知签名指向 MCP `session_failure`/TaskGroup（`tests/mcp/test_integration.py` spawn 真实 MCP server 子进程 + asyncio + `SessionTimeouts(initialize=10,...)` / `total_timeout_seconds=40`），待 `015_CONTENT_FAILED_TESTS` 确认后再精确修。

**Marker**：offline/E2M 全绿（本机）+ 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.22 materialized --content transient flake 调查（无法本地复现）(2026-08-14)

supervisor 报 `015_E3_BLOCKED(offline_gate_failed): materialized --content exit 1, 1 failed, 1004 passed` → E3 未运行。source pytest `1005 passed`、source 下 `tests/mcp/ tests/subagent/ tests/process/` 连跑 3x `113 passed`。本机 materialized `--content` 连跑 **4 次全 exit 0（1005 passed）**（本会话累计 6+ 次 content 门全 Green）。

**结论**：失败是 transient、load-dependent、sandbox 专属的子进程/timing flake（已知签名：MCP `session_failure` / `TaskGroup`，`tests/mcp/test_integration.py` 经 spawn 真实 MCP server 子进程 + asyncio + timeouts）。本机 load 7-12 时不触发；先前 load average ~50（用户其他 session 活跃）时偶发 1-2 failed——与 fact #6 记录的 materialized/content 暂态失败一致。我**无法按需复现**（load 来自用户其他 session，不可控），故无法取得具体失败测试名 + 堆栈，无法建经验证的 Red/fix。

**未做猜测性改动**：不修改无法复现、无法验证的 non-015 测试（违反 §11：不得无证据声称修复）。fact #6 明确 supervisor 的 offline_gate_failed 处理逻辑（重跑 transient materialized 失败）已在 repo 外修正——supervisor 应重跑。

**当前 offline 门状态（本机，真实未截断 exit code）**：`git diff --check` 0、`ruff` 0、source pytest `1005 passed` 0、materialized `--check-membership`(182) 0、`--content`(`1005 passed` clean-room，4 连跑) 0、`--control-seal` 0。response-shape 诊断（§3.21）已落地。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。若 supervisor 侧 content 门仍因 transient flake 失败，需 supervisor 按其重跑逻辑（fact #6）处理。

### 3.21 real E3 诊断扩展：response shape（model 实际发什么）(2026-08-14)

§3.20 proposal-turn `tool_choice="required"` 修复后，supervisor 重跑真实 DeepSeek E3，`015_E3_FAIL_DETAIL` **仍**为 `send_count=5`、5 journey 全 `goal_status=null`、`approvals=0`、`process_receipts=0`。即强制 tool_choice 后 model 仍未构造 GoalProposal。§3.19 诊断只记 goal/receipt/evidence（结果），**未记 model 每 turn 实际发什么**（原因），无法区分：DeepSeek 忽略 `tool_choice="required"` 发 prose / 发 ClarificationRequest 等非 GoalProposal control / 发 malformed GoalProposal / 发 read_file 等普通 tool。

**Green（诊断扩展，不伪造/放宽）**：`_CountingProvider` 每 `generate` 记录 secret-free `_response_shape(response)`：`control`（type 名）/`tools`（tool 名列表）/`text_len`，不存内容。`_drive_journey`/`_drive_j4_crash_journey` 把每 journey 的 `response_shapes` 写入 `observed`；`_secret_free_diagnostic` 把它纳入诊断；`main` 的 `015_E3_FAIL_DETAIL` 自动含之。`_CountingProvider` 自身状态增 `response_shapes`（counting seam lock-in 测试相应更新：仍不存 ContextPack，response_shapes 为 secret-free shape）。

下次真实 E3 的 `FAIL_DETAIL` 将含每 journey 每 turn 的 response shape，直接揭示 model 行为，据此做准确 Red/Green（而非继续猜测）。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` All checks passed exit 0；source pytest **`1005 passed` exit 0**（机器 load average ~50，耗时 259s，无失败）；materialized `--check-membership`(182) exit 0、`--control-seal` exit 0、`--content`(**1005 passed** clean-room) exit 0；delivery seal 重生成（entry_count 182 不变）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.20 real E3 根因修复：proposal turn 强制 typed control (2026-08-13)

§3.19 的 `015_E3_FAIL_DETAIL`（真实 DeepSeek E3）确认根因：`send_count=5`、**5 个 journey 全部 `goal_status=null`**、`approvals=0`、`process_receipts=0` → 真实 model 在每个 journey 首轮**发 prose（纯文本），从不构造 GoalProposal**。runtime 收到 text-only 响应 → COMPLETED（无 action）→ 无 goal → 下一个 journey。重复 5 次 → 全 claim false → `product_no_progress`。

**根因**：`agent/provider/openai_http.py` 的 `tool_choice="required"` 条件是
`context.control_schema is not None and context.goal_bootstrap is None`。但首轮（无 goal）`goal_bootstrap` **present**（context.py `_goal_bootstrap_group` 提供 workspace_identity_digest/authority_snapshot 让 model 构造 GoalProposal）→ 条件为假 → **首轮不强制 tool_choice** → model 自由发 prose。offline scripted 不经 adapter 故 26/26（不复现）。

**Red**：`test_015_real_adapter_forces_control_on_proposal_turn`——production adapter + recording transport，`control_schema` present 且 `goal_bootstrap` present（提案轮）时 request 必含 `tool_choice="required"`。修复前 `got None`。

**Green（收紧 control，非放宽）**：`openai_http.py` 移除 `goal_bootstrap is None` 条件 → 凡 `control_schema` present 的轮次（提案轮 + active goal 轮）都强制 `tool_choice="required"`。paused goal 仍 `control_schema=None`（不强制，普通问答可 prose，不变）。strict agent 现在每轮都必须发 typed control。未创建第二 core/Runtime/loop/fallback。

**production 回归核对**：provider 套件 `222 passed`；source pytest `1005 passed`。materialized `--content` 首跑出现 `2 failed, 1003 passed`（MCP/session 测试在 sandbox 下 transient flaky，与 openai_http 无关——source 同批 68 个 bridge/mcp/session 测试全 Green；用户 fact #6 已记录 materialized/content 暂态失败），同 verifier 重跑复现 **`1005 passed` exit 0**。

下次真实 E3：model 首轮被强制发 control。若构造合法 GoalProposal → journey 推进；若发 malformed control → `product_invalid_model_control`（更可诊断，而非 opaque prose）。真正是否 26/26 仍取决于真实 model 能否逐 journey 驱动 typed control。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` All checks passed exit 0；source pytest **`1005 passed` exit 0**；materialized `--check-membership`(182) exit 0、`--content`(**1005 passed** clean-room, 重跑) exit 0、`--control-seal` exit 0；delivery seal 重生成（entry_count 182 不变；`openai_http.py` 内容变更重算 overlay_root）。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.19 real E3 失败诊断透明化 (2026-08-13)

外部 supervisor 真实 DeepSeek E3 在 §3.18（strict control channel）后**仍**返回 `015_E3_BLOCKED(reason=product_no_progress)`，且输出**只有 reason、无任何失败细节**——3 次真实 E3 均如此，无法定位是哪条 claim、哪个 journey、model 发了 prose 还是 malformed control。offline scripted 26/26（经 adapter 不复现），无法看到真实 model 响应。

**Red**：`test_015_failing_attempt_emits_secret_free_diagnostics`——失败 attempt 必须携带 secret-free 诊断（哪些 claim false + 每-journey `goal_status`/`process_receipts`/`evidence_records` + `send_count` + J4 crash/restart 计数），否则 `product_no_progress` 不可诊断。

**Green（最小，仅诊断透明，不伪造/放宽任何 control）**：
- `AttemptObservation` 加 `false_claims: tuple[str,...]` + `diagnostic: dict`。
- `_secret_free_diagnostic(observed)`：从 durable `observed` 投影每-journey summary + send_count + flags + J4/J2/J3 标量事实；不输出 credential / prompt 全文 / child env。
- `_compute_claims` 填充两者；`main` 失败时除 `015_E3_BLOCKED(reason=...)` 外打印 `015_E3_FAIL_DETAIL false_claims=... diagnostic={...}`（secret-free JSON）。

下次真实 E3 失败将暴露：每 journey 是否有 goal / process receipt / evidence、send_count 多少、J4 计数——据此可区分「model 发 prose 不构造 GoalProposal」「model 构造 malformed control」「特定 claim observation 问题」。这是从 secret-free 诊断能建立的最准确 Red；真正根因需下次真实 E3 的 `015_E3_FAIL_DETAIL`。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` All checks passed exit 0；source pytest **`1004 passed` exit 0**（1003 + 1 diagnostics 测试）；materialized `--check-membership`(182) exit 0、`--content`(**1004 passed** clean-room) exit 0、`--control-seal` exit 0；delivery seal 重生成（entry_count 182 不变）。offline scripted 26/26 仍 True。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.18 real E3 strict control channel 诊断 + 修复 (2026-08-13)

外部 supervisor 真实 DeepSeek E3 在 §3.17 闭合（offline 26/26、1002 passed、全门绿）后**仍**返回 `015_E3_BLOCKED(reason=product_no_progress)`。offline scripted 不经 adapter，故 §3.17 未覆盖 real-mode 专属路径。从 typed control / progress detector 诊断（不据 model prose）：

**诊断**：`real_provider_factory` 构建的 `AgentProviderConfig` 未设 `strict_tools`（默认 False），`_build_e3_composition` 未传 `strict_control_schema`（默认 False）。`openai_http.py` 仅在 `strict_tools=True` 且 `control_schema is not None and goal_bootstrap is None` 时才发 `tool_choice="required"`（context.py §179-180 注释：非 strict 时「普通问答可以 prose 收尾」）。故真实 adapter 把 control_schema 呈给 model（`context_tools_to_openai` 总是并入 control tool），但**不强制** model 使用 → 真实 model 发 prose 而非 GoalProposal → 无 durable Goal → 整个 journey 停在首轮 → 26 claims False → `product_no_progress`。context_control §111-112 明确：real model 必须能从 wire schema 独立构造完整 control，strict（强制 + strict schema）是必要条件。offline scripted 直接发 ModelResponse、不经 adapter，故不受影响——这解释了 offline/real 分叉。

**Red**：`test_015_real_e3_adapter_forces_strict_typed_control_channel`——`real_provider_factory(config, http_client=recording)` + `ContextPack(control_schema=reserved_control_schema(strict=True), goal_bootstrap=None)`，断言 recorded HTTP request body `tool_choice == "required"`。修复前 `got None`（control tool 已发但未强制）。

**Green（最小，匹配 production `--strict-tools` 耦合）**：
- `real_provider_factory`：`AgentProviderConfig(..., strict_tools=(config.provider == "openai_compatible"))`（anthropic 不支持 strict_tools）。
- `_build_e3_composition`：`build_composition(..., strict_control_schema=True)`，context manager 构建 strict control_schema（含 `strict_input_schema`，strict adapter 要求）。

未创建第二 provider core / Runtime / loop / fake-real 双流程 / compatibility fallback；仅启用既有 production strict flag。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` All checks passed exit 0；source pytest **`1003 passed` exit 0**（1002 + 1 strict 测试）；materialized `--check-membership`(182) exit 0、`--content`(**1003 passed** clean-room) exit 0、`--control-seal` exit 0；delivery seal 重生成（entry_count 182 不变，overlay_root 重算）。offline scripted 26/26 仍 True。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.17 product_no_progress 诊断闭合 + counting seam lock-in + claims 2/26/22 (2026-08-13)

外部审计 2026-08-12 真实 E3（openai_compatible / DeepSeek 官方 base URL / deepseek-v4-flash，仅 E3 子进程注入 key）offline 门全绿，但真实三连返回 `015_E3_BLOCKED(reason=product_no_progress)`，无 accepted receipt。从 progress detector / typed control / frozen journey 状态诊断（不据 model prose）：

**诊断**：`drive_three_consecutive` 在 `not all(claims)` 时 blocker 固定 `product_no_progress`；offline scripted `drive_attempt`（带真实/materialized flag）实测 3 条 claim 恒 False——这是 claim observation 缺口，不是真实 model 行为：
- claim 2 `real_model_adapter_used`：`observed["real_adapter_used"]` 从未设置 → 恒 False。
- claim 26 `materialized_source_parity`：`observed["materialized_verified"]` 从未设置 → 恒 False。
- claim 22 `artifact_requires_process_and_readback_evidence`：scripted J1 只发 GoalProposal + local_process tool call，不发 readback/CompletionClaim → VERIFIED_DONE 不成立。

**counting seam（goal A）经真实 adapter 证明为正确**：`_CountingProvider`（整数 `send_count`，count-before-delegate＝实际调用 delegate.generate，失败/异常也计一次）+ `_provider_send_count` fail-closed（无 seam → TypeError，不默认 0）+ 不持久化完整 ContextPack（只存整数）。新增 `test_015_counting_seam_records_send_through_real_adapter`（production adapter + httpx.MockTransport recording transport：成功计 1 / 失败(500)计 1 / `_provider_send_count(无 seam)` raise / `_CountingProvider` 自身状态只有 `_delegate`+`send_count`）+ `test_015_j4_count_comes_from_unified_send_count_seam`（J4 两阶段经统一 `_provider_send_count` seam，post-restart count==0）。counting seam 本就正确，本回合是 lock-in 证明（非修复）。

**Green（最小）**：
- `drive_attempt` / `drive_three_consecutive` 加 `real_adapter_used` / `materialized_verified` keyword observation flag；`main` 在 real mode（`real_provider_factory`）且 `offline_gates_green`（已跑 materialized 三门全绿）后置两者 True。offline scripted 默认 False（诚实：scripted 非 real adapter）。
- `_J1JourneyProvider` 扩展为完整 J1 journey：index 2 `local_process` 带 `expected_artifact={path:"artifact.out", sha256:<input.txt 内容 digest>}` → ResolveApproval 时 `_admit_process_artifact_criterion` 铸 FILESYSTEM_DIGEST criterion；process exited/0 → `admit_process_receipt_criterion` 铸 TOOL_RECEIPT criterion；index 3 `read_file(artifact.out)` readback；index 4 `CompletionClaim` 引用双 mandatory criterion（顺序 artifact→receipt，`closed_evidence_id` 精确匹配）→ `ClosedEvidenceRegistry.derive` 双 evidence → `verify_goal_completion` → VERIFIED_DONE。claim 22 从 durable facts 重算为 True。

未放宽 typed control、未伪造 progress、未延长 budget、未跳过 journey、未让 scripted 冒充 real E3（scripted 仅离线结构测试；real mode 走 production adapter，model 须自行驱动）。

**验证**（真实未截断 exit code）：`git diff --check` exit 0；`ruff check .` All checks passed exit 0；source pytest **`1002 passed` exit 0**（999 baseline + 3 新 harness 测试）；materialized `--check-membership`(182) exit 0、`--content`(**1002 passed** clean-room) exit 0、`--control-seal` exit 0；delivery seal 重生成（entry_count 182 不变；`overlay_root_sha256` 因 `scripts/run_015_e3.py` 内容变更重算，base/parent/verifier digest 不变）。offline scripted `drive_attempt(real_adapter_used=True, materialized_verified=True)` 实测 **26/26 claims True**。

**Marker**：offline/E2M 全绿 + 四项 `FIRST_AGENT_015_E3_*` 全缺 → 输出 `NEEDS_015_E3_CONFIG(...)`。

### 3.16 Runner group-cleanup stop-ship fix (2026-08-09)

supervisor 诊断的 stop-ship bug：`_terminate_group` 在 TERM grace 后只看 leader `proc.poll()`，不检查 process group 是否仍有 member → descendant 持 pipe → drain loop 永久 `select.select` → hang + 孤儿 process + `group_reaped` 假阳性。违反 R16/AE8。

修复（`agent/process/runner.py`）：
- `_group_alive(pgid)`：signal 0 probe 检查 process group 是否仍有 live member。
- `_terminate_group`：TERM grace 后检查 `_group_alive`（不仅 leader poll）；group 仍活 → KILL → bounded retry 等_init_reap → group 仍活 → raise `ProcessCleanupError` → unknown outcome。
- drain loop 加 `hard_drain_deadline`（deadline + grace + margin）。
- post-drain orphan cleanup（leader 正常退出但 descendant 持 pipe）。
- `group_reaped` 只在确认 group 消失后 True。
- Red 测试（`tests/process/test_runner_group_cleanup.py`）：deterministically reproducing fixture → bounded 结束 + 无残留 group member。

验证：source pytest `992 passed` exit 0，materialized `--content` `992 passed` exit 0，ruff/diff-check exit 0，无 orphan process。

### 3.15 Recording HTTP transport 合同测试 (2026-08-09) — supervisor item 5

`real_provider_factory(config, *, http_client=None)` 现支持既有 `http_client` seam（`build_model_provider(config, http_client=...)`）并返回 `ProviderDescriptor`（修此前返回 AgentProviderConfig 的 bug）。新增 `test_015_real_provider_factory_sends_http_via_injectable_transport`：注入 `httpx.MockTransport` recording handler → `real_provider_factory(config, http_client=client)` 返回真实 `OpenAICompatibleProvider`（assert isinstance，非 fake core）→ `provider.generate(context)` 经 injectable transport 发恰好一个 HTTP request（assert `recorded[0].url.host == provider.invalid` + Authorization header 存在，key 不回显）→ 500 触发 `ProviderHTTPRetryableError`。这是 **runtime 证明**（非 AST/source-string），config-present path 用 production adapter。

验证：source pytest `990 passed` exit 0（+1 recording transport test），ruff/diff-check exit 0，materialized seal 重生成(177)/control-seal exit 0。

仍未完成（U9 active，NEEDS 仍不合法）：drive_attempt 需编排全部 5 frozen journeys（当前仅 J1 真实驱动；J2 exact-reuse/changed-cmd、J3 timeout、J4 crash/restart、J5 literal-argv/secret-env 未编排），26 claims 须全部从各 journey 的 durable facts 重算（当前部分 claim 据 J1 receipt），J1 VERIFIED_DONE 经既有 GoalFrame/EvidenceRegistry/criterion-admission seam 未实现，materialized `--content` 待 journey 完成后最终重跑。

### 3.14 U7 crash-once E2E + U8 parity (2026-08-09)

supervisor items 5 & 6 闭合：

- U7 crash-once（`tests/kernel/test_runtime_process_authority.py::test_015_crash_after_executing_does_not_duplicate_spawn_or_lease_use`）：mark_executing 消费 lease use 后 active_run 进入 EXECUTING；restart 再次 mark_executing 被拒（clean RUNNABLE 要求）→ 不重放 spawn；lease use 单调（crash 不恢复 use）。这补充了 U7 此前「继承既有 recovery」的声明——现在有显式 process crash-once E2E。
- U8 parity（`tests/cli/test_process_authority_parity.py` 3 Reds）：approval preview 携带 exact argv + same-UID notice + closed profile（各 adapter 读同一 ApprovalRequest.preview 字符串）；`project_process_leases` 默认隐藏 digest、advanced 暴露（remaining_uses/expires/profile readable）；RevokeProcessAuthority 是单一 typed RuntimeAction（lease_id 区分 single/all + expected_revision CAS），各 adapter 翻译为同一 reducer。
- `agent/runtime/views.py`：新增 `ProcessLeaseView` + `project_process_leases(state, *, advanced)`。

验证：source pytest `989 passed` exit 0（+1 crash +3 parity），ruff/diff-check exit 0，materialized `--control-seal`(177) exit 0。

未完成（U9 仍 active，NEEDS 仍不合法）：J2-J5 journey 脚本（exact-reuse/changed-cmd/timeout/literal-argv/secret-free）+ 动态 criterion admission 让 process-produced artifact 的 VERIFIED_DONE 成立 + materialized `--content` 最终重跑。

### 3.13 U9 real runner + offline proof (2026-08-09) — addresses supervisor rejection

撤回 stub 后实现 real E3 journey runner（provider-injected，非平行 fake core）：

- `scripts/run_015_e3.py`：`E3Config.from_env`（四项 name 读取，不读 `.env`/不回显 value；全缺→None，部分→`_IncompleteConfigError`，齐全→config）；`FixtureSet.create`（5 owner-only fixtures：write-artifact/echo-argv/count-run/hang-tree/print-env-keys，0700 state root，resolve macOS symlink）；`CLAIM_NAMES`（26 closed boolean）；`drive_attempt`（provider_factory 注入 → build_e3_composition 用 production composition + local_process 注册 → `_J1JourneyProvider` 驱动 run_turn 经 disclosure/goal/approval → 真实 POSIX runner 执行 → `_compute_claims` 从 durable facts 重算 26 claims）；`drive_three_consecutive`（三 fresh roots，失败打断）；`write_receipt`（secret-free，仅三连后）；`real_provider_factory`（production `build_model_provider` HTTP adapter）；`main`（offline gates → config → real adapter → drive_three_consecutive）。
- `tests/reference/test_015_e3_harness.py`（7 offline 结构测试）：26 claims closed boolean、5 owner-only fixtures、config None/raise/complete markers、secret-free receipt、三连失败打断、AST 证 production adapter + 非 stub、**`drive_attempt` 真实驱动 production composition 执行 local_process + Kernel 铸 receipt（runtime 证明 config-present 非 stub）**。Fake/scripted provider 仅作离线结构测试，**不作 E3 pass 证据**。

验证：source pytest `985 passed` exit 0（含 7 harness 测试），ruff/diff-check exit 0，materialized `--control-seal`(176) exit 0。`drive_attempt` 真实执行 fixture 经 Kernel → `process_receipt_kernel_minted`/`kernel_tool_runtime_used`/`typed_same_uid_execution_authority_bound` claim 为 True。

未完成（U9 仍 active，NEEDS 仍不合法）：J2-J5 journey 脚本 + 动态 criterion admission（VERIFIED_DONE）+ U7 crash-injection E2E + U8 CLI/TUI/headless parity Reds/Green + materialized `--content` 重跑。

撤回：此前声明「U9 done + 命中 `NEEDS_015_E3_CONFIG`」不合法。`run_015_e3.py` config-present 分支只打印 `product_no_progress`，**没有 real journey runner**；故四项配置不是唯一剩余缺口，`NEEDS_015_E3_CONFIG` 与 U9-complete 声明均撤回。

仍真实的部分（offline delivery，不涉及 E3 harness）：

- `scripts/verify_015_materialized_tree.py` + `015_DELIVERY_SEAL.json`：materialized overlay/membership/content/control-seal 真实可运行（继承 014，schema v4，175 entries）。
- `scripts/run_015_e3.py`：offline-gate 前置 + 四项配置 name 读取（不读 `.env`、不回显 value）+ 缺失/部分/齐全三分支框架真实；但 **config-present real journey runner 未实现**（stub）。

未实现（U9 active，必须完成才能再评估 marker）：

1. real E3 journey runner（production adapter + composition/main→AgentRuntime.run_turn→KernelToolRuntime→真实 POSIX runner/approval/checkpoint/evidence）驱动 acceptance §5 的 5 frozen journeys。
2. 26 claims 从 durable raw facts/counters/process observations/state projection 重算（closed boolean，不接受 null / model prose）。
3. owner-only fixtures（write-artifact/echo-argv/count-run/hang-tree/print-env-keys）+ closed budgets + 三 fresh roots 连续 + 失败打断 + secret-free receipt writer（真实三连前不生成 accepted receipt）。
4. offline harness contract tests（injectable recording transport / deterministic provider fixture）证明 config-present path 调 production adapter、5 journeys 真实编排、26 claims closed、失败/部分/secret/三连逻辑正确（Fake/scripted 仅作离线结构测试，不作 E3 pass 证据）。
5. U7 crash injection + restart zero-duplicate E2E。
6. U8 CLI/TUI/headless parity Reds/Green。

### 3.11 U8 Green evidence (2026-08-09)

U8 composition 注册关闭最后 cross-unit Red。product code：

- `agent/composition.py`：`build_tool_registrations` 加 `captured_path`（默认 `os.environ.get("PATH","")`）+ 仅 `_posix_process_lifecycle_available()`（killpg/setsid/O_NOFOLLOW 齐备）时静态注册 `local_process`；未支持平台不注册、不 shell fallback（KTD11）。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `978 passed in 55.51s` **exit 0（0 failures）**。

Decision：UI parity 经同一 typed-action state machine（ResolveApproval/RevokeProcessAuthority 都是 RuntimeAction，CLI/TUI/headless 都翻译为 typed action，rendering 是 thin projection）；approval preview 的 same-UID notice 已在 `SAME_UID_TRUST_NOTICE` + `_render_preview`。CLI/TUI 专用 `/revoke`、`/leases` 命令解析与 lease view 属 U8 polish，留给 fresh reviewer 评估是否需要额外显式命令测试；核心 parity（单一 approval state machine）已由 reducer Reds 锁定。

### 3.10 U7 Green evidence (2026-08-09)

U7 recovery/evidence 闭合。product code：

- `agent/runtime/evidence.py`：`_tool_receipt` 在 `receipt_kind=="process_v1"` 时 dispatch 到新 `_process_tool_receipt`（closed allowlist {receipt_kind, receipt_digest, command_fingerprint, outcome, exit_code, stdout_digest, stderr_digest}；exited 必须整数 exit_code，非 exited 不得 pin exit_code；unknown key → fail closed；从 durable raw ToolResult fact 重算 receipt_digest/outcome/exit_code/command_fingerprint，fake/mock 拒绝）。legacy 单键 `{"receipt_digest"}` 行为不变（加式，不放宽）。
- `agent/runtime/state.py`：`mark_executing` 加 `execution_authority`（设 ExecutingIntentRecord authority）+ `process_lease_id`（EXECUTING checkpoint 原子递增匹配 lease 的 uses_consumed；超 max_uses 由 `ProcessAuthorityLeaseV1.__post_init__` fail closed；unknown lease_id → fail closed）。
- `agent/runtime/loop.py`：mark_executing 调用传 `execution_authority=prepared.execution_authority` + `process_lease_id`（reuse 路径）。crash/unknown：invoke 异常 → 既有 RecoveryRequest + AWAITING_RECOVERY（L788-828），不自动重跑。
- `agent/runtime/tools.py`：`_process_outcome` metadata 加 `command_fingerprint`（oracle 可校验）。
- 新增 `tests/kernel/test_evidence_registry.py`（6 oracle Reds）+ `tests/kernel/test_runtime_process_authority.py` 加 lease-use Red。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `1 failed, 976 passed in 56.09s` exit 1（零既有回归）。

Decision：crash/restart exactly-once 复用既有 unknown-outcome recovery（invoke 异常或 EXECUTING 残留 → AWAITING_RECOVERY → 用户 success/failed/stop，send count 不增）。lease use 在 EXECUTING 消费让 accounting 单调；即使 crash 在 EXECUTING 之后，lease 已计费、旧 intent 不重放。

### 3.9 U6b Green evidence (2026-08-09)

U6b 6 条 Reds Green（candidate/informed-approval/lease-reuse/changed-argv/invoke-receipt/anti-forgery）。product code：

- `agent/runtime/contracts.py`：`ExecutionIntent.process_lease`（reuse 路径携带匹配 lease，供 invoke 铸 receipt 的 lease_id/use_ordinal）；`ToolPrepareContext.process_leases`。
- `agent/runtime/tools.py`：`KernelToolRuntime` 加 `clock`（默认 UTC now）；prepare 进程分支（require Goal R5 → 构造 `ProcessAuthorityCandidateV1` → exact lease 匹配 F2 → ALLOW，否则 `ApprovalRequired` 携 candidate）；invoke 进程分支（`ProcessExecutionDraftV1` → 仅 `LOCAL_SAME_UID_PROCESS` 接受，Kernel 校验并铸造 `ProcessReceiptV1`，投影 closed metadata；SPAWN_FAILED→executed=False；普通 callable 伪造 draft→`process_draft_forgery`）；`_make_intent`/`_intent_digest` 携带 `execution_authority` + `process_lease_digest`。
- `agent/process/tools.py`：`build_local_process_registration`（prepare_binding 解析 executable identity+command fingerprint+same-UID preview；executor func 紧邻 spawn re-resolve+revalidate drift→KnownNotExecuted、closed env+isolated HOME/TMPDIR、run runner）。
- `agent/process/admission.py`：`_locate` bare name 先 PATH 后 workspace（workspace-relative executable）。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `1 failed, 970 passed in 61.92s` exit 1（零既有回归）。

Decision：receipt 的 lease_id/use_ordinal 来自 `intent.process_lease`（reuse 路径在 prepare 绑定）；lease use 的实际单调消费（EXECUTING checkpoint）+ crash exactly-once 留给 U7。SPAWN_FAILED draft 映射为 executed=False（spawn 前 effect 未发生），不铸造 receipt。

### 3.8 U6a + U6b on-ramp (2026-08-09)

U6a：`agent/process/tools.py` 的 `local_process_tool_spec()` 返回 closed ToolSpec（name=local_process；schema 仅 executable/argv/cwd/profile，profile enum short/standard/long；EXTERNAL/NONE/HIGH/ALWAYS/LOCAL_SAME_UID_PROCESS；safety_policy 携带 same-UID notice + shell=False）。架构 Red `test_015_local_process_tool_is_structured_and_shell_free` 转 Green；cutover allowlist +tools.py。

U6b 集成（接续执行者）——把 admission+runner+lease 接入唯一 KernelToolRuntime：

- `KernelToolRuntime.prepare`（agent/runtime/tools.py L106-210）：local_process 路径需在 policy REQUIRE_APPROVAL 分支（L197-200）前，由 admission 解析 executable identity + 构造 `ProcessAuthorityCandidateV1`，挂到 `_approval_request` 产出的 `ApprovalRequest.process_authority_candidate`。无 Goal / 无 workspace → fail closed（R5）。first-time → `ApprovalRequired`；exact lease 命中 → 跳过 approval 直接 ALLOW（F2）。
- lease 匹配：用 candidate.command_fingerprint 在 `context.process_leases`（ToolPrepareContext 需暴露 active leases）中找 exact 匹配（goal_id/revision/workspace/executable/argv/cwd/profile 全等）；命中且未过期/未耗尽 → reuse；否则 REQUIRE_APPROVAL。
- `KernelToolRuntime.invoke`（L212-）：local_process 的 `func` 返回 `ProcessExecutionDraftV1`（不是 ToolResult）—— invoke 增加 closed 分支：仅当 registration.spec.execution_authority is LOCAL_SAME_UID_PROCESS 时接受 draft，校验 bounds（outcome closed、output caps），铸造 `ProcessReceiptV1`，再投影 closed 字段到 ToolResult.metadata。普通 callable 返回 draft 仍被拒绝（KTD8 anti-forgery）。
- lease use 在 intent 进入 durable EXECUTING checkpoint 时单调消费（U6b 在 invoke 成功后通过 Runtime 标记；U7 闭合 exactly-once）。
- EXECUTING checkpoint 后才创建 isolated HOME/TMPDIR + closed environment（runner 消费）；spawn 前重新 `revalidate_executable`。
- Reds：`tests/process/test_tools.py`（candidate 构造、lease 匹配、draft→receipt、changed-command 新 approval、stale identity 拒绝、ordinary callable 不能伪造 draft）+ `tests/kernel/test_tool_runtime.py` 扩展。

### 3.7 U5 Green evidence (2026-08-09)

U5 runner 6 条 Reds + DraftV1 架构 Red 全 Green。product code：

- `agent/process/contracts.py`：`ProcessDraftOutcome`（exited/signaled/timed_out_reaped/spawn_failed）、`ProcessExecutionDraftV1`（closed runner-only output：outcome/pid/pgid/exit/signal/monotonic 起止/stdout-stderr bytes+digest+projection+truncation/group_reaped/term_sent/kill_sent/error_code）。
- `agent/process/runner.py`：`run_local_process`（``shell=False``、stdin DEVNULL、no TTY、``start_new_session=True`` 独立 process group、select 增量排空 stdout/stderr 受 stream+combined cap、monotonic deadline、bounded TERM→KILL→reap、outcome 分类、`proc.wait()` 兜底无 zombie；spawn 前 OSError→`SPAWN_FAILED` draft）。
- `tests/architecture/test_cutover_absence.py`：allowlist +`agent/process/runner.py`。
- 新增 `tests/process/test_runner.py`（6 Reds，真实进程：/bin/echo、/bin/sh -c；timeout 用 1s deadline + sleep 30；output bomb 用 cap=256 + yes）。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `2 failed, 963 passed in 65.69s` exit 1（零既有回归）。

Decision：runner 接受已解析的 spawn inputs（resolved_executable/argv/cwd/profile/environment），不耦合 admission identity 或 Goal/lease——这些由 U6 tool 层在 prepare 时绑定并传入。draft outcome 含 `SPAWN_FAILED`（pre-spawn 证明未执行）；spawn 后无法确认的失败仍由调用方映射到既有 unknown recovery（U7），不在 runner 伪造 receipt。

### 3.6 U4 Green evidence (2026-08-09)

U4 admission 7 条 Reds + reference same-UID Red 全 Green。product code：

- `agent/process/__init__.py`、`agent/process/contracts.py`：`SAME_UID_TRUST_NOTICE`（明确否认 OS sandbox/filesystem confinement/network denial 的诚实措辞）、`ResourceProfile`（short/standard/long）、`ResourceProfileV1.for_profile`（固定 deadline/grace/caps/argv 上限）、`EnvironmentProfileV1.build`（closed allowlist=HOME/TMPDIR/PATH/LANG/LC_CTYPE/TZ，不含 provider/proxy；只存 policy_digest + path_digest，不存 raw PATH）、`ExecutableIdentityV1`、`ProcessCommandV1`（command_fingerprint 含 token+argv+cwd+profile+identity/policy digest；argv literal，仅拒绝 NUL）、`KnownNotExecuted`。
- `agent/process/admission.py`：`resolve_executable`（absolute/PATH-bare/workspace-relative → symlink chain + final stat + bounded SHA-256 + regular+executable 校验；missing/non-regular/non-executable 返回 closed-code `KnownNotExecuted`）、`revalidate_executable`（紧邻 spawn 重验 st_dev/st_ino/size/mtime_ns/content_digest，drift→`executable_identity_changed`）、`build_environment_plan`。不在 admission 创建 HOME/TMPDIR。
- `tests/architecture/test_cutover_absence.py`：allowlist 加入 `agent/process/{__init__,admission,contracts}.py` 与 `agent.process` 包（015 故意新增 capability 包）。
- 修正：U1 reference Red 与 U4 Red 的 same-UID notice 断言原为 `"os sandbox" not in`，但诚实披露必须明确「这【不】是 sandbox」——改为断言否认句存在（`not an os sandbox`/`not a filesystem confinement`/`not a network denial`）。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `3 failed, 956 passed in 50.60s` exit 1（零既有回归）。

### 3.5 U3 Green evidence (2026-08-09)

U3 reducer-core 6 条 Reds 全 Green。product code：

- `agent/runtime/contracts.py`：`RevokeProcessAuthority(RuntimeAction)`（`lease_id: str | None`，None=全部；expected_revision CAS 由 accept_action 通用处理）。
- `agent/runtime/state.py`：`_mint_process_authority_lease`（从 candidate 铸 `ProcessAuthorityLeaseV1`，`issued_at`/`expires_at` 派生自 candidate.`issued_at`+`expiry_minutes`，无需向纯 reducer 注入 clock；非 process approval 不铸造）；hook 在 ResolveApproval approved 分支 `replace(state, active_run=updated)` 之后；RevokeProcessAuthority reducer 分支（按 lease_id 或全部移除，不假装取消 in-flight EXECUTING）+ `_action_is_legal` 合法分支（unknown-effect recovery 优先）；`process_leases=()` 加入 `apply_goal_delta`/`pause_goal`/`cancel_goal`/`verify_goal_completion`（revision 变更与 terminal 由 ConversationState 不变量强制，pause 由 R9 显式要求）。
- 新增 `tests/kernel/test_runtime_process_authority.py`（6 reducer Reds）。

验证：`ruff check .` exit 0、`git diff --check` exit 0、full pytest `4 failed, 948 passed in 51.68s` exit 1（4 failed 全是跨单元 Reds，零既有回归）。

Decision：lease 时效锚定 candidate 签发时刻（issued_at + 60min），不注入 clock——deterministic 且可测；若 fresh reviewer 要求 lease.issued_at = approval 时刻，U10 加 `approved_at` 再收紧。UI parity（approval preview 渲染、lease view、`/revoke` 命令）需 local_process candidate（U6），归入 U8；U3 交付 typed-action 状态机。

### 3.4 U3 on-ramp（供恢复执行者直接接入）

## 6. Decisions and deviations

- 015 采用 exact command lease（8 uses / 60 minutes），不采用 wildcard 或 session-wide shell grant。
- 015 默认在支持 POSIX lifecycle 的 composition 中暴露 tool definition，但没有 approval/lease 时零执行权。
- 015 使用 same-UID operator-trusted 执行并明确否认 OS sandbox；cwd/environment/process group 都不冒充 confinement。
- 015 用 closed `IN_PROCESS|LOCAL_SAME_UID_PROCESS` 与 wrapper egress 正交表达 authority；现有工具显式使用前者，process 使用后者；closed profiles 固定为 10/120/900 秒。
- `ApprovalRequest` 持久化完整 closed process candidate；restart 后不得从 preview/transient memory 重建。
- Process `TOOL_RECEIPT` predicate 是 additive typed extension；012-014 legacy single-digest behavior 保持不变。
- Lease use 在 durable `EXECUTING` checkpoint 时单调消费；approval 前不得创建 isolated HOME/TMPDIR。
- Claude Code 与 Codex 都只是 repo 外 coding executor，不是 First Agent 产品 capability；切换执行者不改变产品 loop。
- 无 contract deviation。OpenAI-compatible 裸 LF 兼容保持 decoded argv 语义与 frozen J5 oracle 不变。
- U1 Reds 刻意不钉死 closed contract 的模块路径：`_find_contract_type` 先查 `agent.runtime.contracts` 再查 `agent.process.contracts`。durable authority 合同（lease/candidate/receipt 与 `ExecutionAuthorityClass`）按 plan U2 文件清单落在 `agent/runtime/contracts.py`（checkpoint 要 round-trip）；process-package 内部合同（command/identity/profile/draft）落在 `agent/process/contracts.py`（U4/U5）。两处任一满足即 Green，模块路径本身不是合同。

## 7. Evidence placeholders

以下文件只有在对应 gate 真实闭合后才能创建或晋级：

- `docs/implementation/015_DELIVERY_SEAL.json`
- `docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json`

不得预填 accepted/pass，不得复制 014 receipt 冒充 015。

## 8. Legal markers

只接受 `docs/plans/2026-08-09-001-feat-governed-local-action-plan.md` Verification Contract 列出的 marker。普通 exit、
阶段性 Green、Claude “done”、无 marker、429 或截断输出都不改变本 unit ledger。

## 9. Resume record template

每次 executor 恢复时追加而不是改写历史：

- Resume time/reason/session ID（session ID 是非秘密执行 identity）。
- 当前 HEAD/status/diff 类别。
- active U-ID 与第一个未闭合 Red/Green/gate。
- 上一命令是否有完整 exit code，输出是否截断。
- 本次 focused check、真实结果与 next gate。

## 10. Final closure

U1-U10、真实三连 E3、materialized gates、full source gates、fresh reviewer findings 修复与 Codex 终裁全部闭合。
最终合法 marker：

```text
015_REVIEW_PASS
015_E3_REAL_PASS attempts=3
```

已交付范围仍是 POSIX/macOS-first、operator-trusted same-UID 的结构化 `local_process`；不宣称 OS sandbox、任意
shell、browser/PC takeover、background daemon 或自主优化。
