# 009 G8 SubAgent Process-Isolated Hard-Deadline Promotion Review

本文件由非 G8/G8.1 实现 executor session 的独立 promotion reviewer 在 G8.1（修复 F-G8-1/F-G8-2）
之后写入。它是把 SubAgent 从 `implemented-candidate + safe-unavailable + E3-blocked` 提升到
`locally-verified`（E3 pending）的 receipt，不是 E3 acceptance，也不覆写历史
`009_INDEPENDENT_REVIEW.md` / `009_G0_G7_PROMOTION_REVIEW.md`。

## Review boundary

- Implementation executor identity/session：G8（引入 `ChildProcessRunner`）与 G8.1（修复 stderr/temp）
  实现 executor。
- Independent reviewer identity/session：独立 reviewer session（Claude Code，未执行 G8/G8.1 实现）。
- Distinct-actor check：pass（reviewer 未实现 G8/G8.1；本 receipt 由独立 session 写入）。
- Review performed at：2026-07-24（G8.1 之后）。
- 工作副本：`my-first-agent-general-loop.FMHzBg`（隔离后继副本；无 git remote；未 commit/push/tag）。
- Real provider / MCP / network calls authorized：no（仅在 deny-network 边界内跑 verifier；子进程 E2
  用受控 fake provider，不发起真实 HTTP）。
- Private / denied content authorized：no。

reviewer 在写 controls 前亲自重跑了 materialized `--content` gate、`--check-membership`、
`--control-seal`、`git diff --check` 与 ruff（见 Final gate rerun）。

## Prior findings 复核（从磁盘，非引用 executor 报告）

| Finding | 修复 | reviewer 验证 |
|---|---|---|
| F-G8-1（child stderr 开 PIPE 从不 drain → >pipe-buffer 阻塞 → 假 UNCONFIRMED） | `stderr=subprocess.DEVNULL`（`process_runner.py:149`）：stderr 直接丢弃到 OS，不缓冲、不阻塞、不进 result | `tests/subagent/test_process_runner.py::test_process_runner_large_stderr_does_not_cause_false_unconfirmed`（128KB stderr）证明仍 TERMINATED、message 不含 stderr marker；DEVNULL 为无限汇，child 不可能因 stderr 阻塞 |
| F-G8-2（per-run temp 目录泄漏，只删 config.json） | `run` finally 先 `config_path.unlink()` 再 `config_dir.rmdir()`（`process_runner.py:108-117`） | `rmdir` 仅删空目录、不递归、不跟随 symlink、精确 per-run 目录；`test_process_runner_temp_dir_removed_after_run` 证明 success 与 deadline-kill 两条路径均无目录残留 |

附加 defense-in-depth：parent 读 child stdout 现有真实字节上界 `_MAX_RESULT_BYTES=8192`
（`_read_bounded`，:172/:271-283），oversized/malformed → None → UNCONFIRMED，且 read 发生在 child
退出/收尸之后，无死锁；由 `test_process_runner_oversized_stdout_is_unconfirmed`（monkeypatch 上界到 4）
与 `test_parse_result_rejects_malformed_and_oversized` 覆盖。

## stderr_chars / 测试 affordance 泄漏审查（任务显式要求）

`ChildProviderSpec.stderr_chars`（`contracts.py:71`）被 `_spec_to_dict` 序列化进 config、被 child
`_spec_from_config` 读出，但其**唯一消费点**是 `_ScriptedFakeProvider.generate`（`runner.py:148-159`），
而该 provider **仅在 `kind=="fake"` 分支构造**（`runner.py:122-123`）。`kind=="http"` 分支
（`runner.py:125-136`）构建真实 HTTP provider，**完全不消费 `stderr_chars`**。

结论：
- **未泄入真实 HTTP 产品行为**——HTTP 子进程不消费该字段，对其零行为影响；`SECRET-STDERR-MARKER`
  等仅存在于 fake provider（受控 double）。
- **非可达危险配置**——spec 在组合根（main.py）按 operator CLI 参数固定构建，模型只能经
  `subagent__delegate(objective, handoff)` 传这两个字段，无法设置 `stderr_chars`；且 HTTP 路径无消费者。
- 与既有 `sleep_seconds`/`fake_text`/`fake_tool`（同在 spec、同仅 fake 路径消费、HTTP 惰性）结构一致，
  属已接受的“fake-kind E2 knob”设计（进程隔离路径无法用真实 HTTP provider 做确定性 E2，fake provider
  作受控 double，process boundary 本身是真实的）。

reviewer 接受该设计；非阻断。建议（非要求）：未来可考虑 MCP 式 test-fixture child script，使 spec
完全不携带测试专用 knob。此为设计偏好，不影响当前 evidence 或安全。

## 其他独立确认（检查清单）

- **唯一 loop**：子进程经 `build_child_runtime` 复用同一 `AgentRuntime.run_turn`；`process_runner`/
  `child`/`runtime_factory` 不构造第二套 loop。架构测试**未被削弱**（`git diff --name-only
  tests/architecture/` vs baseline 为空），`test_subagent_package_does_not_import_provider_or_loop`
  与 effect-owner AST 检查仍强制 `.generate`/`.invoke`/`.compare_and_swap` 仅出现在 `agent/runtime/loop.py`。
- **进程组所有权 + descendant 终止**：`start_new_session=True`，`_kill_group` 用 `getpgid`+`killpg`
  终止整个 group（process_runner.py:144-189）。
- **hard wall-clock + 确认退出 + kill/wait 失败处理**：`monotonic` deadline；SIGTERM→`wait(1.0)`→
  SIGKILL→`wait()`；`_kill_group` 捕获 `ProcessLookupError`/`OSError` 并退回单进程信号。
- **O1 deterministic UNCONFIRMED 保持**：`test_process_runner_deadline_kill_is_unconfirmed`（sleep 5s >>
  deadline 0.5s，真实子进程+真实 killpg）与收紧后的 `test_unconfirmed_receipt_overrides_child_normalization`
  （严格 `=="unconfirmed"`）均通过。
- **credential 不序列化/不记录**：spec 只带 `credential_env_name`（名）；config 不含值；receipt 只含
  status/message（bounded）；argv 仅 config 路径；无 logging。子进程经继承 env 读值。
- **provider timeout vs parent deadline**：`hard_deadline = args.timeout + 10`（main.py:116），socket
  timeout 先于进程 kill。
- **fake vs HTTP 路由**：`receipt_type=="synchronous"`→`ChildAgentRunner`，否则→`ChildProcessRunner`
  （main.py:278-309）；HTTP 缺 `--model`/`--base-url` fail closed。

## Final gate rerun（reviewer-owned，写 controls 前）

- `--check-membership` → `membership ok: 944 entries`（exit 0）。
- `--content` → `non-editable install ok` / `origin ok` / `console entrypoint origin ok` /
  `deny-network enforced via sandbox-exec` / `ruff passed` / `pytest passed (357 passed in 21.87s)` /
  `ALL CHECKS PASSED`（exit 0，未截断）。
- `tests/subagent/` focused → 26 passed。
- `ruff check agent tests scripts main.py` → All checks passed（exit 0）。
- `git diff --check 7d935ac` → 无输出（exit 0）。

## Per-capability promotion

SubAgent 的 fail-closed boundary 与 hard-deadline provider 路径（进程隔离）现已闭合并经独立复核：
F-G8-1/F-G8-2 已解决，stderr/temp/stdout-bound 全部验证，进程组 killpg + 确定性 UNCONFIRMED 保持，
credential 不泄漏，单 loop 与架构约束未削弱。positive E2 经**真实进程隔离路径**（spawn→run_turn→
stdout→exit→TERMINATED；deadline-kill→UNCONFIRMED）完成，fake provider 作受控 double（contract 允许），
hard deadline 由真实进程边界（killpg）提供，不依赖 provider socket timeout。

故 SubAgent 满足 E1/E2/E2M + 独立 review，晋级为 `locally-verified`。其不再 `safe-unavailable`：
`ChildProcessRunner` 自身声明 `process_terminated` deadline contract，使 production HTTP provider
经进程边界获得 honest hard deadline。

| Capability | Final claim | Residual limitation |
|---|---|---|
| SubAgent | locally-verified | E2 经真实进程隔离路径 + 受控 fake provider 证明 hard-deadline/receipt 机制；**真实 HTTP provider in child 为 E3 reference task，pending**（未用真实 provider 跑过）；CLI parity 待 E3 |

其余 6 项（Minimal Runtime Kernel、MCP、Memory、Scheduler、Skill、TUI）保持上一轮 `locally-verified`，
本轮代码变化未触及它们。没有 capability 是 `accepted`（E3 全部 pending）。

## Promotion receipt

- Independent review result：SubAgent 晋级 `locally-verified`（E3 pending）；F-G8-1/F-G8-2 已解决；
  stderr_chars 审查通过（fake-only，无 HTTP 泄漏）。
- Reviewer-owned `--content` rerun observed before this receipt：exit 0；`357 passed`、
  `ALL CHECKS PASSED`（未截断，deny-network 边界内）。
- Capabilities approved for `locally-verified`：SubAgent（本轮）。其余 6 项保持。
- E3 status：all pending（无 `accepted`）。
- Control state updated by reviewer：`CURRENT_CAPABILITY_STATUS.md`（SubAgent 晋级 + 重封）、本文件
  （新增 post-review-receipt），manifest control digests 与 `seal_state` 同步重封。
- Manifest control digests updated：yes。
- Control seal authorized after all control digests freeze：yes。
- Repository mutated after successful control seal：must be no。

`--control-seal` 的 exit code 与未截断 summary 在仓库外（review summary）报告；写入本文件会使其
sealed digest 失效。
