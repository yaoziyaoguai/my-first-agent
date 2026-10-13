# 验证顺序、证据边界与交付格式

本文件配合 [START-HERE](START-HERE.md) 和 [WORK-PACKAGES](WORK-PACKAGES.md) 使用。这里只规定验证，不扩大执行授权。实际顺序是 W2、W1、W3、W4、V1 的增量，再做 §5 安装检查，最后 §4 完整门；章节编号不是另一个执行顺序。

## 1. 先锁定身份，不先跑全库

接手时记录 HEAD、分支、已有修改清单、Python/OS、pytest/httpx/Textual/Playwright 版本及实际安装位置。读取包元数据即可，不输出环境变量全集，不读取凭据、私人配置或旧运行日志。

开发环境 Textual 8.1.1 不满足 `pyproject.toml` 的 `>=8.2,<9`。先用符合声明的本次独立测试环境，或在本次授权允许时补齐依赖；不要全局升级，也不能降低声明。若只能跑旧环境，结果明确注明不满足声明，最终声明依赖环境门保持未验证。离线缓存不足且未获网络安装授权时，记录对应阻塞，继续不受影响测试。

建议用新建、唯一的 `.local/reliability-closeout/<run-id>/` 存放本次合成测试输出，或独立临时根；不得复用/读取旧 `.local/q3` 或其他任务的数据。公开报告只保留脱敏摘要、测试命令、退出码与文件哈希。最终结果继续写旧包的 [RESULTS.md](../2026-10-11-product-reliability-closure/RESULTS.md)，不新建另一份进度真相。

## 2. 每项先 Red，再做最小 Green

W1/W2/W3 的 Red 必须证明行为缺陷，不是 import/syntax 错误；保留断言、输入/结果摘要与退出码。W4 先定位失败阶段再建立回归；V1/V2 先证明证据负对照能被拒绝，不虚构产品缺陷。修复后记录同一回归的 Green，再跑该项 focused。新测试文件只有完成创建后才能使用下面对应命令。

下列示例假定 `.venv` 已满足项目声明；否则用接手时记录的合规 Python/ruff 绝对路径替换，不能让 shell 默默选另一个解释器。

### W1

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/kernel/test_validation_request_freshness.py tests/continuity/test_reopen_invalidation_q2.py tests/process/test_managed_web.py
```

必需证据：真实服务在 A 验证之后确实写入；实际 stop receipt 已进入被检查的 state；旧 A 被拒，同参数新 A 执行并恢复信任。还要有资源活跃、失败/UNKNOWN、多 writer、重复 stop、A/B 组合、checkpoint reopen/compaction 的合同矩阵，不用单条 happy path 替代。

运行期只读诊断仍应可用。不得通过禁止任何验证、永不完成、重复执行所有验证或按参数永久去重来获得表面通过。每项门分别报告 `resource_closed` 与 `validation_fresh`，两者互不替代。

### W2

建议新建的测试文件完成后运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/reference/test_candidate_manifest_safety.py
```

所有危险路径负例在本次临时 Git fixture 中运行。每例前后比对 sentinel 字节；无论输出是否为空，已有目标都不应被删除或覆盖。必须证明 manifest 目标不安全时也不会先创建/损坏 output。

合法示例使用「仓库外、已存在、本次拥有的同一物理父目录」下尚不存在的 `candidate` 与 `candidate-manifest.json` 两个同级目标。macOS 系统临时目录可能通过 `/var` 别名到 `/private/var`：先规范化已有父目录并检查它与源仓库边界，再指定两个不跟随链接的新叶子；不要一刀切禁止系统路径别名，也不要丢失叶子链接身份。

复制失败、exclusive 创建竞争、输入链接/非普通文件也需失败测试；禁止拿真实仓库、家目录或用户目录做 destructive negative control。

### W3

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/provider/test_deepseek_flash.py tests/provider/test_continuity_control.py tests/provider/test_kernel_providers.py
```

必须同时证明 disabled 正常 JSON/tool continuation 成功，以及 enabled/default 的原保护仍生效。MockTransport 是离线协议证据，不是真实 API 证明。不要仅把 `missing_reasoning_continuity` 捕获后返回空成功。

### W4

单次最小复现命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/reference/test_015_e3_harness.py::test_015_offline_gate_timeout_cleans_owned_process_group
```

遵守 WORK-PACKAGES 的诊断分配：本轮最多8次真实 fixture、累计最多10分钟、单次最多60秒。不是失败后无限重跑，也不是必须用满；第一次失败立即保留该次阶段与事件，不能只留最后一次成功输出。

根因明确并完成最小修复后，至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/reference/test_015_e3_harness.py tests/automation_hosts/test_posix_supervisor_cleanup.py tests/process/test_managed_web.py
```

仅当实际修改 `agent/process/group.py` 等共享 primitive 时追加相应调用方：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/process/test_group.py tests/process/test_runner_group_cleanup.py tests/process/test_process_cleanup_recovery.py tests/subagent/test_process_runner.py tests/subagent/test_process_termination_contract.py tests/automation_hosts/test_posix_owned_cleanup.py
```

不是要求反复跑这些集合；修复批次稳定后各跑一次。`cleanup_unknown` 的负例仍必须存在。模拟不能替代真实受控进程退出、回收、身份及有界耗时的检查。

不要运行 `scripts/run_015_e3.py` 的总入口来顺便验证：它会重复整套离线/materialized 门并继续真实 provider 旅程，超出本包当前授权。这里使用的是该脚本的指定 fixture 测试。

### V1

建议新建的测试文件完成后运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_resume_effect_no_replay.py
```

必须保留进程 A/B 的不同 PID、durable PAUSE、正常 resume 入口、checkpoint/result 身份、实际效果计数、没有重述任务的输入记录、负对照与合法新意图对照。PID/合成数据仅属于本次 fixture，不扫描全机用户活动。

不能只证明“所有工具都被挡住”：恢复后的新操作 Y 应经正常授权实际执行。还需用 callable 内屏障真实产生 EXECUTING 已保存、效果已发生但 RESULT 未保存的崩溃窗口，验证新进程进入 UNKNOWN 而不重做；不是把编造的 UNKNOWN 文件当崩溃过程证据。

仅有 Runtime 对象重建不是新进程；仅有14个唯一 call ID不是语义零重放；把文件写成同样内容也无法区分是否执行两次。非幂等效果计数是本地验证 oracle，不能把它改成“只看目标最终内容正确”。

区分 `/resume` 的控制段与恢复后的推进段。当前 `ResumeGoal` 本身不调用模型/工具；必须另外按 WORK-PACKAGES 通过不重述任务的正常“继续当前任务”入口经过一次 production loop，不能用天然零调用的控制动作冒充后续推进证明。真实模型旅程也分别记录这两段；不要求改变现有 `/resume` 产品语义。

## 3. 真实本地资源与浏览器的最小范围

W1 的实际 writer 和 W4 的实际进程清理属于必需的本地资源证据，与是否有模型 key 无关。只能操作本次 fixture 拥有的资源；记录对应资源 ID/PID/PGID、结果、清理确认和耗时。不要创建 launchd 登录项，不接管个人 Chrome。

本轮不默认重新跑全部浏览器旅程。如果实际修改了 managed-web owner/stop、共享进程清理或 browser lifecycle，才补受影响集成边界：先跑驱动自身的 failure/cleanup 回归，再在已有可用 Playwright 环境运行本次专属 loopback 旅程。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/acceptance/test_daily_use_browser_driver.py tests/acceptance/test_daily_use_browser_driver_ev.py tests/browser/test_f2_owner_shutdown_outclosing.py tests/browser/test_browser_cleanup.py
```

现有本地旅程入口：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/f2_f3_local_browser_journeys.py --journey all --budget-seconds 120
```

检查总退出码、每个 journey 的目标断言、failure_codes、timeout/output 上限和清理确认；总 exit0 不替代逐项。缺浏览器依赖时不偷偷联网安装。若代码未影响该边界，记录“本轮未触及，沿用历史覆盖说明”，不伪造本次重跑。

## 4. 最终完整项目门：只在最终代码上集中运行

所有本地修复、focused 及 §5 增量安装检查完成后，冻结并记录此时代码差异与输入哈希，再运行：

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx
```

三条分别保留退出码和完整摘要。按项目当前配置包含整个测试树，不删除 acceptance 来得到更好数字；必要环境 skip 逐项列原因。新增未跟踪文件也必须检查，不以 `git diff` 没显示为由漏掉它们。

检查 pytest 配置没有隐藏的 `-k`、`--ignore` 或 rerun 插件干扰本轮；清除先前 installed 选择条件。完整门总观察预算为1800秒，超时非通过，按本次精确 owner 做有界清理，不无限等待。保存每个底层命令的真实退出码，不能让 `tee` 的成功覆盖 pytest 失败。`PIP_NO_INDEX=1` 只限制 pip 取包，不是禁止全部网络的证据。

有失败、超时、截断，完整门就是未通过。单独复跑通过不能改写原失败结论；必须完成 W4 类根因处置或保留 UNRESOLVED。若全量暴露本轮造成的新缺陷，修复后先跑其 focused，再在最终身份上重跑完整门；这不是要求每个小修都全库重跑。

历史哈希绑定 evidence 原文的既有空白问题不做顺手格式化；只对本次新增/修改的内容执行相应整洁检查，明确基线与本轮的差别。不要修改 frozen grader 或测试预期来隐藏产品失败。

## 5. 独立安装检查：最少必要证明，不复用旧构建残留

### 5.1 新的干净候选与身份

先完成 W2，才调用修复后的构建脚本。使用仓库外、本次新建并拥有的物理父目录和两个不存在的同级叶子；不能对旧候选执行 `rmtree`，也不运行旧私人 `.local/q3/clean_candidate_build.py`。本次合成日志可以在 §1 的新 .local 目录，但候选导出目标不能在源仓库内。

```text
<合规 python> scripts/build_candidate_manifest.py --out <本次父目录>/candidate --manifest <本次父目录>/candidate-manifest.json
```

尖括号是本次执行者必须填入、记录的绝对路径，不可原样执行。不要传已经由 mktemp 创建好的根本身作为 output；使用其下不存在的 candidate。

清单必须包含本次新增回归、全部必要产品文件和现有测试依赖；不能仍用硬编码“2026-10-11这23个文件”宣称覆盖本轮。只显式加入获准公开路径，不扫描收集所有未跟踪/ignored 文件。逐项验证 candidate 与当前源文件的哈希；wheel 单独记录哈希及其来源 manifest。记录候选构建前不存在 build/lib、dist、egg-info 的事实。

### 5.2 现有原生包装回归

```text
<合规 python> -m pytest -q -rx <本次父目录>/candidate/tests/cli/test_016_packaging.py
```

这个现有集合以测试文件位置定位候选根，会在隔离 venv 做 wheel/入口/离线任务和来源负对照。记录它实际构建/安装的 wheel 身份；若另有 §5.1 的正式 wheel，不能因为源码相同就混用两者的文件 SHA，应让正式 wheel 也有对应入口/行为来源证据。它不证明真实 API，也不证明所有 TUI extras；不得将其写成完整 installed 全量。

### 5.3 修复行为确实来自安装物

在本次新 venv 非 editable 安装上述新 wheel，从仓库外的中立 cwd 执行。不要仅换 Python 后仍在候选源码根运行测试。产品导入必须来自本次 site-packages；删除 PYTHONPATH 中的开发/候选源码入口，不能借 source fallback 救活缺包。

最低覆盖：W1 的关闭后失效/显式重验，W3 的 disabled 正例与 enabled/default 负保护，以及 V1 的新进程 resume（父子进程都使用本次安装解释器/来源）。W2 是开发构建工具，不要求进入产品 wheel；W4 若改的是共享产品逻辑，补一个实际受影响的安装态调用；仅改仓库 harness/fixture 时不宣称其在 wheel 内。

优先直接复用 `scripts/_019_installed_pytest.py`：它在导入产品及 pytest 收集前安装 guard，CLI 固定向 pytest 传整个 `test-tree/tests`，**没有**任意 test-node 参数。通过 pytest 原生 `PYTEST_ADDOPTS` 的本次冻结 `-k` 表达式筛选增量节点即可，不修改 runner、不新增安装框架。执行前列出期望 node ID；报告里的 collected/executed 集合必须与它精确一致，deselected 另列，零节点、skip/xfail 不能算完成。此办法的依据见 [pytest 环境变量文档](https://docs.pytest.org/en/stable/reference/reference.html#envvar-PYTEST_ADDOPTS)。

runner 必须启动在中立 cwd；所有必需产品模块的 `__file__/__spec__.origin` 在本次安装根。新子进程需要同样的来源约束，父进程 guard 不会自动跨进程继承。现有某些 managed-web 测试直接由测试 ROOT 拼接源码中的 child；那不算 installed child。安装态旅程应通过生产 owner 从其已安装 `__file__` 定位 child，并记录实际 spawn 脚本路径及摘要。保留现有 source contamination 负对照；安装物缺模块时必须失败，不能回落到源码。

runner 的真实 CLI 参数只有：`--installed-site`、`--test-tree`、`--report-path`、`--origin-log`、`--basetemp`、重复 `--required-module`。`PYTEST_ADDOPTS` 只在这一条命令的子进程环境设置，之后清除；按报告同时检查 pytest 退出、收集/跳过、各 phase 与 origin error。这里是 installed focused，不再额外跑第二遍3700多项 installed/候选源码全量。

安装成功但回归来自 source，状态只能写“安装 smoke 通过 + 源码回归通过”，不能写“installed 回归通过”。最终生产代码变化后重新物化/安装受影响身份，不能拿修改前 wheel 继续签收。

## 6. 真实模型验证是单独一层，不隐含无限额度

本包没有继承上一执行者报告中的“费用无上限”或 key 读取权限。接手者必须从当前用户授权核对：provider、model、endpoint、凭据来源、允许发送的合成数据、最大调用/时间或费用上限，以及是否允许这次独占资源。不要把过去聊天里的 key 抄进 prompt 或资料包。

没有这些授权时：继续 W1–W4、本地 V1 和 V2；真实层记录 `BLOCKED_AUTHORIZATION`，说明缺哪个字段，不称整体真实验收完成。

获得当前授权后，仅补两个受影响的最小样本，不重启全能力 dogfood：

1. **W3 canary**：全新 disabled 会话，一次简短正常响应；必要时加一次有界工具来回。未指定/启用模式的线上样本是否追加按当前授权及离线覆盖判断。401/429/协议错误分别记录，不尝试搜索其他 key 或自动换供应商。不要拿原 enabled 会话做模式迁移。
2. **V1 真实恢复过程**：沿用旧包公开 D04 fixture 与现有合法入口，真实 PAUSE→退出→新进程 resume，不重述任务/纠正。使用本次实际效果计数与 intent/result 关联，不只数 call ID。先完成离线驱动负对照再用付费调用；跨新进程共用同一 transport audit ledger 与累计 attempts，不清零预算。operator 只答治理提示，不给文件/工具/诊断路线。

旧包 [VALIDATION §Q3](../2026-10-11-product-reliability-closure/VALIDATION.md) 提供公开 fixture 导航与 grader 边界，不授予它里面的历史权限。D04 grader 的 `resume_without_restatement` 与 `no_effect_replay` 固定 false：单列已有业务子谓词与本次过程证据，不改 grader，不把 grader exit1写为全PASS，也不把它当新的产品失败。

付费尝试上限在调用前填具体数字；若用户仅批准读取 key 却没批准成本/数据范围，先问清楚。执行中遇预算边界停止对应样本，报告最后完成状态，不把预算结束称作产品已完成。模型自己提出新的同参效果与内核自动重放必须分别归因。

## 7. 最终报告模板与判定

把下表实际结果写入旧 RESULTS 的本次补漏小节。不要提前勾选，也不要以“共几千个测试”代替逐项结论。

| 项 | 状态 | 修前区分证据 | 修复/无须修改的理由 | 本次身份、命令、退出码、摘要 | 仍缺什么 |
| --- | --- | --- | --- | --- | --- |
| W1 | TODO | | | | |
| W2 | TODO | | | | |
| W3 | TODO | | | | |
| W4 | TODO | | | | |
| V1 本地 | TODO | | | | |
| V1 真实模型 | NOT_RUN | | | | 当前授权未确认 |
| V2 完整门 | TODO | | | | |
| V2 安装物 | TODO | | | | |

状态用 `FIXED_FOCUSED`、`VERIFIED_LOCAL`、`VERIFIED_REAL_RESOURCE`、`VERIFIED_REAL_MODEL`、`PROVEN_NO_PRODUCT_CHANGE_NEEDED`、`BLOCKED_AUTHORIZATION`、`BLOCKED_ENVIRONMENT`、`UNRESOLVED`，必须写覆盖层，不能把同一 VERIFIED 复制到全部列。产品整体身份继续保持 `implemented-candidate`，本包不自动 promotion。

最终摘要必须包括：

- 产品代码有没有改、哪些行为改变，哪些没有改变。
- 完整门精确结果、skip 原因、异常/偶发是否定位；第一次失败和最终修复证据都保留。
- 本次候选、wheel、安装来源和测试身份是否一致；哪些证据只是历史报告。
- 本地资源/真实 API 是否实际执行、成本上限与实际用量、是否清理确认；不输出敏感内容。
- 最终 Git 分支/HEAD/dirty 清单。默认不 commit/push/tag/publish，不删除用户内容以制造 clean。
- 剩余必要问题及唯一下一动作。W4 unresolved 或任一必要门缺失时，结论为“本地部分完成，验收未闭合”；仅缺当前真实授权时，最多称“本地与安装层闭合，真实层待授权”，不能声称生产级或所有功能已验证。

这张表的目标是精确结束本次补漏，不是制造下一轮能力扩张。
