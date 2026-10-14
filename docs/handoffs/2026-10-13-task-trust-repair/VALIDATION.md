# 执行、验证与结案

只验证四个实际修复及其交付边界。用户批准的是准备本包；实施者收到执行指令后按本文件运行。旧报告的权限、日志和预算不自动继承。

## 1. 接手基线与产物

```bash
git status --short --branch
git rev-parse HEAD
git diff --stat
.venv/bin/python --version
```

核对适用AGENTS；不用环境变量全集诊断，不读取私人配置。记录Python、OS、pytest/声明依赖版本；若`.venv`不符合pyproject声明，使用已存在合规环境或离线缓存，不全局升级，不降低声明。当前包本身是预期未提交文档，不能当作垃圾清理掉。

继续用 `docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md` 的新当前摘要和本轮小节。记录R1–R4、C1/C2、I1、G1、E1；不覆盖历史证据，不新建第二份current进度。

本次合成输出使用 `mktemp -d` 创建的唯一临时父目录。候选构建使用其下**尚不存在**的 `candidate` 和 `candidate-manifest.json`，不要把已存在父目录传作输出。不得复用/清理旧 `.local/q3`、旧 `/tmp/v2-*` 或用户目录。

## 2. Red → focused；不要每个修改都跑全库

先分别运行REPRODUCERS的无API探针，转成期望安全行为的回归。Red必须是目标行为断言失败，不是缺依赖/import失败。不要为了抓Red对共享脏工作树stash/reset；修前先运行，或在本次独立公开快照比较。

新增用例优先放已有测试文件。确需新文件时，记录精确路径并纳入本次候选清单；下列命令不自动包含尚未创建的文件。

### R1

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_errors.py tests/kernel/test_runtime_compaction.py tests/continuity/test_resume_effect_no_replay.py tests/provider/test_continuity_control.py
```

必须使用语义故障注入、效果计数、真实保存/reopen、至少一个新进程恢复测试。正常审批pause、未知结果、永不成功保存三条路径都记录。模拟写故障不等于证明真实硬件永不损坏。

### R3

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_contracts.py tests/continuity/test_entry_routing.py tests/continuity/test_verified_done.py
```

覆盖正/禁止/解释/引用/纠正，对比真正Goal义务与完成门，不只测regex helper。

### R2

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_verified_done.py tests/process/test_r1_two_validation_completion.py tests/acceptance/test_coding_autonomy_grader.py tests/kernel/test_evidence_registry.py
```

若创建 `tests/acceptance/test_task_trust_completion.py`，创建后把它加入focused命令。若扩展CompletionClaim，追加受影响的contracts/checkpoint round-trip/provider control测试；不省略旧活动状态无新字段的行为验证。

每条R2场景同时记录：产品状态、当前义务/覆盖、实际文件行为、独立grader两个业务布尔值及补充SPEC断言、模型/工具调用数。反例不能只看模型最后一句话，正例不能只看RunStatus.COMPLETED。

不要把冻结grader的两个过程项false改成true；它们不证明过程。本轮过程证据由可数效果与新进程恢复单列。

### R4

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/cli/test_commands.py tests/cli/test_contextual_decisions.py tests/cli/test_render.py tests/continuity/test_goal_policy.py tests/continuity/test_goal_controls.py
```

交互正例必须从默认提示到合法action和真实Runtime；只有parser flag断言不够。TUI未改不重做界面设计；共享builder变化则追加其受影响测试。

### C1 / C2

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/kernel/test_validation_request_freshness.py tests/provider/test_continuity_control.py
```

在相应文件新增现有P2-2/P2-3的跨层断言，不能只重跑旧测试就勾选。测试调用真实投影函数但使用合成数据/MockTransport，不需要真实provider。正例wire成对；负例确实拒绝缺失/重复结果；不篡改opaque continuation来凑配对。

## 3. R2真实模型：需要单独当前授权，不能拿mock代替

### 授权清单

运行前必须从当前执行对话核对：provider/model/endpoint、thinking mode、凭据的指定注入来源、允许外发的合成数据、累计请求/耗时或费用上限、保存本次脱敏证据的范围。

本包建议（**不是已授权**）：继续现有明确支持的DeepSeek Flash配置，只有公开D04合成workspace，不启用browser/MCP/Skill/SubAgent；两个独立样本各不超过40次物理请求，合计不超过80次，总墙钟不超过60分钟。具体以用户当前确认值为准；产品自身更低的安全限制仍有效，不能擅自放宽以满足建议预算。

不复制真实key到文件包/命令字面量/日志，不读取历史`.local`运行；从用户明确指定的环境变量在composition root注入。缺授权时写 `BLOCKED_AUTHORIZATION` 并继续本地工作。401不搜索其他key，429/余额/额度边界不无限重试。用现有transport ledger累计跨进程实际请求，不能重启清零。

### 最小真实旅程

1. **E1-A 正常完成**：全新D04工作区，按SPEC完成service与CLI行为；允许正常治理审批，但操作员不提示该改哪个文件、不提供实现/失败解释。产品须自己闭合；独立业务grader两项true且新增补充SPEC检查全部通过。
2. **E1-B 新增纠正与恢复**：另一全新、分阶段的D04派生合成工作区，按下面冻结输入及前置条件追加真正的新要求，再正常pause→退出→新进程resume→继续，不重述业务或提供实现提示。最后同样独立验收完整业务；调用次数累计。R1的磁盘故障采用离线注入，不为真实模型反复破坏磁盘。

**E1-B必须在付费前冻结以下过程，防止空验收：**

- 原仓库SPEC、grader和manifest保持原字节与SHA。仅在本次新建的合成工作区里创建并标注`D04 staged variant`：初始SPEC保留标题与原始有界重试段落，不包含以`During the task`开头的未来纠正段落。记录派生SPEC精确内容/SHA及初始prompt；它不冒充原fixture的字节同一性。主模型也不能从manifest任务文案、driver提示或额外附件预先看到未来纠正。
- 初始prompt固定为：`完成当前 SPEC.md 的有界重试功能，并运行 pytest -q 验证。` 后续correction固定为：`补充要求：保留 retry_count 关键字和 --retry-count CLI 选项作为旧别名；新旧名字同时提供时拒绝并报歧义。继续完成任务并运行 pytest -q 验证。` 不允许见到模型输出后临时改变业务要求或暗示修改文件。
- 注入边界固定为：已有当前Goal、发生至少一次正常文件效果之后，第一个尚未终结且接受correction的安全治理交互点。driver先用离线场景证明能识别该点；不新增产品的运行中抢占功能，不直接改checkpoint。如没有观察到合法边界，记录`NOT_OBSERVED`，不能悄悄换新任务当作同任务纠正。
- 注入前保存本次合成任务的版本/义务投影：尚未包含新增旧别名要求，外部别名行为检查尚未全部通过；不得将检查结果或修复提示返回主模型。若模型已提前完成全部别名行为，或初始上下文已泄露后续要求，该样本不能证明新增纠正，记录前置条件未满足，而不是PASS。
- 注入后必须观测到correction已durable、当前版本与相关义务确实变化，随后pause→退出→新PID resume。最后新增别名与歧义行为通过，且产品正确终结。旧覆盖/验证失效的细粒度断言由R2-T5的离线回归证明；此真实旅程不冒充每种持久化故障证明。
- 若选择不制作分阶段派生工作区、仍从完整原SPEC启动，只能报告“恢复旅程”，**不能计为E1-B新增纠正生效**。

不能仅运行默认 `scripts/run_real_coding_scenario.py D04 ...` 就宣称E1-B通过：先检查driver是否真的注入纠正、实际退出/新PID、推进而非只恢复控制。默认脚本的manifest task文字不等于过程已发生。

可复用现有driver/公开fixture，必要时新增本包专用的薄旅程driver及故障测试（例如尚未创建的 `scripts/run_task_trust_d04.py`）；不得做通用评测平台。先离线证明driver遇到业务false、产品未终结、预算耗尽、correction未接纳、恢复失败会如实失败，不根据最后一句文字直接判PASS。

公共物化入口（仅创建新合成workspace，不调用API）：

```text
<合规Python> scripts/materialize_coding_scenario.py D04 <新父目录>/d04-a
<合规Python> scripts/grade_coding_scenario.py D04 <新父目录>/d04-a
```

`<...>` 必须换成本次记录的实际路径。grader完整退出码可能因两个固定false过程项而非0；原样报告，业务字段与本次过程证据分别列，不把整体exit1写成exit0。SPEC补充检查独立报告。

任一样本中，产品报完整成功而外部业务失败，R2就是 `UNRESOLVED`，不能写“模型问题，与产品无关”。诚实未完成比假成功好，但仍不满足正例任务完成目标。不得无限重试挑成功样本；失败后保留本次证据，只有新假设/必要修复和剩余授权预算支持才重跑。修后只重跑受影响证据。

## 4. I1：最终wheel的最小安装证明

先完成所有必要产品修改和真实层导致的修补，再冻结公开输入清单及SHA。缺真实授权可先做本地/安装交付，但不得将来拿此wheel证明后来修改的代码。

复用已有 `scripts/build_candidate_manifest.py` 与 `scripts/_019_installed_pytest.py`。不得重新引入删除/覆盖现有output。前者只自动收集tracked与显式集合：新增未跟踪的公开测试/必要模块必须显式纳入；不使用 `git add .` 或全盘扫描来取巧。允许仅调整其本轮公开输入集合/身份标签，不改变安全算法；核对manifest逐文件匹配当前源。

1. 仓库外唯一父目录、新candidate、新manifest；构建前没有build/lib、dist、egg-info。
2. 从此候选离线构建non-editable wheel，记录源码manifest和wheel SHA；依赖仅用授权/本地来源。
3. 新独立安装target/venv，仓库外中立cwd；产品模块origin必须在新site-packages，不可回落source。
4. installed最小集合：R1连续保存失败/安全pause重开、R3中文正负、R2不完整/完整两个路径、R4当前请求授权；C1/C2若共用这些节点可不重复。执行前冻结具体node ID，执行后逐项核对，零节点/skip/xfail不能冒充通过。
5. `_019_installed_pytest.py`固定整个test-tree/tests；没有`--test-node`参数。使用单次命令局部的`PYTEST_ADDOPTS`冻结`-k`精确选择，并核对实际收集/执行集合。真实参数：`--installed-site --test-tree --report-path --origin-log --basetemp`及重复`--required-module`。
6. 新进程用安装态解释器/产品来源，父进程guard不能当作子进程证明。记录实际子进程来源；保留source污染负对照。

不复跑安装态全库，不重新验证所有历史capability。保留现有包装4项回归作为包装边界；每个不同wheel哈希分开记录，不把相同源码的不同构建物混为同一身份。

## 5. G1：最终完整项目门只集中跑

所有修复及安装检查稳定后：

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx
```

分别记录真实退出码、完整摘要、skip原因。新未跟踪文件需另外检查，不以git diff不显示为由漏掉。无关历史哈希证据不做格式化。确保没有残留`-k`、忽略目录、自动rerun来制造全绿；不要删除acceptance集合。

全量观察预算1800秒；超时/截断/失败不是PASS，按本次测试owner安全收尾并定位。`PIP_NO_INDEX`不是禁止全部网络的证明。若后续改产品代码，先对应focused，再刷新失效的安装/完整证据；这不等于每个小改都重跑全量。

## 6. 交付矩阵与停止条件

在唯一RESULTS记录以下每行，禁止提前填PASS：

| 项 | 修前证据 | 修复/原因 | source | installed | real | 未完成/限制 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 UNKNOWN | 效果1次却被补未执行 | 待填 | TODO | TODO | 本地故障注入/重开，不要求付费模型 | |
| R2 COMPLETION | 真实D04假完成报告+本轮确定性反例 | 待填 | TODO | TODO | E1-A/E1-B待当前授权 | |
| R3 INTENT | 等义中文True/False | 待填 | TODO | TODO | 随E1验证，不另付费单测 | |
| R4 CONSENT | 默认界面没有可用ID入口 | 待填 | TODO | TODO | 本地CLI交互足够 | |
| C1/C2组合门 | 旧报告缺固定回归 | 待填 | TODO | 按受影响节点 | wire离线足够 | |
| I1/G1交付门 | 旧wheel与main不一致 | 待填 | TODO | TODO | 非API门 | |

每项提供命令/node、退出码、输入代码身份、原始失败摘要及修后结果；“不适用”要解释，不写成PASS。

最终摘要必须回答：四个原问题是否逐个解决；有没有新状态/协议字段及其重开合同；是否真正完成E1两个业务任务；人工提醒/诊断/收尾次数、治理批准次数、物理请求数和耗时；最终Git dirty清单。默认保留未提交修改，不擅自commit/push，不为clean删除文件。

R1仍能丢UNKNOWN、R2仍假完成、R3漏明确义务、R4仍需隐藏信息、必要本地/安装/full门缺失，均不得宣告本包完成。仅缺真实授权时可交付“本地与安装层完成，R2真实层待授权”，并给出唯一缺失授权清单。除此不自动开启下一轮能力扩张。
