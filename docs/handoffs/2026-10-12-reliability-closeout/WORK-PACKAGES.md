# 工作项与验收合同

本文是 Codex 独立审计与 Oracle 最高档审计合成后的执行合同。以 START-HERE 为入口；[Oracle 采纳与边界裁决](ORACLE-DECISIONS.md) 解释合成差异。只处理已证实缺陷及明确证据缺口，不授权执行包外改动。

**固定顺序：W2 → W1 → W3 → W4 → V1 → V2（先增量安装检查，再最终完整门）。** ID 保留原审计映射，不代表实施顺序。W2 为 P0 防误删保护，W1/W3 为 P1 已知缺陷，W4 为 P1 未归因失败；V1/V2 是 P1 证据门，不据此预判产品已坏。

产品缺陷写击中基线的 Red；证据缺口写能够拒绝假证明的负对照，不人为制造产品缺陷来满足仪式。执行前将下列矩阵映射到现有或新增 pytest node ID，记录在唯一 RESULTS 小节，不另建测试管理系统。

## W1：完成验证必须对应 writer 停止后的结果

**来源：** 独立审计 A1；原 RC-02 第 3–6 条没有闭合。用户可见后果是用早于最后一次潜在写入的测试结果宣布完成，且显式重验可能被抑制。

**导航：**

- `agent/runtime/evidence.py`：`WRITABLE_PROCESS_TOOLS`、`_may_invalidate_workspace_validation`、`_process_tool_receipt`、`_native_sandbox_tool_receipt`。
- `agent/runtime/loop.py`：`_successful_product_request_inventory`。
- `agent/runtime/resource_lifecycle.py`：`active_task_resources`、`require_closed`。
- `agent/process/managed_web.py`：`start`、`stop`、`_stop_record`、持久 cleanup receipt。
- 现有测试：`tests/kernel/test_validation_request_freshness.py`、`tests/continuity/test_reopen_invalidation_q2.py`、`tests/process/test_managed_web.py`。

**必须先 Red：** 使用生产 receipt/fact 形状构造 start→A→stop，证明当前旧 A 被信任、同参 A 被抑制。随后补一条真实短期服务旅程：临时 sentinel=before → start 就绪 → 只读验证 A → 通过受控请求或事件让服务写 after → stop 清理确认 → 旧 A 必须被拒。同一旅程必须实际把 stop 结果写入被判定的事实序列；不能检查停服前保存的旧 state 然后声称关闭后已验证。

**成功矩阵：**

| 情况 | 预期 |
| --- | --- |
| A→start | 启动前 A 失效 |
| start→A→write→stop | A 失效，资源关闭不等于 A 又有效 |
| start→A，进程仍活着 | 不得完成；不要借修复禁止所有运行期诊断 |
| stop 后显式同参 A2 | 真正执行、不被旧摘要抑制；新 receipt 可用于原有完成条件 |
| stop 后 A2/B2，期间无写入 | 两项正常只读验证可共同成立 |
| start/stop 确定未执行的拒绝 | 不伪造执行，也不能把仍活跃资源移除 |
| 已可能执行的 start 失败、stop 失败/UNKNOWN | 保守处理新鲜度和资源所有权，不能宣布已清理 |
| 两个 writer，一次只关一个 | 剩余 writer 仍阻止完成；最后关闭后取得的新验证才满足最终状态 |
| 已确认 stop 再重复 stop | 定义并测试其幂等语义；不得复活旧验证、制造资源关闭后无限重验循环 |
| 全部关闭后 A2，再 start 新 writer | A2 按既有启动失效规则作废，不继承上一个生命周期的信任 |
| 实际 checkpoint 关闭重开 | 不依赖旧 Runtime 内存；未关闭资源和失效含义保持 |
| compaction 后重开 | 被裁剪事实不能使旧验证复活；正常重验仍可恢复 |

**冻结的最小实现方向：** 最终 workspace 验证的资格 = 验证取得时没有未确认关闭的 managed writer，且后续没有既有失效事件。以验证之前的 durable fact 前缀调用/复用 `active_task_resources()`，只检查本问题对应的 `managed_processes`；不能用最终已经空的资源集合倒推当时安全，也不能把所有浏览器观察改成这个合同。存活期只读结果可供诊断，但不能用于最终验证或成功抑制。

在 evidence 两个 receipt 判定入口和 loop inventory 共用这一资格语义，不增加资源 epoch、持久字段或第二份状态缓存。尤其不能把“writer 存活”简单并入 `trusted_sandbox=False`：当前 false 分支会把请求加入 `ordinary`，仍会抑制重验。须分别保留“严格可信只读 sandbox 结果”和“具备最终复用资格”两个判断；失格的可信只读验证既不进 `native_validation`，也不回落 `ordinary`，其他普通工具抑制不变。

不要简单把 stop 加入无条件失效集合。真实 stop 后旧 A 应无效，但幂等重复 stop 不应作废关闭后取得的 A2；不要求内部 `stop_invalidates` 必须为 true。不要新增永驻监视器、进程状态数据库或 schema 迁移。若发现必须改 schema/所有工具合同，先举出当前表示不足的反例并请求决定。

**必须补核但尚未证实有 bug 的分支：** start 在成功 ready/resource_ref 登记前失败且清理不确定。补读 `agent/runtime/tools.py::KernelToolRuntime.invoke` 的分类、`managed_web.py::prepare_resource` 及重开 cleanup receipt 身份；不能因为资源投影没有 ready 条目就认定安全。若已有 UNKNOWN/执行意图路径阻止完成，只补回归；若没有，保留实际反例，只修命中的现有分类/恢复路径，涉及新权限/schema 时先报告。compaction 的所有权保留入口见 `agent/runtime/compaction_rules.py` 对 `owner_fact_ids` 的使用。

**可改区域：** 上述 runtime 判定与其测试；managed-web 或资源投影只有在有证据证明必须时最小修改。不得顺手重构全部 process/browser 模块。

## W2：候选构建不能以删除用户目录为起点

**来源：** 独立审计 A2；新 `scripts/build_candidate_manifest.py::main` 的 `out.exists() → rmtree(out)`。

**范围：** 该脚本与其 CLI 安全回归。建议新增 `tests/reference/test_candidate_manifest_safety.py`（这是待创建路径，不是已存在测试）。

**最小合同：**

1. 默认只创建新的 output；已有目录、普通文件或软链接均在任何写入前失败，不能提供默认开启的覆盖/删除行为。
2. 收窄到**仓库之外、本次拥有且已存在的同一物理父目录**：output 与 manifest 是其下两个不同、尚不存在的叶子。拒绝源仓库根、祖先、仓库内输出及任何源/目标包含冲突；不自动创建未知父目录。
3. output/manifest 叶子用不跟随链接的检查，已有文件/目录/链接（含悬空）均拒绝；先解析已有父目录再做边界检查，允许系统级路径别名规范化，但链接绕回源树仍拒绝。不能先 resolve 叶子丢失其链接身份。manifest 不在 candidate 内，也不是任意源文件路径。
4. **在任何目标写入之前**完成整份输入清单预检并冻结字节摘要；拒绝源路径链接、非普通文件、越界或私人路径，不因 tracked 就可读取。目录与复制目标使用 exclusive/no-overwrite；复制后验证与预检摘要相同。安全判断用显式异常，不用可被 `-O` 去掉的 assert。
5. 全部复制成功后才能发布正式 manifest，要求完整且不覆盖：在相同父目录写本次独占临时文件，再用目标已存在即失败的发布方式（当前 POSIX 可用 `os.link`），不能用会覆盖的 `os.replace`/普通 rename 冒充。输入变化、复制/发布失败均非零退出，不留有效成功 manifest；明确保留本次 partial candidate 为 incomplete，**不做递归删除回滚**，下一次用新路径。
6. 不读 ignored/private 目录，不全仓递归复制，不为清理旧 build/lib 调危险删除分支。每次从全新输出构建，保留源码清单与哈希。
7. 新增的本包回归也要显式进入候选清单；更新过时的“本轮文件”描述，使 manifest 如实区分基线与当前改动。不能用旧23文件标签假称本轮无漂移，也不能自动把所有未跟踪文件纳入。

**先 Red 后 Green 的矩阵：**

- 已有非空目录，目录内 sentinel 前后字节一致。
- 已有空目录也拒绝；普通文件、断开的软链接、软链接 output/manifest、父路径链接绕回源树；系统别名规范化的正常路径可用。
- 仓库根、仓库祖先（全部在独立临时 Git fixture 验证，绝不拿真实仓库试删）。
- manifest 指到现有文件、源文件、output 中的源码路径；拒绝后 output 也不应提前出现。
- 新 output 与合法新 manifest 正常成功，逐文件哈希正确。
- 清单最后一项丢失/链接/非普通文件：第一项也不能提前复制；受控复制失败、源内容变化、目标创建或 manifest 发布前被占用：非零退出，没有成功 manifest，源和既有目标不变。

临时源树可以替换受控 Git 清单查询，不要求为测试实际 git init/commit。不要求证明可对抗同 UID 的无限并发恶意进程；也不能因此保留最基本的现有路径覆盖漏洞。不增加清理服务、通用构建框架或任意路径 `--force`。

## W3：显式关闭思考模式时的适配正确性

**来源：** 独立审计 A4；不是 key 失效，也不是需要再次提高 token 上限。

**导航：** `agent/provider/openai_http.py::generate`，`config.py::__post_init__`，`normalize.py::context_to_openai_messages/normalize_openai_response`；`tests/provider/test_deepseek_flash.py`、`test_continuity_control.py`、`test_kernel_providers.py`。

**先 Red：** 用 `httpx.MockTransport`，官方 Flash identity、`thinking_mode='disabled'`、`reasoning_effort=None`，返回正常 JSON 文本且无 reasoning_content。断言请求确实发送 disabled、结果应成功；基线实际报 missing_reasoning_continuity。禁止联网后才定位这个已确定问题。

**矩阵：**

| 配置/输入 | 预期 |
| --- | --- |
| 官方 identity，显式 disabled，纯文本 JSON | 成功，不制造 provider_continuation，不要求 reasoning_content |
| disabled，正常 tool call → result → 下一轮 | 能续接正常工具协议，不因没有 reasoning 字段失败；仍校验 call/result 配对 |
| enabled | 保持既有 SSE、reasoning 连续性、完成边界、usage 与字节预算合同 |
| 官方 identity，未指定 mode | 保持当前已支持的默认 reasoning JSON 路径；不得为了 disabled 改默认产品行为 |
| enabled 历史缺少 continuation | 仍在 HTTP 前 fail closed |
| continuation identity 不匹配 | 仍拒绝，不剥掉 opaque payload 后悄悄继续 |
| disabled 会话收到旧 enabled continuation | 保持明确不兼容/拒绝；本轮不新增跨模式会话迁移或自动丢弃历史 |
| 非官方 compatible endpoint / 不相关模型 | 不因名字相似继承官方 reasoning 规则 |
| malformed 响应/断流/缺终态 | 保持现有失败语义，不退回部分答案成功 |

最小条件为“显式 enabled，或 mode=None 且符合当前官方 Flash identity 规则”；family 推断不能覆盖显式 disabled。增加传输边界对照：enabled 收 JSON，None/disabled 收 SSE，以及 disabled JSON 意外携带 reasoning 字段，保持原有严格拒绝；不自动格式回退或重发。断言 MockTransport 调用次数及错误发生在 HTTP 前还是响应后。

只改必要条件与测试。不要更改容量档案、模型列表、API endpoint、真实 key、provider 身份格式或全局 normalize 的保护。None 的默认 reasoning 路径是保留本仓库既有兼容约定，不是本轮重新核实了线上 API。当前官方 API 行为若有争议，查 primary source 并记录适用范围；不能把离线回归说成服务商线上兼容性验证。

## W4：查清进程清理的间歇失败

**已有事实：** 独立完整运行中 `tests/reference/test_015_e3_harness.py::test_015_offline_gate_timeout_cleans_owned_process_group` 期望124，得到125 cleanup unconfirmed。单独复跑0.60秒通过。原执行者还报告另两个位置的时序失败；不能混成同一根因。

**导航：** `scripts/run_015_e3.py::_run`；`agent/process/group.py::verified_group_identity/group_alive/terminate_group`；`tests/reference/test_015_e3_harness.py`。参考但不先改：`tests/automation_hosts/test_posix_supervisor_cleanup.py`、`tests/process/test_managed_web.py`。

**诊断顺序：**

1. 先给 `_run` 的失败诊断区分 `identity_unverified`、`group_cleanup_unconfirmed`、`post_cleanup_output_drain_timeout`；保留现有退出码和成功条件。当前125同时涵盖 terminate_group 失败和后续 communicate 超时，不代表根因相同。只输出有界、安全的阶段、异常类别、errno/耗时，不回显任意子进程敏感内容。
2. 先区分：leader 是否回收、仍有运行中的 descendant、只剩待回收的 zombie/orphan、liveness 查询未知、测试在启动握手前就开始耗尽预算。
3. **本轮诊断最多8次真实 fixture、累计10分钟、每次不超过60秒**，纯 mock 判定测试不计真实重跑：原节点独立与有依据的前序各1次；2次启动/回收屏障对照；有精确公开失败节点时 supervisor 与 managed-web 各最多1次；最多2次留给已形成假设的单变量试验。未知节点不猜、不消耗次数碰运气；上限不是必须跑满。每次记录本次 PID/已验证 PGID、TERM/KILL、leader回收、liveness/errno、EOF 及耗时，失败后先完成本次 owner 的有限清理。到预算标 UNRESOLVED，不无限继续。
4. 真实资源路径必须保留 bounded cleanup。证明原因后再改最小生产逻辑或测试假设；两者分开解释。不能仅提高睡眠/超时值或把 `124` 断言改成 `{124,125}` 就宣称修好。
5. 修改共享 group primitive 只有在其根因被证明时允许；随后补 local-process/subagent/managed-web 相关调用方回归。若是测试夹具未同步，优先修夹具；不能为了一个 fixture 改所有生产超时配置。

先给原失败 fixture 补 `finally` 精确 owner 清理保障，避免第一条断言失败就泄漏并污染后续结果；仍禁止按进程名或失去身份绑定的 PID 猜组。必要补读 `agent/process/managed_web_child.py` 的退出/回收段和 `agent/automation_hosts/posix_supervisor.py` 实际清理调用，不先改它们。共享默认 post-KILL 确认预算6秒、此 harness传2秒只是诊断线索，不构成直接延长超时的修复依据。

**必保不变量：** 仅治理本次验证过身份的进程组；不 pkill/killall；PID身份未知不对猜测的组发信号；发出 TERM/KILL 不等于确认清理；权限错误/未知 liveness 不返回 cleared；owner 关闭路径保持有界；异常路径不能泄漏测试进程。

**可以接受的结论：**

- FIXED：有根因、修前可区分证据、针对性修复和回归，真实受控资源路径通过。
- PROVEN_NO_PRODUCT_CHANGE_NEEDED：以证据证明生产 fail-closed 正确，缺陷在测试的具体假设；修正夹具及测试后保留真实清理负例。单次重跑通过不满足此状态。
- UNRESOLVED：未定位。其余独立工作照做，但最终完整门不能因此标为通过。

## V1：用可观察副作用证明新进程恢复没有隐式重放

**范围：** 补证据，不是发明跨会话 exactly-once 承诺。优先增加 `tests/continuity/test_resume_effect_no_replay.py`，复用现有 `LocalCheckpointStore`、控制入口、受治理工具和 fake/scripted provider；helper 留在测试内，不做新产品服务或评测库。

**现有导航：** `agent/cli/actions.py::build_pause_goal/build_resume_goal/build_resume`，`agent/cli/app.py` 的 `/resume` 分流；`tests/continuity/test_goal_controls.py`、`test_operator_tool_checkpoint.py`、`test_checkpoint_v4.py`。这些现有例子不自动等于跨 OS 进程的完整旅程。

**必须有的本地旅程：**

1. 使用公开合成任务和本次独立 workspace/state root。工具副作用是可数且非幂等的受控动作（例如每次实际执行追加一条记录并 flush/fsync）。计数必须来自 callable 的真实执行，不从 tool_call_id 的数量推算；并记录恢复后 provider 收到的合成 ContextPack，与内核 intent/result 账本互证。
2. 进程A按生产顺序执行一次效果，结果持久化后在合法控制边界 PAUSE；核对 durable paused，退出并确认 owner 关闭。
3. 启动真正的新 OS 进程B，复用同一 workspace/state；只走当前合法 resume 入口，不重述原任务/纠正，不手工修 checkpoint。
4. 在没有新授权效果请求的观察窗口里，确认原已完成效果计数仍为1；同时核对原意图与 result checkpoint 仍在、新进程未隐式重新派发原执行意图。
5. 负对照：受控副本里即使用新的 call ID 重复相同逻辑效果，计数/观察校验也必须发现。证明 oracle 不只检查 ID 是否唯一。
6. 正常后续任务或明确的新逻辑意图可以执行同样的命令；不能通过按参数永久去重把合法操作禁止来让测试变绿。把“恢复隐式重放”与“模型/用户明确提出新请求”分开记录。
7. UNKNOWN 分支保留显式人工恢复决定，不自动重试未知效果。不要为测试把 UNKNOWN 标成成功或放开审批。

同一 fixture 追加两条正向能力/崩溃对照：完成 X 的 RESULT 后、下一操作 Y 前暂停，新进程恢复后 X仍为1，Y经正常工具/授权路径从0到1；在另一个独立样本中，真实 EXECUTING已落盘且X物理效果已fsync、callable尚未返回时，以测试屏障终止本次拥有的进程，新进程应进入既有 UNKNOWN而X仍为1。另设效果尚未发生的崩溃点，计数保持0。不手工编造 checkpoint，不给生产加 failpoint。

对“恢复后模型用新 call ID 再提出 X”的样本，检查现有意图、抑制、授权边界并记录实际归因；未经本次必要授权不得进入 callable。若当前合同把它作为合法新请求并需要新的明确批准，在夹具中拒绝该重复请求、保留计数1，并单列模型重复请求情况。若现有合同允许它通过已有权限执行，记录这层限制，不能把它冒充内核自动重放，也不能顺手增加跨 run 语义去重；需要新的产品边界时交用户决定。普通“继续”不是测试驱动替模型批准重复效果的理由。

**避免空洞证明：** 当前无 active_run 的 `/resume` 会走 `ResumeGoal`，只把 paused goal 变为 goal_ready，正常情况下不调用 provider/tool。测试分两段报告：恢复控制本身没有效果；然后用当前合法推进入口发起一次不含原任务/纠正细节的“继续当前任务”，让新进程真实经过 production model/tool loop，scripted provider 不提出新的副作用意图，效果计数仍为1。不能只断言 ResumeGoal 没调工具就称“恢复后继续执行全过程零重放”，也不能为测试新增自动推进功能。

额外检查纠正只按 durable 接收/应用身份继承；如果本地旅程没有包含纠正，不声称已新证明“纠正后恢复”。真实模型层的纠正/恢复仍以单独授权后的旅程为准。

**真实模型层：** 不读取旧私人记录凑证据。若得到当前授权，沿用旧包 VALIDATION 的 D04 公开 fixture 与不改 grader 的规则，补本次语义效果计数并记录调用内容、逻辑意图、执行 receipt 关联；精确参数可用脱敏摘要/哈希。模型新 ID 重做已完成步骤不能被“不是同一ID”忽略，也不能直接推断成内核隐式重放。发现范围外产品缺陷时报告，不擅自改通用调度/去重策略。

## V2：只用最终修复身份作交付判断

完成 W1–W4/V1 后按 VALIDATION 做一次最终完整门与中立安装检查。结果表必须区分 source、installed、real-resource、real-model；禁止把“在另一 venv 从源码导入”称 installed。

修复后旧653文件哈希、旧wheel、旧全量结果不再覆盖新代码。冻结本次公开输入的清单/哈希，保留新wheel哈希与导入来源；不得重新使用有 build/lib 残留的目录构建。既有包装回归和 `_019_installed_pytest.py` 是可复用工具，不另建安装验证框架。

只把通过的范围写为通过；未授权真实API、环境不匹配、未定位失败都单列，不能在摘要写“全部 VERIFIED”而把阻塞藏到末尾。
