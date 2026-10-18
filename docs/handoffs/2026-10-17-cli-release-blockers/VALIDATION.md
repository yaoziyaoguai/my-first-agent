# 验收合同与执行边界

本文件是实施要求，不是已经获得的通过证据。终版与 WORK-PACKAGES 联合生效。

## 1. 先复现，保留冻结证据

核对 `git status --short --branch`、`git rev-parse HEAD`、适用 AGENTS 和审计 IDENTITY。
不要先无条件全库回归。先以审计 `probes.py` 的已知构造补正式 tests：测试断言期待修后正确结果，修前 Red 必须由目标行为导致，不能由 import/参数拼写失败造成。

审计 probe 当前 exit 0 只说明诊断完成，其 JSON 含故障观察，**不是 release gate**。修后保存新测试结果；不修改历史 JSON、原答、frozen grader 或原 SPEC 冒充过去已通过。
生产 Runtime + scripted provider 的正反测试必须叫 offline/scripted，不称真实模型。source 与 installed 的来源也必须分别标明。

## 2. 每包 focused

所有命令从仓库根执行，除非明确为 installed 中立 cwd。以下路径在准备包时已核对存在；新增节点名由实施者固定并写入唯一 RESULTS。建议本轮新增用 `test_release_a_`、`test_release_b_`、`test_release_c_` 前缀，方便安装态精确筛选，不据此改名旧测试。

### A：完成下界与实际终态

```bash
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx \
  tests/continuity/test_contracts.py \
  tests/continuity/test_verified_done.py \
  tests/acceptance/test_task_trust_completion.py
```

至少列出 A 表每个输入的预期集合、F1/F2 两个完整 Runtime 红绿节点、双文件实际业务正例、零改写 confirm-only、correction 新增/撤回/沉默/未消费/再新增与持久重开。
边界：不把任意自然语言解释都变成承诺，不把完成下界用作写权限。
若修改了 context projection 或 provider 控制信息，再加 `tests/provider/test_continuity_control.py` 与相应投影测试；只写计划不需要跑。

### B：真实可达 pending 决定的全分支

```bash
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx \
  tests/cli/test_contextual_decisions.py tests/cli/test_commands.py \
  tests/cli/test_render.py tests/provider/test_remote_disclosure.py \
  tests/continuity/test_goal_controls.py tests/continuity/test_checkpoint_v4.py
```

测试不得只 `replace` 拼状态后断言 parser；至少一条用 production Runtime Submit→Pause→Resume 达到孤儿 pending，再用真实 REPL 输入。再留一条落盘→新进程重开证据。可以复用现有 checkpoint/reopen 测试设施，不另造 supervisor。

否定/默认拒绝的观测必须包括：用户看到 pending；exit=0；相对前快照没有新业务 correction；没有新 receipt；provider request 和 tool effect 增量都 0；任务可在后续新进程再次明确应答。
再断言 `run_turn` dispatch、全部 USER_MESSAGE/ToolRuntime 调用增量为 0；request digest、conversation、Goal ID/revision/status、state revision、next_action_seq、active_run 与 checkpoint 均不因回答变化。空回车测试在第二次读取输入时直接失败，确保当前输入后立即返回，不能用后续 EOF 掩盖仍在重问。
肯定必须经现有 typed action、CAS/digest/合法状态验证。合法答复后因 data classes 变化二次请求确认属于正确行为，不得自动补批准。
PAUSED、已 receipt、无 pending、active 其它状态不得误认孤儿 pending；未知结果 recovery 的停止/分类语义不变。

### C：验收器负对照

```bash
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx \
  tests/acceptance/test_task_trust_d04_driver.py \
  tests/acceptance/test_coding_autonomy_grader.py \
  tests/reference/test_candidate_manifest_safety.py
```

`_staged_evidence` 与最终 `evaluate_final` 两层都验证：数值 Goal revision 未增、错 Goal/错 correction、缺字段/非整数/负向版本，即使布尔标签 true 和业务检查 true，也必须 incomplete。合法完整证据保持通过。
保持七补充键 exact true，normal 不注入纠正/继续/救场，staged 的未来要求不得提前泄露。不要修改原 grader 的过程固定 false 项来制造过程证据。

## 3. 最终源码门（集中一次）

A/B/C 的代码、测试、相关用户指南稳定后运行：

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx
```

保存各命令退出码、完整摘要、源码身份。全量观察上限 1800 秒；超时/截断/失败不是 PASS。唯一已知设计 skip 为真实 launchd host gate，不能为补 skip 安装登录项。出现其他 skip 要单独解释。
不要用 tee 的退出码覆盖 pytest，也不要让上一条 installed 的 `-k` 进入 full。`PIP_NO_INDEX` 仅限制 pip，不是所有联网均被禁止的证明。
后续确实改了相关产品/driver，先 focused，最后在稳定身份刷新失效门；不通过一遍又一遍空跑来“保持 loop”。

## 4. 干净候选、一个正式 wheel、安装层

复用 `scripts/build_candidate_manifest.py`，只允许维护本轮公开输入清单与身份标签；不重构安全算法。未跟踪的新公开测试必须显式列入，不能扫描 ignored/private，不能 `git add .`。

```bash
MFA_RELEASE_TMP=$(mktemp -d /tmp/mfa-cli-release.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_candidate_manifest.py \
  --out "$MFA_RELEASE_TMP/candidate" \
  --manifest "$MFA_RELEASE_TMP/source-manifest.json"
```

`MFA_RELEASE_TMP` 是本次专用变量；不得覆盖 HOME/CODEX_HOME 等系统变量。导出前 candidate 和 manifest 两个叶子应不存在；不要把已存在 mktemp 父目录本身作为 --out。
不要删除旧候选、运行历史私人清理脚本或沿用 build/lib。记录新候选无 build/lib、dist、egg-info，manifest 逐文件与当前公开工作树 SHA 相同。

从此候选离线构建 non-editable wheel 到该新父目录的单独 dist 子目录；不向源码根构建。使用已有本地构建依赖/授权来源，不安装新平台。记录 wheel 的绝对路径/SHA 和来源 manifest SHA。新隔离 venv 不继承 system-site-packages，`pip check` 通过。

避免“写结果→哈希变化→重建→再写结果”的循环：manifest 是构建时刻的不可变快照。产品、测试、driver、打包配置和会进入 wheel metadata 的 README 在该时刻冻结。随后只向唯一 RESULTS 或本次证据摘要补写观察时，单列这些文档差异与时间，不声称它们仍逐字等于候选；不因此重跑全库/重建 wheel，也不篡改原 manifest。任何产品/测试/driver/构建输入变化则刷新对应候选与失效证据。

命令模板（尖括号需用本次实际绝对路径替换，不能原样执行）：

```text
<build-python> -m pip wheel --no-deps --no-build-isolation --wheel-dir <new-dist> <candidate>
<installed-python> -m pip install --no-index --find-links <approved-local-wheel-cache> <exact-wheel>
<installed-python> -m pip check
```

若本地依赖缺失，记录具体缺包，申请依赖下载范围；不通过删依赖/污染系统环境完成安装。

安装态从仓库与 candidate 外的中立 cwd 运行 `_019_installed_pytest.py`。它只接受：

```text
<installed-python> <candidate>/scripts/_019_installed_pytest.py
  --installed-site <venv-site-packages>
  --test-tree <candidate>
  --report-path <this-run>/installed-report.json
  --origin-log <this-run>/origins.jsonl
  --basetemp <this-run>/pytest-tmp
  --required-module main
  --required-module agent.runtime.state
  --required-module agent.cli.app
  --required-module agent.cli.render
```

该 runner **没有 --test-node**。使用仅对这一命令生效的 `PYTEST_ADDOPTS='-k "<冻结的选择表达式>"'`；先 collect-only 固定预期 node ID，实际 collected/executed 必须精确对应，零节点、skip、xfail 不算所需行为 PASS。

最低 installed-focused：本轮 A/B 新增行为、原 confirm-only、completion/blocked guidance 一致性、provider pause/resume、snapshot drift、setup、`/new` 与 checkpoint 新进程恢复。新增测试可放已有文件；如单独建测试模块，显式加入候选清单。
所有产品 module origins 必须来自该 wheel 的 site-packages；父进程 guard 不自动保护子进程，要记录子进程解释器、main/runtime origin。保留现有源码污染正/负对照；缺模块必须失败，不准 fallback。
测试依赖的 fixtures 可以来自候选测试树，不等于产品可从源码导入。

复用 `tests/cli/test_016_packaging.py` 的原生入口/来源负对照；全量门已覆盖其内部构建。不必再无理由重复构建。正式 wheel 需要自己的安装 origin 与本轮行为证据，不能把包装测试临时生成的另一个 wheel SHA 当正式 wheel。

最短用户流程（离线 scripted，明确标注）：在上述安装物上，专用合成 state/workspace → setup 非秘密字段、取消不落 key → 小文件任务真实 Runtime 到 VERIFIED_DONE → `/new` → 第二小任务 → 退出/新进程恢复 pending 并拒绝。前后状态与产物由外部测试核验。不增加第二生产模型循环，不把 fake echo smoke 冒充编码任务完成。

随后按 WORK-PACKAGES C.2 验证同一 JourneyOperator 的安装装配，重点检查父子进程 origin 和源码污染反例。变量/记录中明确区分 `source_candidate`（构建源码副本）与 `task_workspace`（D04 被修改的业务 fixture）；绝不能把 First Agent 自己的源码候选当作模型任务 workspace。

## 5. 有界真实模型：需要当前授权，非默认开跑

### 5.1 一次性确认清单

到这一步缺授权时统一问：provider、model、endpoint、thinking mode；唯一允许读取的凭据环境变量名/注入来源；只外发本次合成 workspace 的资料；累计物理请求/墙钟上限；脱敏证据保存位置。历史 manifest 的授权布尔值不是当前人类授权。
禁止从 Pi/Claude/历史会话找替代 key；不把值写入 prompt、CLI 字面量、文档、仓库或输出。

建议上限供用户批准：每个样本最多 40 物理请求；三样本和所有重试累计最多 80；累计墙钟 60 分钟；driver 的 `--max-consents 40` 是**每阶段**治理确认上限（staged 有两阶段），最终分阶段及合计报告。staged 只有一个计划恢复，其它恢复不可用于救场。
当前代码已核对：`JourneyOperator.resumes` 记录救场且恒为 0，计划恢复由 `resume_sent` 单独记录；`--max-resumes` 虽被解析/透传，但不控制 `_next_resume`。本轮命令统一传 `--max-resumes 0`，不把此参数冒充额外安全保护，不为它新增产品行为。零救场由既有 operator 行为与负对照证明。
这不是费用无上限，也不是 40 次就应当成功的性能承诺。先样本一，通过后再二、三；失败请求同样计数，重启不能清零。到 401/429/额度/硬上限停止付费操作，不轮换 key/模型、不自动加额度/输出上限。没有新可证伪假设不得重复同一失败。

### 5.2 三个样本，不顺手扩展

| 样本 | 必要输入与动作 | 必须证明 |
| --- | --- | --- |
| E1 normal | 新鲜、未完成的原 D04 fixture；一次初始用户任务；无额外业务提示 | 原两个业务检查 true、七个补充项 exact true、durable VERIFIED_DONE、continue/correction/救场=0 |
| E2 staged | 明示派生 fixture，未来纠正不提前泄露；固定时点一条 correction；消费后 pause；新 PID resume | C 的强绑定证据全部成立、结果业务正确、未知副作用不重放；只有预定纠正和恢复 |
| E3 already-correct | 使用 E1 通过后的合成文件作为新任务输入，独立 state-root；不再 prepare 抹掉成果，不塞“不要凑改动”等救场提示 | 业务不变、零文件写效果、当前内容验证证据、durable VERIFIED_DONE、无循环 claim 到 fatal |

E3 是合法 no-op 场景，不是 E1 fresh 的替身。不要复用 E1 已闭合 Goal 来宣布新任务完成。可以复用已有固定初始请求与 observation/operator，通过现有 run/composition seam 做专用验证；别给生产增加第三模式或通用 runner。先离线证明路径能工作，再用有限真实调用。
E3 的“零写入”具体指业务交付文件字节不变、`write_file/edit_file/make_directory` 执行次数为 0；正常 pytest 产生的测试缓存、产品保存 checkpoint 和本次证据文件不算强制改写业务文件，但必须放在授权的合成范围内。用独立业务文件 SHA 和实际工具效果计数同时验证，不以 Git diff 空或模型说“未修改”代替。
E3 真失败时保存最小脱敏证据，区分缺证据提示/控制协议/模型行为；只有能定位到本包涉及的实际原因才最小修复。不能猜测产品有强制写入规则后删门，不给 operator 加“继续”、指定工具/文件或失败解释。

现有 D04 CLI 的真实参数已核对：

先把 `tests/acceptance/fixtures/d04_resume_correction` 的公开 fixture 显式复制到本次独占的新工作目录（`copytree` 的目标须不存在），核对原 SPEC SHA 与 driver 的 `ORIGINAL_SPEC_SHA256`。`prepare` **不是创建 fixture 的命令**：它要求目录和 SPEC 已存在，会清该专属副本的 `__pycache__`；`--staged` 还会派生 SPEC。只能对本次合成副本调用，不能对产品仓库、用户项目或 E3 的已正确副本调用。

```text
<python> scripts/run_task_trust_d04.py prepare <fresh-workspace> --result <prepare.json>
<python> scripts/run_task_trust_d04.py prepare <fresh-staged-workspace> --staged --result <prepare-staged.json>
<python> scripts/run_task_trust_d04.py journey <workspace> --mode normal|staged
  --state-root <this-sample-state> --ledger <this-sample-ledger> --result <this-sample-result>
  --provider openai_compatible --model <authorized-model> --base-url <authorized-endpoint>
  --credential-env <authorized-env-name> --thinking-mode <authorized-mode>
  --max-model-attempts <this-ledger-cumulative-ceiling> --max-consents 40
  --max-resumes 0 --wall-seconds <min-1800-and-total-remaining-seconds> --timeout 240
  --installed-site <this-wheel-site-packages> --origin-log <this-sample-origin-log>
```

这是授权且 C.2 已实现/离线通过后的模板，当前不得据此付费执行。最后两个 installed 参数是本包新增要求，不能声称现有脚本已经支持；其它参数已用 --help 核对。各样本 ledger 分开保存，外层另汇总累计物理请求；三条各有40不代表总授权120。默认 source runner 会把项目根加到 sys.path，不能仅换解释器就称 installed-real；必须有 C.2 父子真实来源证据。
`--max-model-attempts` 是该 ledger 的**累计上限**，不是本次新增额度。设 L 为该样本已有 ledger 请求数、T 为三样本/重试总数，则新进程上限为 `min(40, L + (80 - T))`；`T >= 80` 或 `L >= 40` 就不启动。staged 两阶段保留同一 ledger 与同一上限；同一样本重试沿用 ledger 累计，不重建空 ledger 逃避上限。每样本 `--wall-seconds` 至多 1800 且不超过总剩余 3600 秒；超限失败不能被最后成功覆盖。
driver 还会读取冻结 TASK-MANIFEST 的 model/预算守卫；启动前只读核对它与当前用户授权交集，不改 manifest 绕过。配置不匹配时停在本地记录具体字段，请用户决定，不自行换 provider/model/thinking。
本次核对的冻结配置为 openai_compatible / deepseek-v4-flash / disabled，单窗口40请求/1800秒；这是 runner 接受的配置，不是当前调用授权。物理模型请求账本由 `agent/transport_audit.py` 在 HTTP adapter 发送前记账并检查累计上限，`openai_http.py` 的 recorder 在 stream POST 前调用。计数只取合法 kind=model 行；本三样本不启用 Web/MCP 等额外外部工具。保留现有 `tests/provider/test_transport_audit.py` 的累计/跨进程负控，不把治理点击数当请求数。

### 5.3 分开记录，不挑成功

必须分别记录：候选源码 manifest SHA；wheel SHA；执行来源 source/installed；provider/model/config 非秘密字段；请求数/耗时；普通工具审批、外发确认、显式范围授权；计划纠正/恢复、额外催促/诊断/救场；typed 终态；业务外部结果；文件效果与重放证据；每次失败及停因。
外部 grader/探针不反馈给实现模型。自动同意只限用户当前批准的本次合成资源，普通 y 不扩大成全局权限。
**最终裁决：** source-real 与 installed-offline 可以作为分列候选证据，但不能签“当前安装版 CLI beta”通过。本包 E1/E2/E3 都直接在 C.2 的同一 non-editable 安装物上运行，不增加付费样本数量；任一实际产品 import 落回 source 就不是 installed-real。安装接入真实阻塞时如实记 UNRESOLVED，未授权时记 BLOCKED_AUTHORIZATION，不自由降级验收门。

## 6. 收口、状态与停止

在唯一 RESULTS 顶部更新当前状态，追加每包证据表；不新建第二套 current：

| 包 | 修前失败/原因 | 修复位置 | focused | installed | real | 未完成与精确身份 |
| --- | --- | --- | --- | --- | --- | --- |
| A | F1/F2 | 待执行 | NOT_RUN | NOT_RUN | E1/E3 NOT_RUN | |
| B | F3 | 待执行 | NOT_RUN | NOT_RUN | E2 涉及，拒绝分支离线证实 | |
| C | F4 | 待执行 | NOT_RUN | 安装证据单列 | E2 NOT_RUN | |

只按真实结果标：LOCAL_VERIFIED、INSTALLED_VERIFIED、REAL_VERIFIED（明确是否 installed）；缺授权 BLOCKED_AUTHORIZATION；可靠业务检查正确但未收尾 INCOMPLETE_CLOSURE；typed done 且可靠业务判据为 false 才是 FAIL_FALSE_COMPLETION；缺键/类型错/探针异常或绑定缺失是 INCOMPLETE_EVIDENCE，不冒称已证明业务错误；范围内未定位 UNRESOLVED。这些是报告分类，不新增产品 RunStatus。
任何失败/未跑层都必须留缺口，不能用总测试数、最后一句“完成”、driver exit=0 替代产品 durable 状态。
范围外问题仅登记优先级/最小证据，不顺手修。所有包与所需授权门闭合后停止；不自动 commit/push/merge/tag/release，不自动再发 Oracle 或开启下一轮。
