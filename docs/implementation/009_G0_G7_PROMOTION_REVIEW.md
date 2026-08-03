# 009 G0–G7 Independent Promotion Review

本文件由非 G0–G6 实现 executor session 的独立 promotion reviewer 在 G0–G6 fault matrix
与 G7 materialized delivery 完成后写入。它是把已满足条件的 capability 从
`implemented-candidate` 提升到 `locally-verified` 的前置 receipt，不是 E3 acceptance，
也不覆写历史 `009_INDEPENDENT_REVIEW.md`（后者记录 U1/U7/U8A 阶段的 candidate seal）。

## Review boundary

- Implementation executor identity/session：G0–G6 closure executor（在 009 sealed candidate 的
  后继隔离副本中连续闭合 G0–G6）。
- Independent reviewer identity/session：独立 reviewer session（Claude Code，与本轮 G0–G6
  实现 executor 不同 session，未执行任何 G0–G6 实现）。
- Distinct-actor check：pass（reviewer 未执行 G0–G6 实现；本 receipt 由独立 session 写入）。
- Review performed at：2026-07-24。
- 工作副本：`my-first-agent-general-loop.FMHzBg`（隔离后继副本；无 git remote；未 commit /
  push / tag）。
- Real provider / MCP / network calls authorized：no（仅在 deny-network 边界内跑 verifier）。
- Private / denied content access authorized：no（未读 `.env*`、credential、`tui/` runtime、
  `.ua/`、`graphify-out/`、用户私有 capability data）。
- Distinct-actor identity 是 reviewer 的程序性 attestation；control seal 只校验 receipt
  schema、`seal_state` 与冻结后的内容 digest。

reviewer 在写 controls 前亲自重跑了 materialized `--content` gate（见 Final gate rerun）。

## Independent evidence（从磁盘复核，非引用 executor 自述）

| Area | Reviewer check | Result |
|---|---|---|
| Runtime ownership（检查1） | 唯一 `AgentRuntime.run_turn`（`agent/runtime/loop.py:116`）；`composition.py` 显式只构造一个 `KernelToolRuntime`/`KernelContextManager`/`AgentRuntime`；SubAgent child 用同一 `AgentRuntime`（`agent/subagent/runner.py:101`，max_model_calls=1） | pass；全仓库无第二个 `class *Loop`、无 `CodingLoop`/`service_locator`/`compat`/`fallback`；`graphify-out`/`.ua` 等仅作 `file_ops.DEFAULT_PRIVATE_ROOTS` 的拒绝前缀，非运行时依赖 |
| G0 / N1（检查2） | `assert_console_entrypoint_origin` 显式断言 `first-agent`/`first-agent-schedule` 在 `prefix/bin`、owner-regular、target `main:<fn>`、prefix-first 环境 `--help` 端到端加载 | pass（content gate 打印 `console entrypoint origin ok`） |
| G0 / N2（检查2） | `tests/tui/test_adapter.py::test_advisory_events_loss_duplicate_reorder_do_not_change_authoritative_control`：注入 loss/duplicate/reorder/复合（含误导 kind/payload）后断言 checkpoint state、`revision`、`save_count==0`、projection actions、`provider.calls==[]` 全不变 | pass；先前 review 的 N2 阻断项已闭合 |
| G1 Skill（检查3） | body/resource 同内容 inode 替换 drift、skill 目录 ancestor 替换 drift（`test_catalog.py`）；bounded metadata 不泄露绝对 root/body（`test_tools.py`） | pass |
| G2 MCP（检查4） | `revalidate_spawn_identity` 复验 executable/ancestor/cwd（`test_catalog.py`）；approval 后 executable 内容替换 pre-spawn `not_executed`（`test_tools.py:368`）；256KB stderr flood 不死锁且不进 result（`test_tools.py:328`，真实 OS 管道）；preview 超限 prepare 拒绝不截断 | pass |
| G3 Memory（检查5） | strict load 拒绝 `revision="2"`/`created_at="1.5"` 等 coercion（`test_store.py:176/235`）；`_MAX_STORE_BYTES` monkeypatch 证明 read 在 parse 前有界（`:214`）；`0o600` owner-only；stale digest CAS 拒绝 | pass |
| G4 SubAgent（检查6） | `ChildAgentRunner` 要求 provider 结构化 `ProviderDeadlineCapability`，否则 `UnsupportedProviderError`（`runner.py:59`）；UNCONFIRMED 覆盖 child normalization→parent recovery | pass（fault matrix 闭合）；真实 `anthropic_http`/`openai_http` 均**不**声明 `deadline_contract`，仅 `fake_provider` 声明 → 无正向 supported E2，保持 `safe-unavailable + E3-blocked` |
| G5 Scheduler（检查7） | canonical UTC 整秒 round-trip，拒绝 fractional/offset/非闰年 2月29 等（`test_contracts.py:53/78`）；`conversation_busy` one-shot reload（`test_caller.py:125`，断言 `runtime.calls==2`）；duplicate replay 单 effect（`provider.calls==1`） | pass |
| G6 TUI（检查8） | 真实 Textual Pilot 全键盘 submit/approve('a')/reject('r')/recovery(s/f)/resume('u')/cancel/reopen/close，绑定 authoritative state 与 call-count；CLI/TUI parity（`test_app.py`/`test_approval_journey.py`） | pass |
| G7 delivery（检查9） | reviewer 亲自运行 `--check-membership`、`--content`、`--control-seal`、`git diff --check`、`ruff` | pass（数字见 Final gate rerun） |

## Final gate rerun（reviewer-owned，写 controls 前）

- `.venv/bin/python scripts/verify_materialized_tree.py --check-membership` →
  `membership ok: 938 entries`（exit 0）。
- `.venv/bin/python scripts/verify_materialized_tree.py --content` →
  `non-editable install ok` / `origin ok` / `console entrypoint origin ok` /
  `deny-network enforced via sandbox-exec` / `ruff passed` /
  `pytest passed (347 passed in 21.98s)` / `ALL CHECKS PASSED`（exit 0，未截断）。
  deny-network 经 sandbox-exec 负向 DNS/TCP 探针先证明阻断，ruff/pytest 及后代均在边界内。
- `.venv/bin/ruff check agent tests scripts main.py` → `All checks passed!`（exit 0）。
- `git diff --check 7d935ac -- .` → 无输出（exit 0，无空白/冲突标记）。

## Per-capability promotion

`locally-verified` 要求 E1 + E2 + E2M + 本独立 review。`safe-unavailable` 不是 claim level：
SubAgent 的 fail-closed boundary 可验证，但无满足 `ProviderDeadlineCapability` 的真实
provider，故不能宣称 `locally-verified` 或 accepted。

| Capability | E1/E2/E2M + review | Final claim | Residual limitation |
|---|---|---|---|
| Minimal Runtime Kernel | complete（唯一 owners、kernel fault matrix、materialized gate、本 review） | locally-verified | minimal foundation；不是完整通用 Agent；E3 pending |
| MCP | complete（identity/transport/receipt/latch matrix、materialized gate、本 review） | locally-verified | governed stdio MCP seam；identity/transport closure done；no real-server E3 |
| Memory | complete（strict store/identity-safe read/CAS、materialized gate、本 review） | locally-verified | governed Memory seam；strict store closure done；owner-only plaintext；E3 pending |
| SubAgent | fault matrix closed，但无 supported provider E2 | implemented-candidate + safe-unavailable + E3-blocked | current HTTP adapters unsupported；需 hard-deadline provider 才能 E3 |
| Scheduler | complete（UTC/busy/conflict matrix、materialized gate、本 review） | locally-verified | deterministic external caller only；E3 pending |
| Skill | complete（identity/drift/metadata closure、materialized gate、本 review） | locally-verified | governed read-only Skill seam；trusted roots only；E3 pending |
| TUI | complete（全键盘 fault matrix + N2 advisory invariant、materialized gate、本 review） | locally-verified | one conversation，no in-flight cancel；CLI parity 待 E3 |

没有 capability 是 `accepted`（E3 reference task 全部 pending）。

## Findings and disposition

| ID | Severity | Evidence | Disposition |
|---|---|---|---|
| O1 | informational（非阻断） | `tests/subagent/test_receipt_contract.py::test_unconfirmed_receipt_overrides_child_normalization` 断言 `receipt_state in ("terminated","unconfirmed")`，接受两种结果而非严格证明 UNCONFIRMED 必然发生（child Runtime 内部捕获 CAS crash 可能返回 terminated）。 | 不阻断：SubAgent 无论 receipt 细节均保持 `safe-unavailable + E3-blocked`（无满足 deadline contract 的真实 provider）；不影响任何 capability 晋级。建议未来 E3 前收紧为确定性 UNCONFIRMED 注入。 |

本轮无未处置的全局 P0/P1/P2。`accepted` 仅出现在 claim-level 定义与“无 capability 是 accepted”
的否定句中；`locally-verified` 仅用于已满足条件的 6 项与定义/规则文本；SubAgent 的
`safe-unavailable + E3-blocked` 在 `CURRENT_CAPABILITY_STATUS.md` 明确写出，未隐去。

## Promotion receipt

- Independent review result：6 项 capability（Minimal Runtime Kernel、MCP、Memory、
  Scheduler、Skill、TUI）满足 `locally-verified`；SubAgent 保持
  `implemented-candidate + safe-unavailable + E3-blocked`。
- Reviewer-owned `--content` rerun observed before this receipt was written：exit 0；
  `347 passed`、`ALL CHECKS PASSED`（未截断，deny-network 边界内）。
- Capabilities approved for `locally-verified`：Minimal Runtime Kernel、MCP、Memory、
  Scheduler、Skill、TUI。
- Capability remaining `implemented-candidate + safe-unavailable + E3-blocked`：SubAgent。
- E3 status：all pending（无 `accepted`）。
- Control state updated by reviewer：`CURRENT_CAPABILITY_STATUS.md`（晋级 + 重封）、
  `G0_G6_CLOSURE_EXECUTION_LOG.md`（残留段同步）、本文件（新增 post-review-receipt），
  manifest 的 control digests 与 `seal_state` 同步重封。
- Manifest control digests updated：yes。
- Control seal authorized after all control digests freeze：yes。
- Repository mutated after successful control seal：must be no。

`--control-seal` 的 exit code 与未截断 summary 在仓库外（review summary）报告；写入本文件
会使其 sealed digest 失效。
