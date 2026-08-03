# 009 Independent Promotion Review

本文件由非 U1-U8A 实现 agent/session 的 reviewer 填写。
它是 `locally-verified` promotion 与 `--control-seal` 的前置 receipt，不是 Coding Agent 自评表，也不是 E3 acceptance。

## Review boundary

- Implementation executor identity/session: Coding Agent 执行器（U1/U7/U8A 实现 session）
- Independent reviewer identity/session: 独立 reviewer session（Claude Code，与本轮实现 executor 不同 session）
- Distinct-actor check: pass（reviewer 未执行 U1-U8A 实现；本 receipt 由独立 session 写入）
- Review started at: 2026-07-23
- Executor content-gate receipt reviewed: pass（`009_EXECUTION_LOG.md` 记录的 `--content` exit 0 / 322 passed）
- Reviewer-owned content-gate rerun before control edits: pass（见 Final gate review；exit 0，未截断）
- Real provider/MCP/network calls authorized: no
- Private/denied content access authorized: no

Reviewer 只能检查 repo-relative path、允许读取的 product/test/package/doc、bounded command output 与 materialized origin evidence。
不得读取 `.env*`、credential/private roots、runtime logs/state、`tui/agent_log.jsonl`、`tui/memory/`、`.ua/`、`graphify-out/` 或用户私有 capability data。
Distinct-actor identity 是 reviewer 的程序性 attestation，不是 verifier 可自行证明的密码学身份；control seal 只验证 receipt schema/status 与冻结后的内容 digest。

## Admission review

| Check | Result | Evidence |
|---|---|---|
| Baseline commit and exact add/modify/delete inventory | pass | baseline `7d935ac...` 存在（`git cat-file -e`）；936 entries = 138 add / 20 modify / 778 delete，与执行 log 一致 |
| Unknown untracked paths fail closed | pass | v2 oracle `test_membership_reconciles_...` 证明 unknown untracked 报错；`reconcile_membership` 第 3 步强制非 denied untracked 必须声明为 add |
| Denied paths are path-only and never read/hashed | pass | v2 oracle `test_denied_and_unknown_paths_fail_before_content_read_or_hash` 用 dangling `.env` 证明 deny 先于 read/hash（无 admission/sha 错误）；entries 中 0 个 denied 路径 |
| Add/modify entries are no-follow regular files with link count 1 | pass | `admit_descriptor` 单一 fd 同时 fstat+read；v2 oracle 证明 hardlink(nlink!=1)/symlink(O_NOFOLLOW) 被拒 |
| Git mode/type and final digest match | pass | `validate_manifest` 校验 git_mode ∈ {100644,100755}；`reconcile_membership` 用同一 descriptor 比对声明 digest/git_mode；content gate 通过即对账成功 |
| Temporary Git index leaves real index unchanged | pass | v2 oracle `test_materialization_uses_temporary_index_without_touching_real_index`（`GIT_INDEX_FILE` 临时索引；before/after sha256 相等） |
| Manifest has no generate/broad-admit/self-hash path | pass | verifier 无 generate mode；manifest 不在 entries；`control_files` 中 manifest 为 `self-digest-forbidden`；`--check-membership` exit 0 |

## Observable-oracle review

Review the actual test body and its recorded Red/Green evidence, not only the test name or total pass count.

| Finding | Test body checks state/receipt/count/boundary | Red is target-accurate | Green uses same oracle | Verdict |
|---|---|---|---|---|
| F1 delivery admission | pass（deny 先于 read、descriptor 一致、三方对账、temp index、control-seal 拒绝 null/unsealed/drifted） | pass（A1/A4：旧 verifier best-effort/TOCTOU/忽略 delivery 测试/恒 0） | pass（同 8 nodeid oracle Green） | verified（delivery admission 闭合；N1 见 findings） |
| F2 content/control modes | pass（`--content` materialize+install+origin+deny-network+ruff+pytest；`--control-seal` 拒绝未封存） | pass（A1/A5：best-effort deny-network、control-seal 恒 0） | pass（reviewer 重跑 `--content` exit 0） | verified（module origin 已证；console entrypoint origin 见 N1） |
| F3 MCP | provisional（focused suite 43 passed，matrix 未完整闭合） | n/a（本轮不扩写） | n/a | provisional |
| F4 Memory | provisional（focused suite 21 passed，durability/recall 未完整闭合） | n/a | n/a | provisional |
| F5 SubAgent | provisional（focused suite 14 passed；保持 safe-unavailable） | n/a | n/a | provisional（E3-blocked） |
| F6 TUI/lifecycle | pass（Pilot 全键盘 submit/approve/reject/recovery/resume/cancel、reopen 零调用、shared queue sink、reverse-close exactly once、closing_requested/shutdown_blocked） | pass（A2：submit-only、renderer 作 sink、close 绕过 stack） | pass（同 Pilot/oracle Green） | verified（R19-R20 闭合；event-injection oracle 见 N2） |
| F7 Skill | provisional（focused suite 34 passed，identity/metadata 未完整闭合） | n/a | n/a | provisional |
| F8 Scheduler | provisional（focused suite 13 passed，busy/conflict matrix 未完整闭合） | n/a | n/a | provisional |
| F9 execution-log honesty | pass（逐项记录可核对 command/exit/observable；统计一致 322） | pass（A3：receipt pending、统计漂移） | pass（reviewer 核对一致） | verified（U1/U7/U8A）/provisional（U2-U6） |

## Final gate review

| Evidence | Result | Receipt summary |
|---|---|---|
| Ruff and all pytest commands have known exit 0 and untruncated output | pass | `--content` stderr 全量可见：`ruff passed`、`pytest passed (322 passed in 24.36s)`、`ALL CHECKS PASSED`、`CONTENT_EXIT=0` |
| Content gate originated from exact temporary materialized tree | pass | `materialize_tree` 用 `GIT_INDEX_FILE` 临时索引从 baseline `7d935ac` 精确 apply operations；真实 index 未触碰 |
| Non-editable import and console entrypoint origins exclude dirty tree | partial | `assert_origin` 证明 `agent.__file__`/`main.__file__` 在 prefix、不在 dirty tree（`ORIGIN_OK`）；console entrypoint origin 未单独断言（见 N1，非阻断） |
| OS deny-network boundary blocks DNS/TCP before send and covers descendants | pass | `deny-network enforced via sandbox-exec`（loopback listener 探针 DENIED）；ruff/pytest 及 descendants 全部在 sandbox-exec `(deny network*)` 边界内；不可用/未阻断 fail closed |
| No skip/xfail/test-double-only proof substitutes for required E2 | pass | TUI 用真实 Pilot 键盘路径 + ScriptedProvider；FakeProvider 仅作受控 provider double，不替代 production boundary journey |
| Ordinary files did not drift after content gate | pass | reviewer 自 content gate 后未修改任何 ordinary product/test 文件；`git status` 普通路径与 manifest 一致 |

## Per-capability promotion

`locally-verified` requires complete E1/E2/E2M plus this review.
Safe rejection without a positive supported journey remains `implemented-candidate`。

本轮不晋级任何 capability 到 `locally-verified`：5 项 extension capability 的完整 fault matrix 本轮未闭合（超出 U1/U7/U8A 授权范围）；TUI 的 event-fault 注入 oracle 缺失（N2）；delivery 的 console-entrypoint origin 断言缺失（N1）。Kernel 作为最小 foundation 保留 candidate。详见 findings。

| Capability | Executor provisional verdict | Reviewer verdict | Final claim | Residual limitation |
|---|---|---|---|---|
| Minimal Runtime Kernel | implemented-candidate | E1/E2/E2M 完整；foundation 非闭合 capability 集 | implemented-candidate | foundation only；不是完整通用 Agent |
| MCP | implemented-candidate | E2 partial（focused suite 通过，receipt/transport/latch matrix 未闭合） | implemented-candidate | no real-server E3；matrix pending |
| Memory | implemented-candidate | E2 partial（durability/recall closure pending） | implemented-candidate | owner-only plaintext；closure pending |
| SubAgent | implemented-candidate + safe-unavailable + E3-blocked | E2 partial；无 supported provider E2 | implemented-candidate + safe-unavailable + E3-blocked | current HTTP adapters unsupported；E3-blocked |
| Scheduler | implemented-candidate | E2 partial（busy/conflict matrix pending） | implemented-candidate | external caller only；matrix pending |
| Skill | implemented-candidate | E2 partial（identity/metadata closure pending） | implemented-candidate | read-only trusted roots only；closure pending |
| TUI | implemented-candidate | R19-R20 闭合（5/6 fault-matrix 组），event-injection oracle 缺（N2） | implemented-candidate | one conversation，no in-flight cancel；event-fault oracle pending |

## Findings and disposition

| ID | Severity | Evidence | Required action | Disposition |
|---|---|---|---|---|
| N1 | P2（非阻断） | `assert_origin`（`scripts/verify_materialized_tree.py:501-526`）只断言 `agent.__file__`/`main.__file__` origin，未单独验证 console entrypoint（`first-agent`/`first-agent-schedule`）origin。R5 字面要求“console entrypoint origin 指向临时安装”。实质安全保证成立：console script 由 `pip install --prefix` 装入、调用 `main:main`，而 `main.__file__` 已证明在 prefix；PYTHONPATH 在 gate 中被清除，无路径让 dirty-tree 代码经 entrypoint 运行。 | 后续在 `assert_origin`/v2 oracle 增加显式 console-script origin 断言（prefix/bin 存在且解析到 prefix）。 | 记录为 residual；不阻断本轮 seal；阻止 delivery/Kernel 到 `locally-verified`（本轮本不晋级） |
| N2 | P2（非阻断） | TUI fault matrix 6 组中，“event loss/duplicate/reorder 不改变 authoritative controls”无专门注入 oracle。事件按设计为 advisory（`load_view` 读 authoritative checkpoint），`drain()` 已测，但无 reorder/loss/duplicate 注入断言。 | 后续在 TUI 增加事件 reorder/loss/duplicate 注入测试后再晋级 TUI `locally-verified`。 | 记录为 residual；不阻断本轮 seal；阻止 TUI 到 `locally-verified`（本轮本不晋级） |
| N3 | 文档诚实性纠正 | executor capability 表把 MCP/Memory/SubAgent/Scheduler/Skill 的 E2 标为 `pass`，但其完整 production boundary journey/fault matrix 未闭合（本轮超范围）。准确值为 `partial`。 | 无产品改动；reviewer 在 Final claim 列已标注 E2 partial。 | 已在 Per-capability promotion 表纠正 |

Incomplete evidence for one capability blocks only that capability's promotion.
Missing review receipt、failed distinct-actor attestation、evidence truncation、admission uncertainty、private-path read、dirty-tree import、network-boundary failure、ordinary-file drift or unresolved global P0/P1 blocks the whole control seal。

本轮无未处置的全局 P0/P1；N1/N2 为 P2 residual，不阻断 control seal。

## Promotion receipt

- Independent review result: SEALED（candidate trustworthy；不晋级任何 capability）
- Reviewer-owned `.venv/bin/python scripts/verify_materialized_tree.py --content` exit/summary observed before this receipt was written: exit 0；`non-editable install ok` / `origin ok` / `deny-network enforced via sandbox-exec` / `ruff passed` / `322 passed in 24.36s` / `ALL CHECKS PASSED`（未截断）
- Capabilities approved for `locally-verified`: none
- Capabilities remaining `implemented-candidate`: Minimal Runtime Kernel、MCP、Memory、SubAgent（+ safe-unavailable + E3-blocked）、Scheduler、Skill、TUI
- E3 status: all pending（无 E3；无 `accepted`）
- Current-status/log controls updated by reviewer: yes（本文件、`009_EXECUTION_LOG.md`、`docs/architecture/CURRENT_CAPABILITY_STATUS.md`）
- Manifest control digests updated: yes（三个 reviewer control 的 sha256 + `seal_state: sealed-u8`）
- Control seal authorized after all control digests freeze: yes
- Repository mutated after successful control seal: must be no

The later `--control-seal` exit code and untruncated summary are reported outside the repository；recording them here after the command would invalidate this file's sealed digest.
