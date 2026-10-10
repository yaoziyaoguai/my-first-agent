# 本轮唯一执行记录：日用闭环修复

## 当前状态

- 日期：2026-10-09（实施轮）；2026-10-10 审计校正。
- 状态：**IMPLEMENTED_WITH_VALIDATION_GAPS**（实施轮完成：S1–S3 落地、DU-01–27 逐行有证据、全量 gate 绿、真实 DeepSeek Dogfood A/B 完成与 C 部分完成；缺口见最终交付摘要与 2026-10-10 审计节）。
- 唯一执行入口：[START-HERE.md](START-HERE.md)。冻结合同：[FIX-PLAN.md](FIX-PLAN.md)；验收：[ACCEPTANCE.md](ACCEPTANCE.md)；审计：[AUDIT-2026-10-10.md](AUDIT-2026-10-10.md)。
- （存史）编包时授权说明：准备执行资料包、当轮无代码修改——已被上方实施轮状态取代。
- 授权变更（2026-10-09，执行者接手时）：用户在最新实施指令中新增**有限真实 DeepSeek API 授权**（预算人民币10元、最多三个代表场景、凭据仅注入 composition root、先离线修复后真实验证）。该授权覆盖 FIX-PLAN §6 与旧条款"真实 API 禁止 / NOT_RUN_UNAUTHORIZED"，但**不扩大其他权限**（仍不 commit/push、不读用户私有数据、不接管用户 Chrome）。真实调用尚未执行，状态记为 **AUTHORIZED_NOT_RUN**；执行时按第五节预算纪律逐次记录。细节见下方"真实 DeepSeek API 授权记录"一节。
- 项目整体 claim 仍为现行 CURRENT_CAPABILITY_STATUS 所声明的 implemented-candidate；本包不是 promotion。
- 编包前证据：2026-10-09 独立审计 143 focused passed、Ruff/diff pass、窄安装 smoke。它们只能证明审计所述边界，不能填下面的修复结果。
- （存史）编包期下一步说明已由实施轮完成；当前下一步见最终交付摘要。

## 有效决定与边界

1. 本轮仅修冻结的三个切片，不按审计的所有候选建议无限扩张。
2. Runtime/evidence/approval/checkpoint 的单一权威保持；advisory/UI 不获得状态修改权限。
3. 真实产品 provider/MCP/外站默认禁止；真实 API 必须新授权、明确费用/请求预算与安全凭据注入。**[2026-10-09 更新]** DeepSeek 真实调用已获有限授权（¥10 上限、三个代表场景上限、先离线后真实），其余边界不变。
4. 既有 dirty/untracked 属于用户；不得丢弃/覆盖、自动 commit/push。
5. 仅使用新建合成 workspace/state/profile；资源 owner 未确认停止/清理时，保留目录、停止后续真实批次并诚实报告。

## 切片进度

| 切片 | 状态 | 当前决定/实际改动 | 下一步/阻塞 |
|---|---|---|---|
| S1 正常复测与安全前台 | IMPLEMENTED (offline) | loop/evidence 三集合折叠（写后合法复测）+ TUI 单飞行/关闭收口/退出码 + CLI heartbeat + 控制窄失败；focused 275 passed | — |
| S2 连续交互与可信结果 | IMPLEMENTED (offline) | 草稿 durable 消费账、流式窗口、UI-04 快照权威、F3/F4 modal、/new 提示；S2 focused 170 passed + 双尺寸（80×24/120×40）Pilot 交互渲染检查 | — |
| S3 验证驱动与交付证据 | IMPLEMENTED (offline) | S3-A/B 驱动器重写+5 tests+真实 f2/d06 旅程 GREEN；S3-C 恢复旅程测试 GREEN（DU-24，含一个真实产品缺陷修复）；S3-D allowlist 完成 | — |
| 最终 full/materialized/复核 | PASS | ruff ✓ / diff check ✓；full pytest 3704 passed / 1 skipped / 0 failed（收口时）；审计复跑 3706 passed / 0 failed（2026-10-10，含其后新增的 2 个双尺寸 Pilot 测试） | — |
| 真实远端模型 | A/B/C 全 PASS（C 于 2026-10-10 二跑按原定义完成） | A 编辑+自验+VERIFIED_DONE ✓；B 审批边界中途纠正+重验+VERIFIED_DONE ✓；C 二跑（.local/dogfood/C2）：S1 在 write 审批边界 /exit（durable AWAITING_APPROVAL=安全边界暂停）→ 全新会话 "Resuming unfinished task"→批准→续做→Verified delivery，notes.txt='paused journey'、check PASS、S1/S2 exit 0、无 CheckpointSecurityError | 首跑（C v3）的 exit=2 缺陷在二跑未复发；可观测性日志已就位 |

## 验收逐行记录

每行填写实际 pytest node/命令、退出码、时间、源码身份/环境和限制；合并运行可引用同一证据，但每条行为必须有对应断言。

| ID | 状态 | Red 证据 | Green /实际 node 或命令 | 限制 |
|---|---|---|---|---|
| DU-01/07 | PASS | B03 重写 Red：`executed_ids` 仅 `[mutate-mid, validate-a, validate-b]`（复测被 duplicate 抑制） | `tests/process/test_r1_two_validation_completion.py::test_r1_midchain_write_allows_fresh_revalidation_then_completes`：写后 A/B-2 真执行、仅 B 复测时 `completion_not_verified`（缺 A）、A-2 后 VERIFIED_DONE、evidence 引写后 receipt fact | 读回须含 write read-back（approved-write criterion 为产品既有语义） |
| DU-02/03 | PASS | — | `tests/kernel/test_validation_request_freshness.py` 7 tests：伪造/缺失/投影不符/非 confined/network-full/绑定不符均不进可信分类；A/B 共存、写后清空、operator mutation 失效、拒绝无 credit、fold 纯函数 | 单元层；生产链证据见 DU-01 |
| DU-04 | PASS | — | 同上 fold tests（operator 已执行 mutation 清 native_validation；失败/非零退出同样清空）+ F1 回归 10 passed | — |
| DU-05 | PASS | — | fold 纯函数测试 + B02 reopen 回归（R1 全文件 5 passed）+ compaction 回归（142 passed） | — |
| DU-06 | PASS | — | 既有 kernel 回归全绿：approval/recovery/limits + continuity goal_controls（S1 focused 142 passed，全量 gate 内）；exact replay/lease/unknown 语义本包未改动，由既有断言持续覆盖 | 语义未改动项以既有回归为证 |
| DU-08 | PASS | — | `tests/tui/test_app.py`：busy 簿记/单 timer/deadline 非 latch/关闭期禁新 action | — |
| DU-09 | PASS | — | 同上：worker 错误退出码 2、reload 失败禁用+单次重试、shutdown_blocked 转 display-only | 视觉确认未做（逻辑断言为准） |
| DU-10 | PASS | — | `busy_control_request_without_inbox`（请求未发送提示、不崩溃）+ adapter narrow error tests（TUI 81 passed） | 绑定更换反例已补（2026-10-10 修复轮）：test_control_submit_rejected_when_displayed_binding_was_replaced——display 与 submit 之间绑定被更换/关闭时窄失败且不向新绑定发送旧意图 |
| DU-11 | PASS | main.py 未接线时 heartbeat 测试 FAILED（Red 已验证） | `tests/cli/test_entrypoint.py::test_default_cli_waits_with_heartbeat_before_blocking_provider_returns`（provider 仅 1 次调用、waiting 先于 final） | — |
| DU-12 | PASS | — | `tests/kernel/test_runtime_progress.py` + renderer 窄锁（S1 focused 275 passed） | — |
| DU-13 | PASS | — | `refresh_preserves_draft`、`submit_draft_consumed_only_by_durable_user_fact`、`late_consumption_does_not_clobber_newer_draft` | — |
| DU-14 | PASS | — | `stream_window_binds_run_ignores_stale_and_degrades_on_gaps`（run 绑定/重复/旧版本不切回/缺口降级/终态屏障） | 重试递增 revision 已补（2026-10-10 修复轮）：test_transient_retry_persists_increasing_revision_between_attempts——真实 Runtime 重试恰好 2 次 generate、revision ≥ +2、durable transient-retry fact |
| DU-15 | PASS | — | UI-04：result overlay 限 form_kind None；takeover/approval 表单不被旧结果覆盖（TUI 88 passed） | fresh/reopen 摘要 parity 复用既有 render tests |
| DU-16/17 | PASS | — | `f3_review_modal_freezes_snapshot...`、`f4_multiline_modal_edits_submits_once_and_esc_preserves`、`multiline_paste_routes_into_f4_modal...` | 8000 字符页预算逻辑断言在 dialogs 层；视觉未逐项确认 |
| DU-18 | PASS | — | TUI 终态 hints 含 /new；CLI /help 已有 /new（`tests/cli/test_commands.py` 170 passed 套件内） | — |
| DU-19 | PASS | — | 既有 TUI 回归全绿（oversized preview fail-closed、exact displayed binding、stale snapshot 等，TUI 套件 88/90 passed）；本包未改动审批 gate 语义 | 语义未改动项以既有回归为证 |
| DU-20 | PASS | — | `tests/acceptance/test_daily_use_browser_driver.py::test_journey_cleanup_owner_reverse_once_and_aggregates`（逆序/最多一次/不跳过/有界聚合） | — |
| DU-21 | PASS | — | `timeout_latches_and_terminates_owned_group` + `group_gone_does_not_prove_independent_session_descendant_cleaned`（后代反例；测试自清后代） | — |
| DU-22 | PASS | — | `rejects_bad_budget_before_launch` + `protocol_failures_fail_bounded`（缺/重复/坏 JSON/缺字段/类型错有界失败） | 超限子例已补（2026-10-10 修复轮）：driver 套件两个新测试用生产常量真实灌 1.3MiB stdout / 70KiB stderr——output_limit 失败码+有界收尾；budget/协议/后代反例原有测试保留 |
| DU-23 | PASS | — | `scripts/f2_f3_local_browser_journeys.py --journey all --budget-seconds 120`：f2+d06 全 passed、cleanup confirmed、exit 0（真实 Chromium + loopback） | 临时目录按判定删除（成功路径不保留） |
| DU-24 | PASS | 过程 Red：CORRECT 应用即抛 `sandbox lease must bind the current goal revision`（真实产品缺陷：纠正 bump revision 未清旧租约，状态不变量 fail closed） | `tests/acceptance/test_daily_use_recovery_journey.py`：CORRECT 落盘(rev2+receipt)→语义 delta+no-op ack→真实改文件 v2+read-back→PAUSE 落盘返回→close→全新 composition/provider 重开→ResumeGoal→同命令新 ID 复测 A/B→VERIFIED_DONE→/new gate 放行且零 provider 调用；期间修复 `state.py` CORRECT 分支补清 process/sandbox 租约（回归 61 passed） | 全链在真实 Runtime/审批/sandbox 上执行 |
| DU-25 | PASS | — | `scripts/run_real_coding_scenario.py` allowlist 扩至本包 22 个公开文件；`test_f3_record_contract.py`+`test_f3_runner_roundtrip.py` 6 passed | 单字节变更改变 identity 的既有 record-contract tests 继续成立 |
| DU-26 | PASS | — | 旧 RESULTS 顶部交接说明（编包时已写入）；本 RESULTS 为唯一新记录 | — |
| DU-27 | PASS | — | README 本地 wheel 安装路径未改动、无付费探测；`test_entrypoint.py` 套件通过 | — |

## 最终检查

| 检查 | 状态 | 实际命令/退出码/证据 | 能证明与不能证明 |
|---|---|---|---|
| 各切片 focused | PASS | S1 275 / S2 170 / driver 5 / TUI 88，全部 exit 0 | 不外推真实模型 |
| git diff --check | PASS | exit 0 | 格式检查 |
| Ruff | PASS | `ruff check .` All checks passed | 静态检查 |
| full pytest -q -rx | PASS | 收口 3704/1/0 → 审计复跑 3706/1/0 → 修复轮终验 **3711 passed / 1 skipped / 0 failed**（含本轮新增：DU-10/14/22 补证 + usage 持久化共 5 个新测试） | 全量在修复轮最终候选上完成 |
| 本地真实 F2/D06 | PASS | journey 脚本 exit 0，f2+d06 全 passed、cleanup confirmed | 仅 loopback/专属 Chromium |
| non-editable wheel smoke | PASS | `tests/cli/test_016_packaging.py` 4 passed（最终 gate 内）：wheel 构建→隔离 venv（system-site=false）→--no-index 安装→RECORD 闭包物化→`--version`=first-agent 1.0.0→FakeProvider 一轮交互→origin 全部来自安装 site 且不含源码路径→缺 extras 诊断。另做独立构建核对：wheel SHA-256=33fd460c…89f77（内容与 gate 内 fixture 等价） | §5 的 allowlist 物化 staging 由 pyproject 打包清单等价承担，未另建独立 staging |
| CLI/TUI 实际交互/视觉检查 | PASS（文本级） | `test_pilot_daily_flow_renders_readably_at_both_terminal_sizes`[80-24 / 120-40]：终态摘要+/new 提示渲染可读、无 escape/markup 残留、连续三轮派发、草稿→F2→F3→Esc 保留草稿、F4 多行 F6 提交、焦点回输入框、Ctrl-Q 正常退出（exit 0）；超时退出/重载失败重试由专项 Pilot 测试覆盖。视觉等级=文本级渲染断言，非像素级 | — |
| 最终 scoped diff/合同复核 | PARTIAL | 本表+执行日志为复核记录 | — |
| 真实模型 Dogfood | A/B/C 全 PASS | C 二跑证据：S1 exit0@审批边界→S2 全新会话恢复同任务→批准→Verified delivery→check PASS；无 CheckpointSecurityError。请求台账：首跑 A32+B15+C5=52 + 二跑 C2 5 次 + 连通检查 2 次；估算费用 <<¥10 预算（各调用均小额，usage 现已随 RecordedRunResult 持久化可复核） | 不证明所有模型/任务 production-ready |

## Oracle 与编包证据

### 本次全新 Oracle 咨询

- Session：`fa-daily-use-plan-20261009-0qfc99`，未复用旧会话、未使用 followup、未手动发送。
- 已完整重读当前 oracle-web Skill；doctor 成功。源 Profile 只使用 doctor 指定身份，没有读取 cookie/凭据或升级 CLI。
- 强度：`--browser-thinking-time max`；发出前两次 slider ARIA 均为 **Power, item 5 of 5**，verified=yes。它证明网页档位，不把 CLI requested model 冒充网页实际模型。
- 本地启动时间：2026-10-09 16:57:30 +08:00；完成时间：17:19:21 +08:00。metadata.status=completed，调用退出0。
- 已提交：browser.runtime.promptSubmitted=true，独立 [ChatGPT 会话](https://chatgpt.com/c/6ac8acad-c774-83e8-b49a-f17f61da2df7) 有 committed turn；完整答复已经保存为 [ORACLE-RESPONSE.md](ORACLE-RESPONSE.md)，不是仅看到“正在思考”或截取摘要。
- 清理已确认：本次 Chrome PID 95015 不存在；本次临时 `oracle-browser-6nk2C4` Profile 已移除。没有关闭用户的其它 Chrome 或配置源 Profile。
- 本次自己的运行 metadata/output 留在 `/Users/jinkun.wang/.local/state/oracle-web/sessions/fa-daily-use-plan-20261009-0qfc99/`，仅为追溯路径；执行者无需读取该目录，也不依赖 Oracle 登录。
- 附件仅10个明确公开输入：AGENTS、KERNEL_ARCHITECTURE、EXTENSION_CONTRACTS、10月9日审计、TUI app/render/adapter、本地 journey driver、R1 test，及从15个公开源文件选出的带行号/摘要哈希摘录。发送前做了文件预览和凭据形态检查；没有真实配置、日志、用户会话或秘密附件。
- [ORACLE-PROMPT.md](ORACLE-PROMPT.md) 保留发送时的候选方案。候选键位/机制在冻结合同中已裁决，不与最终合同并列生效。

### 建议采用情况与本地纠偏

| 议题 | 冻结裁决 | 本地依据/边界 |
|---|---|---|
| 总范围 | 保留3切片；不增加CLI并发输入/tool advisory/新平台 | 支撑当前个人终端产品，不追求所有入口对称 |
| CORE-01 | 三个集合+单一durable fold；严格read-only/off native receipt；operator mutation不可漏 | ToolRuntime.invoke拒绝未授权ToolResult伪造；_sandbox_outcome验证draft/lease/binding并铸造receipt；evidence原mode-only例外需收紧 |
| Worker生命周期 | 已排队也busy；移除exclusive隐式取消；真正callable完成后才reload/exit；重复Ctrl-Q重载 | 本机Textual的正常SUCCESS/ERROR在await callable之后；CANCELLED不能证明线程结束。保留single-flight与main唯一cleanup owner |
| 流式producer扩展 | **不采纳新增invocation/attempt ID**；只修TUI过滤/水位/终态屏障，并增加真实Runtime重试回归 | loop在每次foreground generate前save record_foreground_model_attempt；state该reducer和begin_provider_call均revision+1；现有HTTP adapter单次generate无内部模型重试，compaction不传observer。Oracle复用revision是待核实推测，已被当前源码限定，不应据此增新协议 |
| 草稿消费 | 排队不等于消费；exact replay+user fact / ControlReceipt后才清同版本草稿 | state._apply_action使用action:{seq}:user；apply_control_request使用control:{request_id}:user并写receipt；RunStatus本身不是消费证明 |
| 历史与编辑 | F3最近20条当前retained可展示facts、8000安全字符/页；F4编辑、F6发送、Esc保留 | 不读取archive/tool payload/opaque continuation，不新增存储或编辑器依赖；主Input命令和modal普通文本分开 |
| 交付摘要 | 复用现有GoalView与scope；不新增虚构resource-cleaned字段 | 当前GoalView有targets/criteria/scope/durable_authorities_closed；已知recovery/takeover提示仍优先 |
| Journey控制 | 固定子进程、管道EOF协作停止、120+15+1+1+6预算；group和资源清理分开 | 复用process/group primitive；managed_web可独立session，不能把外层group消失当所有后代已清理 |
| 离线恢复路径 | correction→真实改动→PAUSE→close→全新composition/provider→复测→完成→/new | 新provider读取实际ContextPack，不靠旧脚本对象计数；不冒充崩溃恢复或真实模型成绩 |

这些取舍已写入 FIX-PLAN / ACCEPTANCE，不要求下一位执行者重新投票或再开一轮Oracle。
dev_co 将范围/证据集中在此记录，handoff 只产生转发入口；没有另建平行当前计划。

### 编包检查（不是产品修复验证）

- 48个公开源码/测试/配置 BASELINE 哈希再次匹配；本次没有修改它们。
- `git diff --check` 退出0；本包本身另查未跟踪 Markdown 的空白、链接、验收编号、现有命令路径和敏感串。
- 文档检查最终退出0：6个Markdown文件、17个本地链接、27条验收与结果行一一对应、27个命令/测试路径（其中3个明确标注为待新增）；无断链、未冻结条款或凭据形态命中。原始Oracle答复只规范化了13处行尾空白，内容未改写。
- 本次完成源码/文档交叉复核，没有运行本包尚不存在的Red/Green、全量pytest或真实本地旅程；上表实施检查继续NOT_STARTED。
- 仅新增本执行包和临时转发入口，旧 RESULTS 顶部增加历史/当前入口说明。既有dirty/untracked不清理、不提交。

## 执行日志（2026-10-09 实施轮）

- worktree 起点：main @ 838cb2b，48 文件 BASELINE 全匹配；既有 dirty/untracked 保留。
- S1：loop/evidence 三集合折叠（写后合法复测）——B03 重写 Red→Green（R1 全文件 5 passed）；TUI 单飞行/关闭收口/退出码/控制窄失败（TUI 88 passed）；CLI heartbeat 接线（Red 已验证）+ renderer 窄锁。
- S2：草稿 durable 消费账/流式窗口/UI-04/F3+F4 modals（新 agent/tui/dialogs.py）//new 提示；S2 focused 170 passed。
- S3：journey 脚本控制层重写（两代清理 owner + 子进程协议）；driver tests 5 passed；真实 f2/d06 旅程 exit 0 全 passed；identity allowlist 扩至 22 文件（record-contract 6 passed）。
- 事故记录：执行者会话缺陷曾覆盖未跟踪的 journey 脚本；已按上下文原文逐字重建并叠加本包合同修改，语义经语法检查与真实运行验证（f2/d06 真实旅程全绿）；最终哈希与基线不同属预期（本包本就修改该文件）。
- S3-C：恢复旅程测试（DU-24）已完成 GREEN（第二轮执行）；期间发现并修复真实产品缺陷：apply_control_request 的 CORRECT 分支未清 process/sandbox 租约，bump revision 后被状态不变量 fail closed（回归 61 passed）。
- 真实 DeepSeek：官方信息核对（model=deepseek-flash、base=https://api.deepseek.com、谷时输出 4 元/1M tokens）；预算估算三场景合计远低于 10 元上限；连通性检查 401 invalid（key 尾号 3204）→ 按边界停止真实调用，未轮换 Key、零费用。
- 资源收尾：journey 成功路径临时目录已由脚本删除；wheel smoke 临时目录已删除；无活跃/未知所有权资源残留。
- 真实 DeepSeek Dogfood（第二轮，有效 Key）：
  - 官方核对：model=deepseek-flash、base=https://api.deepseek.com（/v1/chat/completions）、谷时输入 ¥1/输出 ¥4 每 1M tokens。
  - 连通性：43 tokens（¥0.0001）确认身份。
  - **缺陷发现与修复**：DeepSeek-flash 官方端点默认即思考模式；thinking_mode=None 时响应携带 reasoning_content，normalize 以 unsupported_response_block fail closed。修复：openai_http 按 DeepSeek family 识别（model+endpoint）在请求侧启用连续性回放、响应侧放行 reasoning 并铸造 continuation；新增回归测试 `test_flash_default_thinking_json_response_keeps_reasoning_continuity`（tests/provider 29 passed）。修后场景 A 首跑即全绿。
  - 场景 A（编辑+自验+交付）：真实编辑 app.py→howdy、check.py 同步，2/2 evidence，"Verified delivery" + permissions closed；4 次审批全走产品审批流。
  - 场景 B（中途纠正）：hola 任务在审批边界收到英文纠正——pending 工具调用撤销为非执行结果，纠正成为 GoalDelta authority，按新要求重做并重验，最终 howdy 交付（exit 0，15 次请求）。
  - 场景 C（完成+重开）：notes.txt 创建+验证完成（check PASS）；全新进程重开同一 workspace/state 加载正常（"Status: no unfinished task"）。恢复语义（暂停→重开→续做）由 DU-24 离线真实链证明。
  - 范围外新发现（只记录）：① 进程内连续第二次会话启动报 CheckpointSecurityError（同一进程 S1 关闭期亦报一次；全新进程加载正常）——疑似进程级残留句柄/状态，未修复；② 任务完成后 /exit 关闭路径曾报同错误一次（transient，未复现于新进程）；③ 模型 usage 未持久化到 checkpoint，费用只能上台账+估算。
  - 预算台账：52 次传输尝试（A32/B15/C5，含失败与修复前调用）；谷时价上界估算 <¥2 << ¥10；Key 已在收口时删除（.local/.dskey），无回显、无入檔。
- 资源收尾：.local/dogfood/{A,B,C} 保留（含 ledger 与 result 证据，gitignored）；无活跃进程；Key 文件已删除。
- 最终 gate：`git diff --check` exit 0；`ruff check .` 全过；full pytest 3701 passed/1 skipped/1 failed（失败=架构清单缺 dialogs.py，已补清单，architecture 70 passed 复验）。

## 执行日志模板

在下面按有意义的里程碑追加，避免复制大段原始日志：

- 时间 / worktree 起点：
- 工作项与改动文件：
- Red：实际失败、为什么证明本问题（不是 fixture/环境错误）：
- 最小机制与保持的不变量：
- Green/focused：命令、完整 summary、exit code：
- 资源收尾 / 未证边界：
- 下一步：

## 真实 DeepSeek API 授权记录（2026-10-09 新增）

- 授权来源：用户 2026-10-09 最新实施指令（本 Prompt 为最新指令，覆盖旧"禁止真实 API"条款，不扩大其他权限）。
- 模型：用户指定的 DeepSeek Flash；调用前须按 DeepSeek 官方文档核对当前实际 model ID、官方 endpoint、价格与计费方式；无法确定时停止真实调用并报告。
- 预算：本轮所有真实调用合计 ≤ 人民币 10 元（连通性检查、失败请求、重试、正式 Dogfood 全部计入）。
- 凭据：仅允许读取本项目明确引用的 DeepSeek 专用凭据环境变量或用户明确指定的本地凭据文件；先从非秘密配置确定引用位置；不扫描主目录、不翻找其他客户端凭据、不从历史聊天提取；无法确定时请用户安全配置。Key 只注入验证进程的 composition root，不写入 Prompt/资料包/源码/Git/日志/命令回显/checkpoint/evidence。
- 场景：最多三个代表场景（A 小项目修改+自主验证交付；B 中途纠正后按新要求修改并复验；C 安全边界暂停→关闭→重开→继续原任务完成交付）。只用合成任务/临时工作区；必须走真实产品入口、Runtime、ToolRuntime、审批与 checkpoint；首次失败先诊断，仅在有新修复+预算允许时做最多一轮复测。
- 状态（时间线，2026-10-10 审计校正）：首轮环境 Key（尾号 3204）401 无效 → BLOCKED_CREDENTIAL；随后用户提供有效 Key，三场景 Dogfood 完成（见执行日志与最终检查表）；Key 已删除。原始 401 详情：单次连通性检查（max_tokens=8）返回 HTTP 401 authentication_error，按合同边界停止、未轮换 Key、零费用。

## 范围外发现与阻塞

编包时的范围外项按 START-HERE §5 保留；不自动转成执行任务。

执行轮新增（只记录，未修复）：
1. 进程内连续二次会话启动 CheckpointSecurityError（C 场景 S2；全新进程正常）——疑似同进程前一会话残留（fd/缓存）；影响 TUI/CLI 同进程 /new 之外的重开路径。
2. S1 关闭期 transient CheckpointSecurityError 一次（任务已完成、数据无损失；新进程复载正常）。
3. checkpoint 未持久化模型 usage/费用——真实使用的可观测性缺口。
执行中新增项记录具体事实、影响和是否阻断当前验收，不能只写“待优化”。

## 最终交付摘要（2026-10-09 执行轮，第二轮更新）

- 分级：**LOCAL_CLOSED（离线）+ 真实 Dogfood A/B/C 全 PASS**（2026-10-10 终态）：离线 DU-01–27 逐行 PASS（含修复轮补证）；最终全量 gate 3711 passed/0 failed；usage 已持久化；真实 C 二跑按原授权定义完成（安全边界暂停→重开→续做→交付），CheckpointSecurityError 未复发（可观测性日志就位，如复发可定位）。详见 [AUDIT-2026-10-10.md](AUDIT-2026-10-10.md)。
- 实际修改范围：
  - `agent/runtime/loop.py`（三集合折叠/抑制查询/重折叠）、`agent/runtime/evidence.py`（共享严格分类器 + 收紧失效判断）、`agent/tui/app.py`、`agent/tui/adapter.py`、`agent/tui/dialogs.py`（新）、`agent/cli/render.py`、`main.py`（CLI progress 接线）、`scripts/f2_f3_local_browser_journeys.py`（控制层重写）、`scripts/run_real_coding_scenario.py`（allowlist 22 文件）；
  - 测试：R1 B03 重写、`tests/kernel/test_validation_request_freshness.py`（新 7 tests）、TUI 新增 14 tests、CLI heartbeat test、driver tests（新 5 tests）。
- 验收未通过/未运行项及原因：视觉检查为文本级渲染断言（非像素级，如需截图级验收须另行授权/工具）；进程内二次会话 CheckpointSecurityError（范围外新发现，只记录）；真实 Dogfood 的 C 场景暂停-恢复由离线 DU-24 承担。
- 当前用户能做什么（含真实模型验证）：用 DeepSeek-flash 完成日常任务闭环——真实编辑+自验+VERIFIED_DONE（A）、审批边界中途纠正并按新要求交付（B）、审批边界安全暂停→关闭→重开→续做原任务→交付（C 二跑，原授权定义全链）；CLI/TUI 的等待 heartbeat、安全退出、草稿保留、F3/F4、/new 均可用；f2/d06 真实浏览器旅程全绿。
- 注意限制：离线恢复链由 DU-24 证明；安装物经 packaging 契约测试证明；真实模型行为 A/B/C 全 PASS（C 二跑为原授权定义全链）；DU-10/14/22 子条件已补证；唯一未定位项=首跑 C 的进程内 CheckpointSecurityError（二跑未复发、日志可观测已就位）。
- 是否有活跃/cleanup-unconfirmed 的本次资源：无（journey 成功路径临时目录已删；测试自清后代与子进程）。
- Git：未 commit/push/tag/修改 remote；既有 dirty/untracked 保留。
- 下一执行者最小继续路径（2026-10-10 审计后）：(1) 补 DU-10 绑定更换反例、DU-22 stdout/stderr 超限子例、DU-14 重试递增 revision 锁定测试；(2) 修进程内二次会话 CheckpointSecurityError；(3) 如需真实 C 的原定义（安全边界暂停→重开→续做→交付）按新授权重跑；(4) checkpoint usage 持久化。前一轮列出的 DU-24/wheel/full-gate 事项均已完成。

（原未填模板已由上方 2026-10-09 实施轮摘要取代；模板定义存史：LOCAL_CLOSED=全部本地 gates 通过且真实远端模型另行声明；IMPLEMENTED_WITH_VALIDATION_GAPS=实现完成但列明未证项；BLOCKED=需新授权或边界决定。）
