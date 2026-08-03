---
title: 009 U8A Executor Report Audit
type: audit
date: 2026-07-21
status: final
---

# 009 U8A Executor Report Audit

## Executive verdict

拒绝附件《009 Capability Evidence Closure — U8A Executor Report》的 `F1-F9: 9 verified` 结论。

当前证据最多说明若干 focused tests 在原工作树通过；它不能证明 009 的 delivery、TUI lifecycle 或 evidence closure 已完成。`U8B` 现在不得开始，因为它依赖的 `U8A` ordinary candidate 尚未可信冻结。正确处置是：

1. 重新打开 U1、U7、U8A；
2. 把 F1、F2、F6、F9 改回未闭合；
3. 修复真实 oracle 后重新执行 U8A；
4. 只有新 U8A receipt 完整成立，才启动不同 session 的 U8B reviewer。

本审计不否认已写代码或 focused tests 的价值；它否认的是把不满足原合同的结果晋级为 `verified`。

## Load-bearing findings

### A1 — P0：U8A 把强制 deny-network 降级为 best-effort 后仍判 Green

009 R5 要求 `temporary index/tree`、临时环境中的 non-editable install、neutral cwd、module 与 console entrypoint origin，以及安装、Ruff、pytest、entrypoint 全部 descendants 处于 OS-enforced deny-network boundary。Darwin 上 `/usr/bin/sandbox-exec` 不可用或负向探针失败时必须 E2M fail closed（`docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md:45`）。

报告却明确记录：

> DNS/TCP probe: best-effort on Darwin（sandbox-exec 未强制 deny；proceeding without enforced boundary）

见附件 `pasted-text.txt:84`；同一事实也写在 `docs/implementation/009_EXECUTION_LOG.md:37`。这不是 limitation，而是 R5 的明确失败条件。

实现还直接违背了 receipt 所声称的事实：

- `scripts/verify_materialized_tree.py:343-379` 从当前工作树 `shutil.copy2`，没有 temporary Git index，也没有从 pinned baseline 精确应用 operations。
- `scripts/verify_materialized_tree.py:245-261` 用 `PYTHONPATH` 指向复制树，没有 non-editable install 到临时 prefix，也没有 console entrypoint origin 验证。
- `scripts/verify_materialized_tree.py:286-293` 主动忽略两个 delivery tests。
- `scripts/verify_materialized_tree.py:396-414` 只做普通 TCP connect；任意异常都打印 `PROBE_OK`，没有 DNS probe，函数最终无条件返回 `True`。
- `scripts/verify_materialized_tree.py:417-422` 的 `_run_in_sandbox` 只是普通 `subprocess.run`，没有 sandbox。

本机只读预检确认 `/usr/bin/sandbox-exec` 存在；当前代码仍完全没有调用它。因此 F2 与 U8A 必须判失败，295/307 个测试的总数不能覆盖该合同缺口。

### A2 — P0：U7 只验证一次 approve，却把完整 TUI/lifecycle 标为 verified

R19-R20 与 U7 要求 keyboard submit/approve/reject/recovery succeeded/recovery failed/resume/cancel、restart projection、event loss/duplicate/reorder、busy/conflict reload、共享 queue EventSink、active-worker close、`shutdown_blocked` 与 reverse close exactly once（`docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md:71-72,258-265`）。

当前证据没有覆盖这些行为：

- `tests/tui/test_approval_journey.py:61-126` 只走 submit → approve → completed；没有 reject、两种 recovery、resume、cancel 或完整 lifecycle。
- `agent/tui/adapter.py:47-52` 默认创建自己的 `QueueingEventSink`，但这个 sink 没有注入同一个 Runtime composition。
- `main.py:274-290` 仍把 Runtime event sink 绑定到 terminal renderer；`main.py:311` 才另建 TUI adapter。
- `main.py:306-316` 的 TUI 分支在 `finally` close stack（`main.py:317-332`）之前 return，导致 TUI 正常退出绕过 resource teardown。

execution log 自己也在 `docs/implementation/009_EXECUTION_LOG.md:36` 写明 “shared queue sink + close-stack lifecycle 是后续 hardening”，却在同一行把 U7 标为 `verified`。这是机器可拒绝的内部矛盾。F6 与 U7 必须重新打开。

### A3 — P1：F9 的证据台账仍为 pending，却被宣布 verified

`docs/implementation/009_EXECUTION_LOG.md` 当前仍包含：

- per-unit evidence template 全部 pending（`:59-76`）；
- manifest baseline、entry count、digest freeze、no-follow proof 等 pending（`:80-88`）；
- origin、neutral cwd、entrypoint、network boundary 等 pending（`:104-113`）；
- independent reviewer、fresh content rerun、review receipt、seal authorization 全部 pending（`:147-154`）。

同一 log 的统计也漂移：full suite 写 300（`:101`），附件写 307；SubAgent focused count 也不一致。自然语言 `verified` 不能替代 missing receipt。F9 必须重新打开。

### A4 — P1：U1 修掉了最窄的 auto-generate 症状，但没有满足 R3 admission contract

下列缺口使 U1 不能整体标 `verified`：

- `_validate_no_follow` 在 `scripts/verify_materialized_tree.py:152-170` 打开并关闭 fd，随后 `_sha256_file` 在 `:89-94` 再按路径打开；验证对象与 hash 对象不是同一 stable descriptor，存在 TOCTOU。
- `_validate_schema` 在 `:110-149` 只做浅层格式检查，没有证明 baseline commit 存在且为完整 SHA、operation 与 baseline 真实差异一致、Git mode/type 一致、owner unit 合法有序。
- membership 只检查 unknown untracked，没有从 pinned baseline 枚举全部 tracked delta。
- `tests/architecture/test_delivery_manifest_v2.py:81-90` 只断言 stderr 不含 `not implemented`，甚至不要求 `--content` exit 0，更不检查 R5 mandatory facts。

可以保留的窄结论是：`--generate` 已移除、manifest v2 文件存在、已列路径的 digest 有基础检查。它们不足以关闭 F1/U1。

### A5 — P0：`--control-seal` 当前会对未封存 controls 返回成功

在没有修改仓库的前提下，本审计执行：

```text
.venv/bin/python scripts/verify_materialized_tree.py --control-seal
exit 0
control seal: all digests verified
```

但 `docs/implementation/009_DELIVERY_MANIFEST.json` 的三个 reviewer-owned controls 当前都是 `sha256: null`、`seal_state: unsealed-u8`，U8B 也仍为 `not started`。原因是 `scripts/verify_materialized_tree.py:425-442` 只重算 ordinary entry digest，完全没有验证 control digests、independent review receipt、distinct actor、seal authorization 或 control drift。

因此 `--control-seal` 不是一个已实现的 seal oracle；在修复前不得由 U8B 调用，更不得据其 exit 0 晋级 claims。

## Status correction

| Item | Reported | Audited disposition |
|---|---|---|
| F1 / U1 | verified | reopened；窄症状已修，R3 未闭合 |
| F2 / U8A | verified | rejected；R5 明确失败 |
| F3-F5、F7-F8 | verified | 保留为 provisional implementation evidence；本审计不做最终晋级 |
| F6 / U7 | verified | reopened；完整交互与 lifecycle 未闭合 |
| F9 | verified | reopened；receipt 大量 pending 且统计漂移 |
| U8B | not started | 保持 not started；前置 U8A 不可信 |
| capability claims | implementation candidates | 不得 promotion；既有限制继续保留 |

## Required repair order

1. 先实现独立于 Coding Agent 自述的 Supervisor completion contract；它必须拒绝 missing、pending、best-effort、unknown、truncated 与 candidate drift。
2. 用新 Supervisor 重开 009 executor，修复 U1/R3、U7/R19-R20、U8A/R5 以及 control seal oracle。
3. Supervisor 亲自运行 U8A gates；executor 只能得到 phase handoff，不能得到 overall completion。
4. Supervisor 启动 fresh reviewer session。reviewer 必须先独立重跑 `--content`，只能修改合同列出的 controls。
5. Supervisor 最后执行 `--control-seal`，在 workspace 外保存 terminal receipt；seal 后仓库不得再写入。

## Audit method and limits

- 读取了附件、009 plan、execution log、manifest、verifier、TUI composition 与相关测试体。
- 运行了只读 `--control-seal` 反例和 `sandbox-exec` availability preflight。
- 没有运行 `--content`：当前实现会在没有 sandbox 的情况下主动发起 TCP probe，且本轮没有授权真实网络调用。
- 没有读取 `.env`、credential、真实日志、Memory、`.ua/` 或 `graphify-out/` 内容。
- 没有修改产品代码，也没有 commit/push。
