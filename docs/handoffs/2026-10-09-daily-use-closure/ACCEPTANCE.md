# 验收合同与命令

> 版本 1，2026-10-09 冻结。测试名称标注“新增”的，不声称当前已存在。
> 只读审计的 143 passed 和旧资料包的 PASS 都不能填进本包的 Green。

## 1. 验收纪律

- 每个行为变更：先记录当前源码的失败反例（Red）、再做最小改动、用相同反例 Green。已被他人修好的项允许“当前行为已满足”，但需实际验证。
- 确定性 race 用 Event/Barrier/可控 clock；不要依靠碰运气的长 sleep。
- 核心正向测试只能替换 provider 或明确基础设施测试 seam，不能 mock 掉 Runtime、ToolRuntime、审批、receipt、checkpoint、evidence 后再声称生产闭环。
- `RunStatus.COMPLETED` 不等于 `GoalStatus.VERIFIED_DONE`；结果文本不能代替 typed state。
- 超时、输出截断、进程未退出、缺测试依赖不能算 PASS。SKIP/NOT_RUN 记录原因和受影响的结论。
- 合成 tests 的 key/路径/任务不来自用户现有私有数据。macOS 临时根先 resolve 为真实路径，避免 `/var`→`/private/var` 的 no-follow 别名误伤。
- 测试 fixture/driver 的 cleanup 放 finally；不能用测试末尾强制 app.exit() 掩盖产品退出 bug。诊断清理与产品验收断言分开。
- DU-01–27 全部为本包必需项；缺本地 Seatbelt/Chromium/Textual 等环境只能记录验证缺口，不可删除对应验收或签 LOCAL_CLOSED。真实远端 API 是另行授权门，不属于这27项。

## 2. 必需验收行

每行在 RESULTS 填实际 node/命令、Red/Green、退出码和限制；一行可有多个测试，不用测试总数替代下列行为。

| ID | 行为与必须观察到的证据 | 主要落点 |
|---|---|---|
| DU-01 | 成功 A/B → 真实受治理写入 → 相同参数且新 call ID 的 A/B 真正再执行 → 新 receipt 支撑完成；分别断言执行次数、实际文件字节、fact/receipt 新鲜性、VERIFIED_DONE，不能只断言最后状态 | 现有 `tests/process/test_r1_two_validation_completion.py` 增补 |
| DU-02 | 输入未变时同成功验证再次请求仍被抑制/有限 no-progress；A 与 B 在同一未变输入上共存，B 不让 A 的 suppression 自动过期；不把所有 sandbox 全局豁免 | 同上 + kernel limits |
| DU-03 | 仅模型 mode=read-only、伪造/缺失/投影不符/非 confined/network非off receipt 不能进入可信验证分类；普通 callable 不能伪造 native receipt；原 same-UID lease-governed 例外和其它 effect suppression 不变 | 新增 `tests/kernel/test_validation_request_freshness.py` |
| DU-04 | 已执行可能修改输入的成功/失败/超时结果使旧验证过期；不能因 operator origin 被过滤而遗漏该失效；未执行拒绝不触发新特许；UNKNOWN 仍先 recovery，不借 invalidation 自动重跑 | 同上 + `test_f1_input_mutation_invalidation.py` |
| DU-05 | 新 Runtime/CheckpointStore 从相同持久 facts 重建：写前重复仍挡、写后合法复测可执行；正常压缩旧闭合 turn 前后结论一致，当前 run 执行事实仍受保护；live/reopen/compaction 不依赖进程内缓存，summary不提供执行凭据 | R1 + 新 freshness tests + compaction regression |
| DU-06 | exact typed action replay 不二次 invoke；same action-in-progress 不重送；Goal revision、撤权、租约过期/次数耗尽仍按原规则重批/拒绝；unknown effect 不能被 cancel/new 绕过 | kernel approval/recovery + continuity controls |
| DU-07 | B03 显式证明 write 确实发生、写后 B 真执行成功、A 仍缺当前证据，因此不能完成；再补 A 后可完成。不同阶段使用新 call ID，修正原测试“两个验证之间”的不实注释 | R1 原 B03 |
| DU-08 | 已排队但 callable 尚未开始也 busy，禁止二次调度/隐式exclusive取消；Ctrl-Q 过deadline时资源不提前关闭；callable真返回后自然退出；重复Ctrl-Q只一只timer；CANCELLED不能冒充线程已结束 | `tests/tui/test_app.py` 既有 Pilot 扩展 |
| DU-09 | 关闭期 worker失败+reload成功退出码2；正常为0；reload失败保持禁用，重复Ctrl-Q只重试只读load而非重做action；unknown保留未决义务不被变成CANCELLED/CLEANED；main closeables逆序一次、失败不吞 | TUI Pilot + composition boundary |
| DU-10 | 活跃但无Goal/binding、current与submit之间绑定关闭/更换、store.load失败时 pause/cancel/correction有界失败；不崩溃/未来重绑/假称已停止；请求排队与durable应用分开，关闭期不接新纠正 | TUI app/adapter + continuity controls |
| DU-11 | 通过实际默认 main（非 TUI）接线，阻塞 provider 返回之前已有 waiting 提示；provider 仅一次调用，非事后重放 event；无真实 API | cli entrypoint + `tests/kernel/test_runtime_progress.py` |
| DU-12 | 丢失/重复/迟到进度 event 不影响审批/Goal/evidence；sink 抛错不改变结果；最终权威结果不被旧 waiting 文案覆盖；普通 tool batch events 不冒称实时事件 | CLI/TUI progress/render |
| DU-13 | F2/刷新/审批/回看/错误不丢草稿；只由匹配action replay+user fact或ControlReceipt证明消费，单纯worker排队/COMPLETED不算；AWAITING_APPROVAL已消费可清；迟到回调不清新版本；未知接收保留且不自动重发 | TUI Pilot 草稿用例 + adapter消费判定 |
| DU-14 | 跨conversation/run、同run多次generate/重试不串流；真实Runtime重试递增revision；重复/迟到忽略，序号缺口/逆序降级；preview<=2000、有限cache<=256；paused/approval/error/final后关闭窗口，F2 active刷新不误关闭 | TUI Pilot/render + runtime progress/重试 |
| DU-15 | VERIFIED_DONE fresh/reopen显示已有GoalView目标、criteria计数、scope、durable权限状态；保留已知未决资源提示但不发明cleanup证明；新snapshot压过旧result；COMPLETED未验收不假称交付，takeover提示保留 | TUI render/app + CLI parity |
| DU-16 | F3冻结snapshot，最近20条允许事实按序；每页<=8000安全展示字符，长文尾可达；summary明确非原文；continuation/reasoning/tool私有数据不出现；零provider/tool/state写，Esc保留草稿焦点 | TUI render + F3 Pilot |
| DU-17 | F4 Enter换行、F6/发送按钮仅提交一次、Esc保存；多行paste打开modal；modal slash为普通文本；多行草稿不压成单行丢失；pending/closing/unknown拒绝、stale快照不重绑；active纠正仍走原control gate | F4 + paste Pilot |
| DU-18 | 用户能发现 /new；仅现有 new_session_gate 放行时建新会话，旧 Goal/证据保留；pending/unknown/busy 时拒绝，不能把 follow-up 偷换成新任务 | CLI/TUI existing commands |
| DU-19 | 回看/新提示/多行不绕过 approval preview cap、exact request/binding、stale displayed-state 与 literal safe display；Enter/粘贴不默认批准 | TUI actions/approval regression |
| DU-20 | F2两代独立ExitStack，readiness检查前已登记callback；第一代失败不启动第二代；open/ledger/close/多callback失败均尝试剩余且每个一次；记录generation/index/type，不覆盖任务失败或签PASS | 新增 `tests/acceptance/test_daily_use_browser_driver.py` |
| DU-21 | 阻塞child在work budget+15+1+1+6清理预算内结束控制等待（留OS容差）；timeout锁存；独立session后代反例证明group消失!=资源清理；unknown保留目录停all后续；测试自身精确清理后代 | 同上，机制按 FIX-PLAN S3-B |
| DU-22 | budget的NaN/Inf/非正值在启动前拒绝；child异常、缺/重复/坏JSON/字段错误、stdout>1MiB/stderr>64KiB均失败并有界收尾；同时排空管道；没有owner清理终态不得签cleanup；只处置本次owned group | 同上 |
| DU-23 | 当前主机的真实本地 F2 正常关闭→新 owner 补记、D06 本地提交→readback→browser/managed_web cleanup，各自身份/结果/cleanup 明确；缺 Chromium 时 NOT_RUN，不能用 fake 替代 PASS | 修复后本地 journey 命令 |
| DU-24 | 离线真实链：写入并验证→CORRECT落盘→真实改文件→PAUSE落盘并返回→close→全新composition/store/provider→同命令新ID复测→VERIFIED_DONE→/new；新provider依据ContextPack而非旧计数；任务不重述、效果不重放、旧evidence不充数、产物/权限真实闭合 | 新增 `tests/acceptance/test_daily_use_recovery_journey.py` |
| DU-25 | 本轮相关公开源码（至少 loop/state/contracts/evidence/control/CLI/TUI 与实际 driver）进入明确有界的 source identity；选定关键文件变更令 identity 变，不涉及私有/全盘输入；producer/validator 仍 exact roundtrip | existing record-contract tests |
| DU-26 | README、旧 RESULTS 顶部和本包结果区对 D06/安装态/本轮成绩无互相覆盖：按历史报告、本次独立复核、新实现验证分别标注；不擦掉失败历史 | 文档核对 |
| DU-27 | 缺浏览器依赖的提示与本地 wheel/源码安装方式一致，不自动安装；默认路径不索取或回显 key、不额外发付费探测；候选等级、macOS-first、受限扩展、scheduler未接线限制保留 | cli readiness tests +文档 |

## 3. CORE-01 / B03 的最小复现顺序

复用 R1 的 `_make_fixtures`、`_drive`、`_approval_now` 和正常 `_parse_action("/approve ...")`。脚本 provider 只安排模型响应，不替代执行链：

1. 初始任务明确要求 check-a 和 check-b，提出合法 Goal。
2. 调用 validate-a-1、validate-b-1，实际执行两个只读 native sandbox。
3. 通过 write_file 写真实文件；断言文件字节已变和 executed fact 已落盘。
4. 以 validate-b-2（新 ID）、**完全相同的 tool name/arguments** 再调 B。
5. 原代码应在第 4 步暴露 duplicate_product_request，不能以审批时间过期、fixture prepare 失败或 call ID 重复冒充 Red。
6. 修复后 B 真执行。此时 A 的旧 receipt 仍无效，completion 不应通过。
7. 再用 validate-a-2 真执行 A，读取实际新 receipt，正常 CompletionClaim 应能 VERIFIED_DONE。
8. 加一版在写后、第 4 步前重建 Runtime/store。不要把此前 Python 对象/成功集合带过去。

核心测试可以使用小脚本作为控制流探针，但 DU-24 必须额外核对实际产物内容，不能把 `exit 0` 本身当业务正确性。

## 4. 检查顺序与命令

以下路径均以仓库根为 cwd；新增文件先创建再运行。命令不调用真实产品 provider。

### S1 focused

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/process/test_r1_two_validation_completion.py \
  tests/process/test_f1_input_mutation_invalidation.py \
  tests/kernel/test_validation_request_freshness.py \
  tests/kernel/test_runtime_approval.py tests/kernel/test_runtime_recovery.py \
  tests/kernel/test_runtime_limits.py tests/kernel/test_runtime_progress.py \
  tests/kernel/test_runtime_compaction.py tests/continuity/test_compaction_groups.py \
  tests/continuity/test_goal_controls.py tests/continuity/test_sandbox_verified_done.py \
  tests/tui/test_app.py tests/tui/test_adapter.py \
  tests/cli/test_entrypoint.py tests/cli/test_render.py
```

### S2 focused

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/tui tests/cli/test_commands.py tests/cli/test_render.py \
  tests/cli/test_contextual_decisions.py tests/continuity/test_views.py
```

实际 Pilot 操作：连续三轮消息、中文长文本/代码块/宽窄终端（至少 80×24 与 120×40）、
草稿→F2→F3回看→返回→F4编辑/F6提交、暂停/纠正、终态摘要→追问→/new、正常退出/超时后退出/重载失败重试。
检查真实渲染的焦点/滚动/文字可读，不把保存截图成功当作看过。没有视觉检查时如实标注。

### S3 focused

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/acceptance tests/browser/test_f2_owner_shutdown_outclosing.py \
  tests/browser/test_browser_cleanup.py tests/cli/test_018_browser_experience.py \
  tests/cli/test_daily_use_launcher.py tests/cli/test_016_guided_setup.py
```

真实本地 journey 必须先修完驱动/异常清理测试再跑，只用合成 fixture 与 loopback：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/f2_f3_local_browser_journeys.py --journey all --budget-seconds 120
```

不可从该命令 exit 0 单独签 DU-23；记录每条结果及控制器的资源结论。超时/cleanup-unconfirmed 立即停止该真实旅程批次，不自动再启动下一次。

### 最后一次集成与完整 gate

```bash
git diff --check
.venv/bin/ruff check .
PIP_NO_INDEX=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

- 全量只在合集收口时跑一次；若失败后修复影响行为，先 focused，再在最终候选上补最后一次 gate。
- 收集完整退出码/summary；长命令保持可监控，不把超时或截断记通过。
- 本包未授权网络安装。PIP_NO_INDEX=1 限制 pip；它不是网络 sandbox，不代表所有外部操作自动安全。沿项目既有测试隔离运行；发现外部依赖即停受影响检查。
- 无新行为修改不重复刷全量。资料包本身仅做链接/命令/范围审查，不伪称已运行以上新测试。

## 5. 最终安装物 smoke（与源码测试分开）

仅在最终候选构建一次 non-editable wheel：

1. 从明确公开文件 allowlist 物化到新临时 staging：pyproject.toml、README.md、main.py、agent/ 和 first_agent_skill_runner/ 的公开 Python 文件；不用整个仓库复制，不含根 tui/、.env、私有运行态。
2. 使用现有本地 build/runtime 依赖，`pip wheel --no-index --no-deps --no-build-isolation`。临时 venv 安装 wheel，禁止 editable/PYTHONPATH 指回源码。
3. 可复用 `tests/cli/test_016_packaging.py` 的 base 依赖闭包物化模式；不要把可选 UI 依赖缺失伪装成 TUI 验证。若为 TUI 复用本机已安装依赖，要明确这个更弱隔离边界。
4. 从源码目录之外 cwd，验证 `agent.__file__`、`main.__file__` 都在候选 venv site-packages；记录 wheel SHA-256、解释器与依赖来源。
5. `first-agent --version` / `--help`、临时非秘密 setup、FakeProvider 一轮交互/exit、现有本地 Textual 的 Pilot mount及本包关键交互各 smoke 一次；仅挂载不能证明 DU-13–19。
6. 退出后清理本次拥有的临时产物。任何活跃/unknown 资源目录按 FIX-PLAN 保留并报告，不能自动删除。

这不证明在线依赖解析、其它平台、浏览器 extras 的新安装或真实 provider 成功。full pytest 已包含 packaging 测试时可引用同一候选证据，不为凑格式重复构建。

## 6. 真实 API：独立的、当前关闭的门

本包不含 key，不延续历史授权，不改全局默认模型/预算，也不翻阅真实日志找凭据。

未来只有用户明确同意下列四项后才可真实验证：模型与官方 endpoint、请求次数/输出上限和费用上限、凭据的进程内注入方式、测试 workspace/state 与数据外发范围。

- 最多先跑一个代表任务；不自动扩成全部 D 场景，不在失败后无限付费重试。
- 先验证一小次身份/连通性；余额/配额/认证失败立即停受影响操作，不更换/搬运其他客户端 key。
- 凭据只注入 composition root；不能写入资料包、测试命令明文、记录或checkpoint。
- “离线 scripted 已过”和“真实模型自主完成”两栏分开。未批准时明确 NOT_RUN_UNAUTHORIZED，这不是离线验收失败，但禁止对真实成功率作结论。
- D04/D05 原 required_checks 保留；本包 DU-24 仅证明指定离线链路，不将它们的全部真实过程项改成 PASS。

## 7. 交付审查

检查一次最终 diff 是否全部映射 DU 行；检查新增路径是否违背架构依赖；检查用户可见反馈是否与真实状态一致。
确认所有必需项有证据、未运行项有原因、当前资料包与 README 无夸大，最后更新 RESULTS。
不要求新增 Oracle/评审团队，不再自动打开下一轮。
