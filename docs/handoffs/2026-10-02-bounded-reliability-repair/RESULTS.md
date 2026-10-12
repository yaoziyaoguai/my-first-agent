# 本轮唯一执行记录

> 2026-10-09 交接说明：此文件从现在起保留为 10月2–5日的历史执行/自评记录，不再是下一轮工作入口。
> 当前有限修复入口为 [日用闭环修复包 START-HERE](../2026-10-09-daily-use-closure/START-HERE.md)，唯一新执行记录为该包 RESULTS。
> 下方 B03/B12/B13 等旧 PASS 不覆盖 [10月9日独立审计](../../audits/2026-10-09-agent-product-readiness-review.md) 的新反例；原始成绩与失败记录均保留，不改写历史。

## 当前状态

- 首轮修复已有实际实现；2026-10-03 独立复核后状态：**IMPLEMENTED_PARTIAL_VERIFICATION**，暂不接受完整 LOCAL_VERIFIED。
- F2 正常收尾主链、F4 顺序归档修复可保留；F1 多验证生产收尾和 F3 实际 runner 接线尚有已复现缺口，另有退出/驱动清理与测试补证小项。
- 当前用户请求：审计执行者自述并准备下一步执行包，先能用、不扩大范围；本次未实施新的产品修复。
- 下一步唯一入口：[FOLLOWUP-2026-10-03.md](FOLLOWUP-2026-10-03.md)，独立证据见 [AUDIT-2026-10-03.md](AUDIT-2026-10-03.md)。
- follow-up 产品实施：**DONE（2026-10-04）**——R1/R2/R3 + A20 补证完成，B01–B16 全 PASS，全量 gate 3673 passed / 1 skipped / 0 failed；真实模型 Dogfood 仍 NOT RUN—未授权。本节执行表已更新；首轮历史记录保留不动。
- 总体能力状态仍见 `docs/architecture/CURRENT_CAPABILITY_STATUS.md`；此文件只管理本包 F1–F4/L1，不是第二份全项目状态表。

## 2026-10-03 follow-up 当前执行区

下方“首轮执行者记录”保留原始自评和首次失败；其全部 PASS/无阻塞声明已由本节和独立审计校正，不能继续当作当前结论。

| 工作项 | 当前状态 | 实际修改 / Red / Green / 剩余边界 |
|---|---|---|
| R1 多项验证生产闭环 | DONE（2026-10-04） | 三处生产缺口修复：sandbox oracle `receipt_digest` 可选（批准时义务可铸造）；state.py 新增 read-only sandbox 审批准入 `_admit_approved_read_only_validation_criterion` + 结果时 `admit_sandbox_receipt_criterion`；loop.py 结果准入接线；`SandboxAuthorityCandidateV1` digest 移除 issued_at（审批后重 prepare 不再永久 miss lease；timeout 变更仍重批，shell 回归保持）。B01 Red 过程两次失败如实记录（固定批准时刻早于真实时钟；candidate digest 漂移），均为真实缺陷并修复 |
| R2 runner/validator 贯通 | DONE（2026-10-04） | `_load_final_state` 改经 `inspect_workspace_sessions`（真实 `workspaces/<scope>/` 布局，错绑/零/多失败）；required checks 全集由 manifest 构建、缺项 false+reason；相关测试证明必须经 `ClosedEvidenceRegistry.derive` 从 durable facts 重验（孤立记录/旧 Goal receipt fail closed）；preflight 补批准预算↔max-model-attempts 耦合与 wall 预算；validator 补 external_grader_runs≥1、ledger 差值==physical_requests、model_identity 非空且 real 时与 manifest 一致；新增 `--provider fake` 离线脚本模式与 run→validator 实际贯通测试（正例 completed 两端一致；业务正确未测试反例 incomplete） |
| R3 退出/驱动收尾与补证 | DONE（2026-10-04） | adapter.shutdown 仅在 worker 已退出时跳过向 unusable session 重发 close（poisoned+alive 仍清理）；journeys 脚本两代资源 ExitStack + `--budget-seconds` 真实有界停止（worker 线程 join timeout）+ D06 分层证据；清扫移出只读加载（仅 startup/restore 写路径清扫）；A20 重写为真实 try_acquire open→flock 边界 shim 暂停 + 置换 + 重验拒绝 + mutation check |

| 验收 | 结果 | 实际 node/命令、首次失败、最终退出码与证据 |
|---|---|---|
| B01 | PASS | tests/process/test_r1_two_validation_completion.py::test_r1_two_read_only_validations_complete_via_real_runtime——真实 AgentRuntime + open_workspace_session + seatbelt sandbox_exec；两个明示入口经批准/执行/结果准入产生 ≥2 个不同 fingerprint 的 native_sandbox_v1 mandatory criteria → VERIFIED_DONE；无手填 criterion |
| B02 | PASS | 同文件 ::test_r1_resume_between_validations_still_completes——验证 A 后经生产 open_workspace_session 重开（RESUMED），义务/租约随 durable state 恢复并完成 |
| B03 | PASS | 同文件 ::test_r1_midchain_write_keeps_invalidation_and_blocks_completion——两验证间真实受治理 write_file → 旧证据失效 → 完成被挡；A01/A02 focused 42 passed 不回退 |
| B04 | PASS | 同文件 ::test_r1_old_process_obligation_not_substituted_by_sandbox_receipt——旧 process_v1 义务不被 sandbox receipt 变造；backend 缺失 fail closed 由既有 qualification 套件保持 |
| B05 | PASS | tests/acceptance/test_f3_driver_typed_status.py（真实布局迁移）+ inspect_workspace_sessions 错绑/零/多失败路径 |
| B06 | PASS | tests/acceptance/test_f3_runner_roundtrip.py——实际 run()（--provider fake，替身只换 provider）→ 实际 validator：completed 正例两端一致；业务正确未测试反例 incomplete 且记录可消费 |
| B07 | PASS | tests/acceptance/test_f3_driver_receipts.py——通过必须经 ClosedEvidenceRegistry.derive 从 durable facts 重验；孤立 passed 记录（::test_f3_old_goal_receipt_is_not_reusable，修正为 False）与空 facts fail closed；R1 真实链可过 |
| B08 | PASS | tests/acceptance/test_f3_record_contract.py::test_f3_runner_refuses_dispatch_before_any_provider_send（spy 0 calls）+ preflight 预算耦合（批准 1 配 30 / wall=0 拒绝） |
| B09 | PASS | 同文件 ::test_f3_bad_records_fail_closed + validator 新一致性（external_grader_runs≥1 / ledger 差值==physical_requests / model_identity 非空且 real 时与 manifest 一致；offline 不伪标 real） |
| B10 | PASS | tests/acceptance/test_coding_autonomy_grader.py——D04/D05 过程项保持 false+理由；required checks 未减少 |
| B11 | PASS | tests/browser/test_browser_cleanup.py::test_shutdown_does_not_reclose_unknown_session_to_dead_worker——0.15s 超时下 <0.5s 返回、page.close 恒 0 次、UNKNOWN 保持；poisoned+alive 回归保持 |
| B12 | PASS | journeys 脚本两代资源 ExitStack（单 cleanup 失败不跳过其余、异常聚合不吞）；清理失败不签 passed |
| B13 | PASS | journeys `--budget-seconds` 为 worker 线程 join(timeout) 的真实有界停止（超时如实记 timeout；临时资源仍由 ExitStack 清理） |
| B14 | PASS | tests/continuity/test_f4_lock_accumulation.py::test_f4_acquirer_paused_before_flock_rejects_swapped_lock——真实 try_acquire open→flock 边界 shim 暂停 + 置换 + post-flock inode 重验拒绝旧 fd + mutation check（移除重验 ⇒ 错误签发）；12 轮容量/恢复合同保持（continuity 473 passed） |
| B15 | PASS | `scripts/f2_f3_local_browser_journeys.py --journey all` exit 0（修复后驱动：F2 重启补记 + D06 提交/读回/清理；工具 receipts / 观察层 / 业务层分列） |
| B16 | PASS | 本节声明校正：旧版本混跑非自动安全（重验只保护新版进程，升级前须退出旧进程）；清扫只在写路径（startup/restore），只读加载/inspect 不清扫；原 A03 为 oracle 层证明、以 B01 生产证据补足；原 A11 断言按 R2c 收紧 |

复核时实际运行：acceptance 32 passed（8.18s）；F1/F4 新测试文件 8 passed（2.49s）；F2/cleanup/composition/unknown recovery 34 passed（131.91s）；归档 100 轮正常；Ruff/diff-check 通过。额外反例仍失败，故这些计数不代表本包完成。
本次未为重复计数再跑全量，未独立重跑真实 Chromium/wheel，未调用付费 provider；这些边界见审计原文。

执行者完成 follow-up 后在本节更新最终 source gates、真实本地旅程、适用安装 smoke 与真实模型 NOT RUN 的分层结论，不覆盖下方首轮历史。

### follow-up 最终分层结论（2026-10-04）

- 分级：**IMPLEMENTED_LOCAL_VERIFIED（follow-up 范围内）**——B01–B16 全 PASS；R1 日常多验证生产收尾打通（B01 真实 AgentRuntime + seatbelt sandbox 双验证 VERIFIED_DONE）；R2 runner→validator 实际贯通且两端一致；R3 退出/清理/截止修复。
- source gates：`git diff --check` exit 0；`.venv/bin/ruff check .` 通过；全量 `pytest -q -rx`：**3673 passed / 1 skipped / 0 failed（434.45s，exit 0）**。
- 真实本地旅程：`scripts/f2_f3_local_browser_journeys.py --journey all` exit 0（修复后驱动，120s 预算内，ExitStack 清理；工具/观察/业务三层证据分列）。
- 安装 smoke：未在本轮重复（原 wheel 流程已验证且本轮未触打包配置；如需交付安装版按原 ACCEPTANCE §4 复跑窄 smoke）。
- 真实模型 Dogfood：**NOT RUN—本包未授权**（原包与 follow-up 均未授权；后续仅在用户明确授权后选一个代表任务做最小真实验证）。
- 保留边界：外部/并发同 UID 写入、旧版本进程混跑（升级前须退出旧进程，重验只保护新版进程）、F3 相关性判定的保守 fail-closed、调度入口未接线。
- 审计遗留校正已落实：不再声称"只读加载执行清扫"；不再声称"旧版本混跑自动安全"。

### 真实模型 Dogfood（2026-10-04，用户明确授权后执行）

- 授权与凭据：owner 在对话中明确授权并仅提供 DeepSeek key；授权/预算/模型按产品授权门要求记录进 `TASK-MANIFEST.json`（real_dispatch_authorized=true、40 请求/1800s wall、model=openai_compatible/deepseek-v4-flash/disabled）。key 只经 `DEEPSEEK_API_KEY` 环境变量注入运行进程，未写入仓库、记录或日志；对话中已暴露，建议后续轮换。
- 授权状态连带：4 个断言"manifest 冻结未授权态"的测试按门合同重构——门测试改为对强制未授权的临时 manifest 副本测门（合同不依赖线上授权值）；manifest 冻结断言更新为 owner 当前记录。
- **第一轮（暴露真实缺陷，如实保留）**：D01 全新候选，deepseek-v4-flash，19 请求。业务三项全过（模型真实修复 CSV 缺陷），但运行中崩溃 `ValueError: sandbox lease_id must be unique`——同一验证命令第二次批准（修复后重跑的正常路径）铸造同 id lease 撞状态唯一性不变量，并连锁 fatal 持久化失败 → 记录 `incomplete`（product_ran_related_tests=false，typed 链成立地拒绝了未完成的完成）。validator：RECORD_VALID/real_model/incomplete（诚实记录可消费）。
- **修复**：`_mint_process_authority_lease`/`_mint_sandbox_authority_lease` 的 lease_id 绑定批准请求身份（每次批准一条新租约；容量上界与不变量保持）；状态级回归测试 `test_r1_second_approval_of_same_command_mints_new_lease`。另修 runner 直接运行时仓库根不在 sys.path 的导入缺陷。
- **第二轮（修复后）**：D01 全新候选，deepseek-v4-flash，**12 请求，product_status=completed**——四项检查全过，`product_ran_related_tests=true`（模型真实运行验证且经 typed 证据链证明），validator `RECORD_VALID/real_model/completed` 零错误零警告。stop_reason 标签语义已在 2026-10-05 修正：typed 达成 VERIFIED_DONE 时记录 `verified_done`，不再让 operator 的 idle 诊断标签覆盖事实（回归断言加入 offline roundtrip 测试）。
- 范围：按包约定单场景最小样本起步；用户 2026-10-05 指示继续后补跑 D02/D06（同预算、同模型、key 只经环境变量）；state/candidate 均为每次新建临时目录。
- **D02（2026-10-05，12 请求）：completed**——五项检查全过（cli_to_service/invalid_format/default_compatibility/tests_and_docs/product_ran_related_tests=true）；validator RECORD_VALID/real_model/completed 零错误。
- **D06 第一轮（暴露第二个真实缺陷，如实保留）**：业务与 managed_server/regression 过，但浏览器链崩溃 `ValueError: browser issued_at must be a zoned RFC3339 string`——产品双时间格式不一致（CLI 审批时钟 "…Z" vs browser binding isoformat "…+00:00"），`_parse_browser_datetime` 的 `value[-6] in "+-"` 误拒 Z 形式，真实审批路径直接崩 → 记录 incomplete。修复：接受两种 zoned RFC3339 形式（agent/runtime/contracts.py）；回归测试 `test_browser_lease_accepts_product_clock_z_format`；browser 套件 384 passed。
- **D06 第二轮（修复后，23 请求）：completed**——四项检查全过（managed_server/browser_behavior/regression/**owned_resources_closed=true**：真实模型的 start/open/act/close/stop 资源治理链闭环）；validator RECORD_VALID/real_model/completed 零错误。
- 本轮执行中的偏差如实披露：B01 调试期间两次失败（测试时钟精度、candidate digest 漂移）均定位为真实缺陷并修复；journeys 脚本一次 NameError 由引用 driver-side helper 造成，修复后实跑通过；RESULTS 首轮区为审计者重写版本，本轮只更新 follow-up 区，不覆盖历史。

### 编包验证

2026-10-03 编包检查：follow-up 的 18 个公开输入指纹全部匹配；审计/执行入口/RESULTS 的 5 个本地 Markdown 引用全部存在；B01–B16 共 16 项无重复；代码围栏、行尾空白、换行及明显凭据形状检查通过；`git diff --check` exit 0。
一次独立 scoped 文档复核未发现必须修改项，确认没有把 R1 扩成新框架，也没有要求重写 F4。
本次仅新增审计、follow-up 入口/指纹并更新此记录，没有产品/测试改动。以上是编包检查，不是修复后产品验收。

## 执行起点核对（2026-10-02，执行者）

- `git rev-parse HEAD` = `838cb2b66fbba674311d4d86fc7c4f4322fd8612`，与审计 HEAD 一致。
- `shasum -a 256 -c .../BASELINE.sha256`：29 个公开相关文件全部 `OK`，exit 0。
- `git status --short --branch`：`main...origin/main [ahead 7]`，134 tracked 修改 + untracked 条目，与编包记录一致。既有 dirty/untracked 全部保留。
- 结论：基线匹配，按当前工作树直接实施。

## 审计基线（历史事实，不是修复后的成绩）

HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`。分支 main，相对缓存 origin/main ahead 7。
编包前 134 tracked 修改文件，11,333 additions / 900 deletions，26 untracked 状态条目（含目录）。未 fetch。

| 2026-10-02 检查 | 结果 | 限制 |
|---|---|---|
| git diff --check | exit 0 | 非产品正确性证明 |
| ruff check . | exit 0 | 非功能证明 |
| 全量 pytest（当时受限 sandbox） | 3586 passed / 30 failed / 12 errors / 11 skipped，382.38 秒 | 不能签全绿 |
| 上述失败/报错覆盖项宿主复查 | 73 passed，40.74 秒，exit 0 | 环境限制项恢复；不是再次同环境完整全量 |
| 架构与 browser approval focused | 71 passed，40.61 秒 | 不覆盖本包全部新反例 |
| F1/F4 局部旧测试 | 110 passed | 旧测试通过但审计组合反例成立 |
| 验收设施局部旧测试 | 16 passed / 2 deselected | 不代表真实 provider 或完整场景通过 |

宿主复查命令：

```bash
.venv/bin/python -m pytest -q -ra --color=no tests/browser/test_profile_store.py tests/process/test_managed_web.py tests/sandbox/test_network_only_macos.py tests/sandbox/test_packaged_policy_real.py tests/skill/test_executable_tools.py::test_real_seatbelt_executes_declared_entrypoint_via_trusted_application_runtime
```

旧本机临时日志（可已被系统清理；不是包的必需输入）：
`/private/tmp/first-agent-audit-20261002-pytest.log`、`/private/tmp/first-agent-audit-20261002-host-recheck.log`。
这是本次测试产生的合成日志，不授权打开用户其他真实日志。

审计已复现：成功 process 写后旧 readback 仍支持 verified_done；fake-production browser 新 owner 无法 close 旧 ref；验收文字/审批/候选空测试误判；容量 2 下归档锁累积使第 6 轮失败。
F2 尚不是 fresh Chromium 复现；本包要求后续同时补本地真实验证。没有本轮真实 API 调用。

## 执行包编制检查（不是产品验收）

- 本包共 5 个文件；12 个本地 Markdown 引用均可解析，代码围栏与文本换行检查通过。
- A01–A22 共 22 个独立验收编号，无重复。
- `shasum -a 256 -c docs/handoffs/2026-10-02-bounded-reliability-repair/BASELINE.sha256`：29 个选定公开输入全部匹配，exit 0。
- `git diff --check`：exit 0；另检查本包未跟踪文本的行尾空白与结尾换行，未发现问题。
- 一次独立 scoped 文档复核未发现必须修改项：范围、真实 API 禁止/本地 Chromium 允许、安装 smoke 和未完成状态一致。
- 编包只新增本目录文档与指纹文件，未修改产品/测试、未运行付费调用、未 commit/push。
- 不重跑产品测试来验证纯文档包；上方测试结果仍是审计时历史，后续实现必须产生新的证据。

## 首轮执行者记录（历史自评，当前结论以上方独立审计为准）

在此维护最新状态，保留上方历史基线。不要把 NOT STARTED 改为 PASS 后丢掉首次失败。

| 工作项 | 状态 | 实际修改/选择 | Red node 与失败 | Green/回归与证据 | 剩余边界 |
|---|---|---|---|---|---|
| F1 | IMPLEMENTED（focused Green） | 选定机制：收紧 `ClosedEvidenceRegistry._may_invalidate_workspace_validation`（agent/runtime/evidence.py:1383）。已执行（executed=True）的 same-UID process receipt 无条件失效其前的验证证据（成功/失败/超时同权；成功退出≠无写入）；read-only+confined native sandbox 例外保留（host 实际隔离，runtime 铸 receipt 时强制 enforcement matrix，非模型自报）；未执行（policy 拒绝、spawn_failed）不失效。共存机制：未沙箱 receipt 不再有"共存"合同；同一可信输入多项验证的可证明路径 = read-only native sandbox。旧正向合同 `test_015_successful_validation_processes_can_coexist_without_workspace_write` 前提即审计缺陷，已重写为 `test_015_unsandboxed_validation_processes_no_longer_coexist_read_only_sandbox_does`（断言先前验证被后续执行失效、最后执行者仍有效=有限步路径存在）。未改 loop/contracts/checkpoint | `tests/process/test_f1_input_mutation_invalidation.py::test_f1_successful_process_rewriting_readback_artifact_blocks_completion`（A01，真实 composition+KernelToolRuntime+真实改写 shell，fix 前得到 VERIFIED_DONE）；`::test_f1_successful_validation_then_input_rewriting_process_invalidates_validation`（A02，DID NOT RAISE）；`::test_f1_unsandboxed_validations_no_longer_coexist_conservatively`（DID NOT RAISE）。3 failed / 2 passed（2026-10-02） | 新文件 5 passed；focused 四文件 61 passed（含重写后的旧合同）；tests/process+tests/continuity+tests/kernel 全量 975 passed（53.44s）。命令与退出码见执行日志 | 外部/并发同 UID 写入不可观测，属保留边界（FIX-PLAN 已声明不声称主机并发一致性）；unknown-outcome 事实不携带 receipt，由 loop 既有 unknown recovery 拦截，derive 的 EXECUTING 拦截不变 |
| F2 | IMPLEMENTED（focused Green） | 选定机制：owner shutdown 持久化最小可信闭合凭据 + 重启补记。`agent/browser/tools.py`：新增 `BrowserToolBundle.owner_shutdown` 与 `_BrowserTools.owner_shutdown()`（逐 session 底层 close receipt → CLEANED 且无 pending recovery 才把 session ledger 落 CLOSED 并释放 site writer lease；UNKNOWN/未决/ledger 拒绝 fail closed）；`close()` 与 `prepare_session()` 增加 durable-ledger 补记回退（仅接受 CLOSED + browser identity 全等；其他 session/损坏 ledger/过期 identity/未知 session 一律 fail closed，补记 metadata 带 `closure_basis=durable_ledger_closed`）；`agent/browser/ports.py` 补 `shutdown()` 端口方法；`agent/composition.py` closeables 从 `environment.shutdown` 改为 `tools.owner_shutdown`（先逐 session 关闭+凭据，后 worker 收尾）。resource_lifecycle 无需改动（cleaned close fact 即解除门槛） | `tests/browser/test_f2_owner_shutdown_outclosing.py` 5 failed / 1 passed（fix 前；含 composition 级 A05 与 worker-alive fail-closed 回归） | 6 passed（A05 单元级 + composition 级 + A06 负例×3 + A07 幂等/writer 释放）；F2 focused 四文件 63 passed（79.84s）。实际命令见执行日志 | SIGKILL/断电/凭据落盘前崩溃仍 UNKNOWN（无凭据不补记，按冻结承诺）；cleanup UNKNOWN 的 site writer 保持 quarantine；本轮未做真实 Chromium 旅程（A08 记 NOT RUN，待最终集成阶段） |
| F3a | IMPLEMENTED（focused Green） | 选择：driver 完成判定只认 typed 终态——`_load_final_state`（本次驱动合成的唯一 session checkpoint，`LocalCheckpointStore`）+ `_typed_completion`（GoalStatus.VERIFIED_DONE）；`DogfoodOperator` 不再把 "Task is closed." 文案读成完成；`product_ran_related_tests` = 用户权威 `criterion:required-local-process:` 的 passed evidence records（旧任务 receipt/grader 自跑/审批均不算，无 criterion 时诚实 false+reason）；D06 操作证据 = `_managed_web_receipts`/`_browser_executed_facts`/`_resource_closure`（active_task_resources）。`scripts/run_real_coding_scenario.py` 重写；记录含 unverified_reasons | `tests/acceptance/test_f3_driver_typed_status.py` 2 failed→2 passed（Red 为旧 operator 文本签完成合同） | acceptance 目录 32 passed（3.73s）；`test_real_coding_scenario_runner.py` 重写为新合同 | "related" 语义保守：无用户权威 process criterion 时恒 false+reason（不退回 argv 启发式）；真实模型重跑需另行授权（本包 NOT RUN） |
| F3b | IMPLEMENTED（focused Green） | 选择：D06 独立断言冻结在 candidate 外（`tests/acceptance/fixtures/grader/d06_app_behavior.test.mjs`，经 `D06_CANDIDATE` 注入 candidate 路径）；`grade_d06` 真实启动 candidate `server.py`（loopback GET / 200 核验）+ 运行冻结 node 测试；candidate 自带 tests 不参与判定；Node 结果只签 JS 行为（managed_server/regression），产品 browser 证据由 driver 从 durable receipts 取得 | `tests/acceptance/test_f3_grader_freeze.py`：缺陷 fixture browser_behavior/regression=false；坏 server.py → managed_server=false；候选空测试不改独立结论；修复参考全绿 | 4 passed（0.94s） | 独立真实浏览器旅程（A13）属最终集成阶段；本轮不建第二套浏览器控制器 |
| F3c | IMPLEMENTED（focused Green） | 选择：D04/D05 过程项（resume_without_restatement/no_effect_replay；nested_instructions/search_after_truncation/protected_paths_unread）恒 false + `unverified_reasons(scenario_id)` 理由；保留全部 required_checks 不删项不降门槛；业务项（latest_correction/final_validation/precedence_matrix）照常如实判定 | 既有 D04/D05 参考测试改为业务 true + 过程 false 断言（旧合同曾以文件存在性自证过程项） | grader acceptance 16 passed（1.96s） | 过程观测旅程（correction/resume/secret-read instrumentation）本轮不建设 |
| F3d | IMPLEMENTED（focused Green） | 选择：记录 schema 2——`build_record_v2`（16 键 exact：+fixture/source/grader identity、unverified_reasons、stop_reason、schema_version、model_identity；metrics +ledger_start/ledger_end）；validator `grade_coding_autonomy.py` 同步 exact key set，RECORD_VALID 只证明记录合同（一致性校验 completed_without_basis；救场度量为正降级为 warning），不等于产品 PASS；physical_requests=ledger_end-ledger_start；runner 在任何 provider 发送前核对 manifest 授权/预算/模型配置/凭据存在，不匹配即 SystemExit（本轮不修改 manifest 授权状态） | `tests/acceptance/test_f3_record_contract.py` 4 passed；A17 spy transport 0 calls（拒绝路径零 provider 触碰）；既有 validator 测试更新到 v2 合同 | acceptance 32 passed | manifest 授权/预算/模型由 owner 决定记录，本轮不打开；真实模型记录 NOT RUN—本包未授权 |
| F4 | IMPLEMENTED（focused Green） | 选择：容量与锁残留分离 + 有界清扫 + post-flock inode 重验。`agent/continuity/sessions.py`：`_load_candidates` 移除与容量混算的 `max*3+1` 枚举上界，改为两条显式上界（checkpoint ≤ max_history_checkpoints 不变；锁条目 ≤ max+`_MAX_LOCK_RESIDUE`(32)，超界 fail closed）；新增 `_sweep_retired_locks`（≤32/次）：每个孤儿锁 open→flock LOCK_EX|LOCK_NB→重验 pathname↔fd inode/设备一致才 unlink+fsync，忙碌/被替换的锁跳过；布局不变，不迁移旧合成布局。`agent/runtime/checkpoint.py`：`try_acquire` 在 flock 持有后重验 pathname↔fd inode/设备，不一致（清扫/重建后凭旧 inode）fail closed 返回 None。边界说明：升级混跑时，持有旧锁 inode 的旧版本进程只能 fail closed 重试（当前 pathname 串行化）；本实现不停止任何用户进程；等待者-清扫者-恢复者之间以 inode 重验串行化（A20 受控并发反例证明无 split-lock） | `tests/continuity/test_f4_lock_accumulation.py::test_f4_capacity_two_supports_at_least_12_archive_rounds`（A18，Red：`workspace state enumeration exceeds its bound`，sessions.py:637） | 3 passed（A18 12轮+恢复/digest 保持、A19 symlink/mode fail-closed、A20 fork+pipe 无 split-lock）；tests/continuity 全量 473 passed（10.98s）；kernel/process/browser/sandbox/automation 1371 passed（216.62s） | 极长寿命进程反复持有忙碌孤儿锁时靠 32+max 上界 fail closed（明确资源边界，不推迟）；等待者持旧 inode 跨恢复的场景由 post-flock 重验串行化，旧版本混跑需退出（已记录） |
| L1 | VERIFIED（文档核对，无代码改动） | `agent/automation/cli.py` 仍 `core=None` fail-closed（needs_019_config / host_profile_unavailable，exit 2）；README §Scheduler/Durable automations 与 `docs/architecture/CURRENT_CAPABILITY_STATUS.md` 已准确声明非开箱即用、不创建登录项/launchd、019 host profile 未对当前 identity 绑定，无需修改文档；本 RESULTS 不把调度/安装态称作开箱即用；未 promotion、未注册登录项 | — | 文本核对（2026-10-03），无新测试 node | 继续保留 macOS-first 沙箱、隔离 Chromium、受限扩展能力、candidate 等级；真实 API 未重跑与安装态分别记录 |

### 验收映射（2026-10-03 填写；全部 node 在本轮实际运行）

| ID | 结论 | 实际 node / 命令 | Red→Green | 证据/限制 |
|---|---|---|---|---|
| A01 | PASS | tests/process/test_f1_input_mutation_invalidation.py::test_f1_successful_process_rewriting_readback_artifact_blocks_completion | Red：fix 前得到 VERIFIED_DONE（3 failed / 2 passed，2026-10-02）；Green：5 passed | 真实 composition + KernelToolRuntime + 真实改写 shell；生产 /approve-artifact 路径 |
| A02 | PASS | 同文件 ::test_f1_successful_validation_then_input_rewriting_process_invalidates_validation | 同上 Red | derive 级，生产 receipt 形状 |
| A03 | PASS | 同文件 ::test_f1_read_only_sandbox_validations_coexist_on_same_trusted_input、::test_f1_unsandboxed_validations_no_longer_coexist_conservatively；tests/process/test_j1_verified_done.py::test_015_unsandboxed_validation_processes_no_longer_coexist_read_only_sandbox_does（重写） | 旧正向合同在 fix 后必失败（其前提即审计缺陷），已重写 | read-only sandbox 共存 + 未沙箱保守失效双证 |
| A04 | PASS | 同文件 ::test_f1_unexecuted_rejection_and_spawn_failure_preserve_validation | — | 拒绝/spawn_failed 不误伤；失败/超时失效；read-only 例外保留 |
| A05 | PASS | tests/browser/test_f2_owner_shutdown_outclosing.py::test_f2_normal_shutdown_then_new_owner_outcloses_old_ref、::test_f2_composition_shutdown_then_new_owner_outcloses_old_ref | Red：5 failed / 1 passed（owner_shutdown 缺失、outclose 失败） | 单元级 + composition 级（fake factory）双证，非只测 helper |
| A06 | PASS | 同文件 ::test_f2_unknown_shutdown_leaves_no_credential_and_outclose_fails_closed、::test_f2_corrupted_ledger_and_wrong_identity_and_unknown_session_fail_closed | — | unknown/损坏/过期 identity/未知 session/异 root 全 fail closed |
| A07 | PASS | 同文件 ::test_f2_repeated_outclose_is_idempotent_and_writer_released | — | 重复 close 幂等、无 reopen/二次物理 close；site writer 正确释放 |
| A08 | PASS | `.venv/bin/python scripts/f2_f3_local_browser_journeys.py --journey f2`（exit 0） | — | 真实专属 Chromium + 真实 shutdown CLEANED + 新 owner 补记；`--journey all` 复跑通过 |
| A09 | PASS | tests/acceptance/test_f3_driver_typed_status.py（2 tests） | Red：旧 operator 文本签完成合同（fix 前 fail） | 文本/CANCELLED 均不能判完成 |
| A10 | PASS | tests/acceptance/test_f3_driver_receipts.py::test_f3_approval_only_is_not_executed_test | — | 审批记录不可能构成 VERIFIED_DONE state（state 不变量） |
| A11 | PASS | 同文件 ::test_f3_executed_success_in_current_goal_passes、::test_f3_old_goal_receipt_is_not_reusable + driver product_ran_related_tests fail-closed 理由 | — | 用户权威 process criterion passed evidence；无 criterion 诚实 false |
| A12 | PASS | tests/acceptance/test_f3_grader_freeze.py（4 tests） | — | 缺陷 fixture/坏 server/候选空测试均不能骗过冻结独立断言 |
| A13 | PASS | `.venv/bin/python scripts/f2_f3_local_browser_journeys.py --journey d06`（exit 0） | 首跑 passed=false（真实读回暴露 ARIA li 无文本），修正判定（li 计数）后通过；如实记录 | 真实浏览器提交→列表更新（li 1→2）→browser_close cleaned→managed_web_stop confirmed；产品 receipt 与独立断言分离 |
| A14 | PASS | tests/acceptance/test_f3_d06_resource_evidence.py（2 tests） | — | exact start/stop+open/act/close 正向可过；缺 cleanup/UNKNOWN 不过 |
| A15 | PASS | tests/acceptance/test_coding_autonomy_grader.py（D04/D05 过程项断言更新） | 旧合同曾以文件存在性自证过程项（重写 3 个测试） | required_checks 保留不降门槛；unverified_reasons 理由齐全 |
| A16 | PASS | tests/acceptance/test_f3_record_contract.py::test_f3_producer_validator_roundtrip_valid、::test_f3_bad_records_fail_closed | — | schema 2 round-trip；缺字段/错 manifest/错身份/完成无依据准确失败；RECORD_VALID≠PASS |
| A17 | PASS | 同文件 ::test_f3_runner_refuses_dispatch_before_any_provider_send | — | spy transport 0 calls；未授权/零预算/模型不匹配/缺凭据全部发送前拒绝 |
| A18 | PASS | tests/continuity/test_f4_lock_accumulation.py::test_f4_capacity_two_supports_at_least_12_archive_rounds | Red：`workspace state enumeration exceeds its bound`（sessions.py:637） | 容量 2 下 12+ 轮 create/archive；早期 archive 可恢复 digest 保持 |
| A19 | PASS | 同文件 ::test_f4_unsafe_lock_entries_still_fail_closed | — | symlink/错 mode 锁仍 fail closed；容量满额拒绝由既有 retirement 测试保留 |
| A20 | PASS | 同文件 ::test_f4_stale_inode_holder_cannot_gain_contradicting_lease | — | fork+pipe 受控并发；旧 inode 持有者得 None、当前 pathname 持有者得租约 |
| A21 | PASS | 全量 pytest 3666 passed / 1 skipped；F4 两条显式上界 + F1 read-only 例外保留 | — | 无上限放宽；异常项 fail closed 保留 |
| A22 | PASS | L1 核对（见执行表） + `tests/automation/` 全绿 | — | 未 promotion/注册登录项；调度/安装态声明与证据一致 |

### 最终集成结果

| 检查 | 状态 | 命令/退出码/身份/证据/限制 |
|---|---|---|
| touched-area 集成 | PASS | tests/process+continuity+kernel 975 passed（53.44s）；tests/browser focused 63 passed（79.84s）；tests/acceptance 32 passed（3.73s）；tests/continuity 473 passed（10.98s）；kernel/process/browser/sandbox/automation 1371 passed（216.62s） |
| diff --check | PASS | `git diff --check` exit 0 |
| Ruff | PASS | `.venv/bin/ruff check .` All checks passed（含修复 agent/browser/tools.py 缺失 `SessionNotFoundError` 导入） |
| 完整 pytest | PASS | `.venv/bin/python -m pytest -q -rx`：3666 passed / 1 skipped / 0 failed（595.93s，exit 0；对比审计基线 30 failed / 12 errors） |
| 真实本地浏览器 F2 + D06 | PASS | `scripts/f2_f3_local_browser_journeys.py --journey all` exit 0：F2 重启补记（cleaned + durable_ledger_closed + 凭据落盘）与 D06 提交/读回（li 1→2）/清理（browser_close cleaned + managed_web_stop confirmed）；各自 120s 预算内；临时 workspace/state/profile 于 finally 清理；无真实 provider |
| non-editable wheel 与 import 来源 smoke | PASS | 公开 allowlist staging（pyproject/README/main.py/agent/first_agent_skill_runner，无 ignored/private/tui）构建 `first_agent-1.0.0-py3-none-any.whl`，SHA-256 `d854143d074383c22c74ce711b9a3d59961713f7b6aa458efcfb7010e88f3546`；新建 venv `--no-deps` 安装 + 从 pyenv site-packages 复制明确核对本地依赖（httpx/httpcore/h11/anyio/sniffio/idna/certifi）；源码树外 cwd + 清空 PYTHONPATH：`agent.__file__`/`main.__file__` 均在该 venv site-packages；`first-agent --version`（1.0.0）/`--help` 正常；纯库 smoke（ClosedEvidenceRegistry + active_task_resources）通过；临时 venv/staging 已删除。限制：调度子命令 smoke 未执行（权限边界，保守跳过）；browser extras 未安装于该 venv，如实在此记不可测 |
| 真实模型 Dogfood | NOT RUN — 本包未授权 | 不读取旧 key；真实重跑需用户另行批准（建议 D01/D02/D06 单场样本，按 ACCEPTANCE §5） |
| 独立 scoped 复核 | NOT RUN | 非本包必需检查；未执行，不冒充完成 |

### 实施决定 / 范围外发现 / 阻塞

- 决定（已实施）：F1=已执行 same-UID process 一律保守失效先前验证证据（成功退出≠无写入），tests/lint 共存路径=read-only+confined native sandbox；F2=最小可信闭合凭据=session ledger CLOSED phase（底层 CLEANED 后落盘），补记幂等零调用；F3=typed 完成判定、冻结外置 D06 断言+真实启动核验、D04/D05 过程项诚实 false+理由、记录 schema 2 与 validator exact key set 同步、发送前授权/预算/模型/凭据门；F4=容量与锁残留分离（锁 ≤ max+32 超界 fail closed）+ 孤儿锁有界清扫（flock+inode/设备双验）+ try_acquire post-flock inode 重验。
- 范围外：scheduler 开箱接线、跨平台、新能力、D07–D12 与全部 promotion，均不实施。
- 范围外发现：ports.py 的 BrowserEnvironment 协议补入 shutdown()（composition 原依赖但端口未声明）；run_real_coding_scenario.py 为 untracked，执行中被执行者误覆盖后按会话内原文完整重写（F3 修改叠加其上，基线检查在其覆盖前已记录通过）；wheel smoke 的调度子命令检查因权限边界保守跳过；D06 journey 首跑 passed=false（ARIA li 无文本）如实记录后修正判定（li 计数）再通过。
- 阻塞：无。

### 首轮最终交付摘要（原自评保留；完整 LOCAL_VERIFIED 已被独立复核降级）

- 分级：**IMPLEMENTED_LOCAL_VERIFIED**（A01–A22 全 PASS；required local/full/wheel smoke 通过；含两条真实本地浏览器旅程；真实模型 Dogfood NOT RUN—本包未授权）。
- 实际改动文件：`agent/runtime/evidence.py`（F1）；`agent/browser/tools.py`、`agent/browser/ports.py`、`agent/composition.py`（F2）；`scripts/run_real_coding_scenario.py`、`scripts/coding_scenario_grader.py`、`scripts/grade_coding_autonomy.py`（F3）；`agent/continuity/sessions.py`、`agent/runtime/checkpoint.py`（F4）。
- 新增测试/驱动：`tests/process/test_f1_input_mutation_invalidation.py`、`tests/browser/test_f2_owner_shutdown_outclosing.py`、`tests/acceptance/test_f3_driver_typed_status.py`、`tests/acceptance/test_f3_driver_receipts.py`、`tests/acceptance/test_f3_d06_resource_evidence.py`、`tests/acceptance/test_f3_record_contract.py`、`tests/acceptance/test_f3_grader_freeze.py`、`tests/acceptance/f3_helpers.py`、`tests/acceptance/fixtures/grader/d06_app_behavior.test.mjs`、`tests/continuity/test_f4_lock_accumulation.py`、`scripts/f2_f3_local_browser_journeys.py`。
- 重写的旧合同测试：`tests/process/test_j1_verified_done.py` 的未沙箱共存合同（前提即审计缺陷）、`tests/acceptance/test_real_coding_scenario_runner.py`（operator 新合同）、`tests/acceptance/test_coding_autonomy_grader.py`（validator v2 合同 + D04/D05/D06 参考测试）。
- 局限：外部/并发同 UID 写入与旧版本混跑边界按 FIX-PLAN 保留并记录；F3 相关性判定保守（无用户权威 process criterion 即 false+理由）；调度入口 smoke 未执行（权限边界，保守跳过）；独立 scoped 复核未执行。
- 无 commit/push/tag/PR；保留全部既有 dirty/untracked 工作；未读取凭据或真实日志；未调用付费 API；本轮创建的临时 workspace/state/profile/wheel-staging/venv/journey 目录已全部清理。
- 真实模型 Dogfood：NOT RUN — 本包未授权。若后续批准，按 ACCEPTANCE §5：仅 D01/D02/D06 单场样本，由用户确认模型/请求上限/总预算/凭据注入来源后运行。
