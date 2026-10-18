# CLI 个人试用审计 — 2026-10-18

本文件是本次独立审计的固定快照，不是新一轮执行包或第二份可变进度表。项目可变记录仍为 `docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md`。

## 结论

**可以现在开始 macOS、单用户、CLI、项目副本上的人工验收式试用；不能签署当前候选“所有业务验收通过”，也不能当成无人检查的可靠交付工具。**

这次实施有实质进展，A/B/C 不是只写了文档。独立复核确认明确文件遗漏守卫、引用/版本号排除、正常确认零改写、CLI pending 外发决定和 staged 验收器均有有效修复与测试。安装版能够启动，实际产品代码与工作树一致。

仍有一个新发现的验证义务边界缺陷、一个已报告但不能豁免的真实业务失败、一个审批入口不一致及一处影响上手的文档矛盾。下一步应收口这些问题并交出固定试用入口，不应再扩展能力、重开全模块优化或添加通用语义判断框架。

## 1. 审计身份与权限

- HEAD：`0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`；分支 `main`，本地跟踪显示与 `origin/main` 对齐（本次未 fetch，非独立远端状态证明）。
- 开始时 26 个 tracked 文件有改动，另有公开资料包/测试及未知未跟踪文件。它的最新工作尚未形成 Git 提交；HEAD 本身不包含这些修复。
- 本次只做源码/公开记录审查、离线诊断与安装态离线启动；未修产品代码、未读取凭据或私人会话、未发真实模型请求、未新增 Oracle 咨询、未 commit/push 或改登录项。
- 未读取/改动 `result.phase.json`。本次新增仅此审计报告；离线试用夹具使用本次独占临时目录。

## 2. 必要问题（按优先级）

### F1 / P1：验证义务重绑定未绑定工作目录

位置：`agent/runtime/state.py:3414`、`:3431`、`:3479` 的 `_rebindable_failed_process_obligation`。

旧、新命令的“等价”只比较 executable 与 argv；收集旧调用时同样丢弃 cwd。当前 Goal、失败退出码、用户 opt-in 虽受约束，但不能证明两次命令覆盖同一组文件。

独立离线 reducer 诊断复用了 `tests/process/test_obligation_rebind.py` 的合成 receipt/approval 夹具：旧调用 `pytest -q`、cwd=`.`、exit=2；新调用仍 `pytest -q`，仅 cwd 改为 `smoke`；显式批准重绑定后，旧 `required-local-process` criterion 被换成新 fingerprint。结果为 `rebound=true`。控制组 `python3 -m pytest -q`、同 cwd 同样允许；换成 `smoke/pytest` 则被拒绝。

**影响**：根目录验证失败后，子目录中通过的少量测试可能承接原本的验证义务。批准执行新命令不等于两条命令验证范围相同。当前重绑定披露中的旧/新命令文字也没有说明该 cwd 差异。

这是对实际 reducer 的独立反例，不是已运行完一条真实模型误完成旅程的证明；但足以推翻当前“canonical 等价”资格判断的完整性。

最小处置：把受信任的 cwd 身份纳入资格判断；仅 cwd spelling 改变而物理身份相同的情况需要明确处理，不能靠任意字符串标准化跳过身份验证。对其它会改变验证范围的参数保持 fail-closed。补 `cwd 根→子目录` 的拒绝负控、同目录合法 wrapper 正控及真实 Runtime 审批链测试。不引入第二套授权/执行系统。

### F2 / P1（交付验收）：最新 E2 仍是业务失败，不能用“模型问题”豁免

公开记录 `RESULTS.md:786` 自报最新同一安装物 E2 已 `verified_done`，但 `latest_correction=false`、`conflict_rejected=false`：需求要求新旧参数同时出现就拒绝，实现却只在两者值不同时拒绝。

既定 `docs/handoffs/2026-10-17-cli-release-blockers/VALIDATION.md:187` 明确将“typed done + 可靠业务判据 false”定义为 `FAIL_FALSE_COMPLETION`。本次核对了该合同及 `scripts/run_task_trust_d04.py:583` 的判定实现；未读取真实会话/日志或重跑付费样本。因此本项的真实观测依据是实施者公开记录，不能冒称本次独立真实复现。

模型理解偏差可以解释实现为何出错，却不能把失败改成通过。也不能反过来断言仅此一次失败证明 Runtime 的所有证据逻辑都坏了：当前 closed oracle 主要证明文件字节、获批准的进程成功、来源等，界面已有“这些证据不保证语义正确”的说明。

最小处置：报告如实标失败；保留冻结需求和 grader；检查本任务关键边界是否进入实际验证，不让文件存在/read-back/普通测试 exit 0 被当成完整需求正确的证明。不得靠改 grader、删同值冲突条件、继续随机重跑至成功来收口，也不为此发明通用 NLP 裁判。任何真实复测仍需有效的调用与预算授权。

### F3 / P2：同一审批，`y` 与 `/approve <id>` 结果不一致

位置：`agent/cli/app.py:281`、`:397`。

新 pending 披露明确说本次批准会同时重绑定失败验证义务，但只有 `y` 分支设置 `authorize_obligation_rebind`；显式 `/approve <id>` 分支未设置。

在同一合成 pending state 上独立调用真实 CLI parser/reducer：

| 输入 | 显示重绑定披露 | action 授权重绑定 | 旧失败义务替换 |
|---|---|---|---|
| `y` | true | true | true |
| `/approve request:1` | true | false | false |

**影响**：使用明示审批命令的用户仍可能卡在旧失败义务，尽管提示承诺本次批准会重绑定。临时试用选择屏幕提示的 `y` 可避开此分支，但不是最终修复。修复应保证同一显示快照、同一明确同意范围的入口一致，不扩大 TUI/headless 的默认权限。

### F4 / P2：上手文档与交付入口尚未收口

- `README.md:103` 明确日用 base CLI，不推荐 TUI；`docs/guides/daily-use.md:23` 的推荐安装却仍装 `[tui]`。TUI 已知恢复后 pending disclosure 展示不完整，不能把它作为默认日用承诺。
- 日用指南支持矩阵仍写真实层待授权，未反映 10-18 最新 E1/E2/E3 的分项事实。
- 当前候选 wheel 和可运行 venv 都在 `/tmp`；该位置适合验收，不是稳定交付目录。`first-agent --version` 只显示 `1.0.0`，本次靠 SHA 确认身份。不能让用户 clone main 后以为得到的就是这轮候选。

最小处置：统一一条 base CLI 安装/启动路线，交出稳定位置的非 editable 安装物及对应 SHA，明确当前已知问题。Git 整理/提交与安装到用户固定目录需要有效授权；本次没有代做。

## 3. 独立验证

### 源码与历史反例

本次运行（完整退出结果）：

```bash
git diff --check
.venv/bin/ruff check .
PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 \
  .venv/bin/python -m pytest -q -rx -p no:cacheprovider \
  tests/process/test_obligation_rebind.py \
  tests/continuity/test_contracts.py \
  tests/acceptance/test_task_trust_completion.py \
  tests/cli/test_contextual_decisions.py tests/cli/test_render.py \
  tests/provider/test_remote_disclosure.py \
  tests/acceptance/test_task_trust_d04_driver.py \
  tests/acceptance/test_coding_autonomy_grader.py \
  tests/reference/test_candidate_manifest_safety.py
```

结果：diff-check clean；ruff passed；**394 passed，40.21s，exit 0**。未重复整库 4000 余项测试；4042 passed / 1 skipped 是实施者自报，不冒称本次独立全量结果。

重新调用旧审计公开 probe 中四个仍兼容的函数：

- 有空格/无空格两种遗漏 CLI 文件反例均停在 `goal_ready`，未误完成。
- `修改app/config.py` 被捕获；Python `3.12`、输入 SPEC 引用、跨分句引文和日志描述不被误认待写文件；礼貌请求仍识别。
- 已正确文件的确认任务到 `verified_done`，文件不变。
- staged 错 fact ID / Goal revision 未推进等伪证据被判 incomplete。

旧 `probes.py` 整体直接复用曾失败：历史 `disclosure_probe` 假设输入 `no` 仍会产生 Runtime action，新实现按合同返回 None；旧 probe 随后把 None 传给 Runtime，触发 AttributeError。这是历史诊断调用约定失配，不标为产品通过或新产品回归。未修改历史 probe；B 分支以当前正式测试与源码复核为据。

### 候选身份与安装态

- wheel：`/tmp/mfa-cli-release.KVQylQ/dist/first_agent-1.0.0-py3-none-any.whl`
- SHA-256：`46bcc2a4a4abf3299ffceb79f8847b4d70d6d1ad50b6dc2b15570917bc9cbf89`
- source manifest SHA-256：`54872bc6fe0340e07e4aef82127f8469daac57d07518636d82850766d9b0db0b`
- 安装入口：`/tmp/mfa-fix3-venv/bin/first-agent`
- 825 个 manifest 输入逐文件复核，仅后续补写的 RESULTS 不同；产品/测试/driver 等冻结输入没有漂移。
- wheel 中 **157 个产品 Python 文件**逐字节比较：当前工作树、wheel、安装 site-packages 三者一致。
- 中立 cwd 的安装态 `--help`、`--version` 正常；版本显示 `1.0.0`。
- 新建独立 workspace/state-root，fake provider 离线执行“启动→一条 echo 输入→`/new`→`/exit`”成功，exit 0；输出 `Sandbox: ready (macOS Seatbelt; workspace-write, network off)`。产品 import 来自安装 site-packages，不是源码。
- 首次离线启动使用 `/tmp/...` 字面路径触发 `Web profile path must not traverse symlinks`；macOS `/tmp` 是链接，改用本次临时目录的物理路径 `/private/tmp/...` 后成功。未放松 no-follow 检查。
- 以上只证明离线启动、适配器和本机装配，不是本次真实模型 dogfood。

实施者最新同一 wheel 的真实样本，应分别引用：E1 正常任务 PASS；E2 中途纠正/新进程恢复的过程链 PASS、业务 FAIL；E3 already-correct 零写 PASS。更早 wheel 的 E2 PASS 不能覆盖最新 wheel 的失败。累计 324 次物理请求是多轮尝试总数，不是 324 个不同日用任务。

## 4. 什么时候开始试用，以及怎么试

**现在即可开始知情、低风险的个人试用。** 尚不能称为面向普通用户的稳定版；试用也不等于免验收。

推荐：macOS 上只使用 CLI；以有备份的项目副本/独立目录为工作区；先做小型文件修改、文档产出、有明确测试命令的代码修复；逐项阅读写入/本地进程/外发审批；最后看 diff、运行已有验收，而非只看 `VERIFIED_DONE`。当前不把 TUI、浏览器、无人值守调度及其它 extras 纳入首轮试用保证。

临时启动模板（替换工作区和全新状态目录；工作区须已存在，路径使用真实绝对路径；shell 须已由用户配置有效 `DEEPSEEK_API_KEY`，本次没有检查它）：

```bash
/tmp/mfa-fix3-venv/bin/first-agent \
  --workspace /绝对路径/你的项目副本 \
  --state-root /绝对路径/全新且专属的试用状态目录 \
  --provider openai_compatible \
  --model deepseek-v4-flash \
  --base-url https://api.deepseek.com \
  --credential-env DEEPSEEK_API_KEY \
  --thinking-mode disabled \
  --without-owner-preferences
```

此命令是用户实际试用入口，会在外发获准后使用真实 API；本审计没有执行它。不要启用 `--tui` 或 `--browser` 来代替这条已核对路径。临时 venv 可能被系统清理；长期使用前须完成 F4 的固定安装交接。

不建议再以“补齐所有 Agent 能力”作为试用前置条件。必要下一步仅是：补 F1/F3 的窄缺陷、诚实处理 F2 的验收与验证范围、完成 F4 的 CLI 交接，然后用真实日常任务收集问题。不得由本报告自动扩张成新一轮架构或功能建设。
