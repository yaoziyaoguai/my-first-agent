# 验证、候选交付与真实 Dogfood

本文件给执行步骤，不宣布任何修复已通过。所有命令以仓库根目录为工作目录，除非明确写中立候选目录。先核实文件和入口仍存在，不猜不存在的 flag。

## 1. 历史反例探针：可复现，不是验收 oracle

`diagnostics/*.py.txt` 是 2026-10-11 审计时的合成实验副本，后缀用于表明它们是参考附件，不是产品或 pytest 测试。Python 可以直接执行。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/handoffs/2026-10-11-product-reliability-closure/diagnostics/runtime_probe.py.txt --repo "$PWD"

PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/handoffs/2026-10-11-product-reliability-closure/diagnostics/tui_probe.py.txt

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/handoffs/2026-10-11-product-reliability-closure/diagnostics/driver_probe.py.txt
```

- runtime：只使用合成 facts/receipts 和内存 store；不调用 provider，不起工具进程。
- TUI：Pilot、假 provider 和临时内存状态；需当前 TUI 依赖。8.1.1 上的历史结果不能替代声明范围中的最终测试。
- driver：只启动短期、自有 Python child，具有独立 watchdog 和清理；POSIX/macOS 实验，不启动真实浏览器或 API。
- **exit 0 仅表示实验执行完毕。** 原缺陷的“复现成功”不是产品 PASS；看输出的实际谓词，并将必要场景变为常规 assert 测试。
- 探针调用了当前内部测试 fixture；修复后其 API 可能变化。若无法运行，要迁移成等价生产边界测试，不得通过修改参考输出伪造历史证据。
- 这里的 `PYTHONPATH` 仅用于源码审计探针；禁止带到安装物验收。

## 2. Focused gates：按完成批次执行

以下均为现存路径。新增回归优先放相应文件，确实超出文件职责时可新建一个明确命名的测试文件，并加入对应命令；不需要复刻全部目录。

### Runtime / S1

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/kernel/test_validation_request_freshness.py \
  tests/kernel/test_run_result_usage.py \
  tests/kernel/test_runtime_progress.py \
  tests/kernel/test_tool_outcomes.py \
  tests/continuity/test_verified_done.py \
  tests/continuity/test_sandbox_verified_done.py \
  tests/continuity/test_checkpoint_v4.py \
  tests/process/test_f1_input_mutation_invalidation.py \
  tests/process/test_managed_web.py \
  tests/acceptance/test_daily_use_recovery_journey.py
```

如果修改 checkpoint schema、公共 contracts 或 compaction，再增加当前受影响的 checkpoint/compaction 文件；记录理由，不把全部历史 host acceptance 默认拉入。

### TUI / S2

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/tui/test_app.py tests/tui/test_adapter.py tests/tui/test_render.py \
  tests/tui/test_approval_journey.py tests/cli/test_entrypoint.py
```

在声明范围内的 Textual 环境再次运行 UI 回归和一次真实终端启动/退出；Pilot 证明输入状态，真实终端证明可用启动和退出，两者不要混称。

### 驱动与日志 / S3

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/acceptance/test_daily_use_browser_driver.py \
  tests/browser/test_f2_owner_shutdown_outclosing.py \
  tests/browser/test_browser_cleanup.py \
  tests/acceptance/test_f3_driver_receipts.py \
  tests/acceptance/test_f3_driver_typed_status.py \
  tests/cli/test_entrypoint.py
```

只有驱动的故意失败矩阵已经正确判 FAIL，才运行下面的真实本地浏览器旅程：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/f2_f3_local_browser_journeys.py \
  --journey all --budget-seconds 120
```

使用本次专属 Chromium 与 loopback fixture。不得使用个人 Chrome、登录网站或系统登录项。记录两个 journey 的目标结果、总 exit code、超时和资源清理，不只摘一个 `passed`。浏览器依赖缺失时标明未验证，不把 skip 写成功；安装必要浏览器依赖遵守当前网络授权。

### 包与入口 / S4

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx \
  tests/cli/test_016_packaging.py tests/cli/test_daily_use_launcher.py \
  tests/cli/test_entrypoint.py
```

这组测试修复后仍不能替代下节“最终明确候选”的独立安装验证。

## 3. 无 Git 写入也能建立干净候选，但不能伪称已提交

本包不要求 commit 才能验证。请采用显式 allowlist 的临时 materialized candidate，不修改真实 Git index，不把 `git add -A` 当候选收集工具。

### 3.1 候选清单

S0 在 RESULTS 的候选小节先列依赖，S4 输出最终 `candidate-manifest.json`（位于本包目录或明确的公开证据目录），最少字段：

```json
{
  "base_head": "接手时实际提交哈希",
  "source_kind": "reviewed-uncommitted-candidate",
  "product_files": [
    {"path": "agent/runtime/example.py", "sha256": "实际内容哈希", "reason": "依赖或问题ID"}
  ],
  "validation_files": [],
  "excluded_known_changes": [],
  "dependency_versions": {},
  "artifact_sha256": {},
  "verification_evidence": []
}
```

这是字段格式示意，不是可当作完成证据的预填文件。`product_files` 必须覆盖所有实际候选产品文件，而非仅本轮 touched 文件；tests/fixture/构建配置在 validation_files 里有界列明。混合文件需注明包含的原有变更及理由。

不要自动扫描或打包 `.env`、secret、credential、真实状态/log/session、`.git`、`.venv`、根 `tui/`、`.ua/`、Graphify、任何私人目录。公开 `agent/runtime/`、`agent/tui/` 是产品源码，不等于用户私人 runtime。路径逐项审核，复制时拒绝指向范围外的 symlink。

### 3.2 构建与安装顺序

1. 用 `mktemp -d` 创建只属于本次验证的根。包含 `candidate-source`、`build-env`、`dist`、`base-env`、`tui-env`、`neutral`、合成 workspace/state 等子目录；不重用用户真正工作目录。
2. 从已审核清单复制确切源码，核验哈希。默认不复制整个 dirty 仓库。若借助 `git archive` 获取公开基线，仍需对 archive 清单审核并覆盖审核后的必要内容；只导出 HEAD 会再次遗漏本轮未提交修复。
3. 在候选源码上运行完整必要测试。创建隔离构建环境，安装声明构建依赖；从候选源码构建 wheel。可用已有本地 wheel 缓存；记录来源。不能依赖开发环境已装的产品模块。
4. 创建不继承 system-site-packages 的 base/tui venv，各自安装同一 wheel 和相应声明依赖。`pip check` 必须通过。只安装 base 的环境不偷偷含 TUI extra；TUI 环境需要满足 `textual>=8.2,<9`。
5. 在 `neutral` 目录执行安装后的 console entry。清除产品导入相关 `PYTHONPATH`/`PYTHONHOME` 污染，使用 allowlist 子进程环境，隔离 owner preferences/state；不要为此修改全局 `$HOME` 或宿主配置。
6. 验证 `main`、`agent`、`resource_lifecycle` 等关键模块 `__file__` 来自目标 venv；所有 origins 不包含原仓库/candidate-source。用源目录污染的负对照确认同一个检测器确实会判失败。

命令形状（具体候选路径由执行者填入 RESULTS；不要直接运行占位符）：

```text
<build-python> -m pip wheel --no-deps --no-build-isolation --wheel-dir <dist> <candidate-source>
<base-python> -m pip install <exact-wheel>
<tui-python> -m pip install "<exact-wheel>[tui]"
<base-python> -m pip check
<tui-python> -m pip check
<base-env>/bin/first-agent --help
```

### 3.3 用户路径验收

- base 已安装入口，`--provider fake --without-owner-preferences`，显式临时 workspace/state；输入一条无秘密消息再 `/exit`，确认真实 AgentRuntime 首轮返回、状态可重开。`fake` 仅证明离线安装路径，不证明真实模型任务能力。
- base 缺 TUI 时有正确 missing-extra 提示，不伪装成缺 API key。
- tui 已安装入口：`--provider fake --tui --without-owner-preferences` 配合同样独立状态；终端可打开、输入、F4/F3、退出；对修复项另由 Pilot 精确断言。
- 帮助、安装后命令、指南三者一致。源码指南可保留为单独一节，不能混进用户安装路径。
- wheel 内容人工/脚本检查均无私人或 Coding Agent 辅助产物。
- 验证后重新核对候选哈希。若有变化，旧结果只属于旧候选。

如果用户随后批准提交，提交后必须再核对 commit tree 与 manifest，重跑必要的干净导出启动/安装 smoke，才能升级为“已提交交付”；未批准就如实保留这个剩余动作。

## 4. Q3：真实代表性任务与诚实失败

### 4.1 先记录授权，不搜密钥

在 RESULTS 填以下非秘密信息：授权出处/时间、provider/model 精确 ID、允许 endpoint、指定环境变量或密钥来源、允许发送的数据、总费用或调用/token 预算、总时长、重试上限。不要填写 key 内容或任何片段。

若有效授权缺失，只向用户询问缺少的范围。**可建议**本轮总计不超过 30 次 model attempts、30 分钟，每条失败路径最多一次有原因的修正重试；这是建议而不是已批准额度，费用硬上限需用户确认。更低的有效限制优先。不要以小额为由自行开始付费调用。

若产品支持，使用现有 `--transport-audit-ledger` 与 `--max-model-attempts` 做累计控制；`main.py` 当前要求二者一起使用。重开后复用同一任务累计 ledger，不能换 ledger 清零限额。token/金额限制另按现有可用计量落实；模型请求次数不是金额上限。无法保证批准的成本边界就先停止付费部分。

精确模型 ID 用用户当前批准配置，不从不同历史文档任选 `deepseek-flash` 或 `deepseek-v4-flash`。若需确认当前 API 行为，只查官方文档和一次预算内小请求，不随意换 provider/model/key、不扩大输出或上下文上限。

凭据仅在本次子进程 composition root 注入；从用户明确允许的来源读取，禁止 print/export 命令回显、curl 明文 header、写到任何公开文件。外发数据限本次公开或合成 fixture，默认不发真实用户仓库。

### 4.2 正例：沿用 D04 小项目，增加真实交互闭环

优先复用 `tests/acceptance/fixtures/d04_resume_correction/`：有 `retry_app/service.py`、CLI 和现存测试，适合 2–5 文件的实际修复。不要另造大项目或随机挑选新框架。

准备规则：

1. 将审核后的公开 fixture 复制到独立 workspace，保留原夹具不改。
2. 原 SPEC 已包含后续纠正提示；在副本中仅保留初始需求，把“保留 retry_count 别名”的段落留给稍后真实用户输入。记录这个可见性处理，避免把提前读到的需求伪称中途纠正成功。
3. 放置一个与任务无关的 sentinel 文件，记录哈希，最终必须不变。验证器留在 workspace 外；运行前冻结其哈希，不向模型提供参考解。
4. 不运行会自行 `git init/commit` 的 materialize helper 来绕过本包 Git 边界。普通审核复制即可；若确实需要 fixture Git 基线，须先明确这种仅临时 fixture 的授权。

初始任务：实现 transient RuntimeError 的有界重试，公开参数 `max_retries`，CLI 同义；负数拒绝、最多运行 `1 + max_retries` 次，补测试并实际运行。

观察/操作步骤：

1. 从同一已安装候选启动真实 provider。让 First Agent 自己读代码、定位、提案、在审批后修改；执行者不能手工补成参考解。
2. 在合法输入/控制边界输入纠正：保留原 `retry_count` keyword 与 CLI alias；新旧名称同时给出必须拒绝歧义。记录产品的接收与应用事实，单凭界面回显不算已应用。
3. 通过当前支持入口 `/pause` 或 TUI 对应动作在合法安全边界暂停；确认 durable paused，退出并确认 owner 关闭。在同一 fixture、同一 state 与同一累计 ledger 上启动新进程，用合法 `/resume` 继续。
4. 若只能正常 `/exit` 重开而未观察到 PAUSE，则只能报告“退出重开已验证”，不能称暂停恢复通过。不要通过修改 checkpoint 手工制造 paused。
5. 最终模型完成必要实现、真实运行 fixture tests；外部执行者用原有 `scripts/grade_coding_scenario.py D04 <candidate-workspace>` 做业务子项核对。**当前 D04 grader 的 `resume_without_restatement`、`no_effect_replay` 刻意固定为 False，因此 CLI 总 exit code 会为 1，不能要求它总体 PASS。** 如实记录原 exit code 与原字段，仅采用 `latest_correction`、`final_validation` 两项为业务子证明，不修改 grader、不把原报告改成通过。
6. 逐项检查：重试边界、负数、旧 alias、两名冲突、CLI 对齐、实际调用次数、sentinel 未变、产物/测试摘要可理解。

7. 在 RESULTS 分开记录本次过程证明：纠正有精确接收/应用身份；新进程 `/resume` 后不重新发送初始任务或纠正全文仍完成新要求；由本次合成任务的 typed 状态/脱敏 receipt 记录执行前后的稳定 call/idempotency 身份，确认已完成 effect 没有因恢复自动重放。只看到最终文件正确不足以证明无重放；过程证据取不到就明确该项未验证。

为了验证 grader 的业务子项真的检查行为，先对未修 fixture 或一个已知错误的独立副本运行，相关业务谓词必须为 False；正确候选中应为 True。两次总体 exit code 都可能为 1，不能以 exit code 相同认定无效，也不能把必需业务谓词的 False 隐藏成“只有过程缺口”。只在本次 fixture 中制作负对照，不能篡改真实产品证据。

本包 Q3 的最终证据表包含业务子项、实际 fixture tests、精确纠正、真实 PAUSE、fresh-process resume、无 effect 自动重放和资源清理，逐项记录来源。全部有证据才可将**本次新旅程**标为通过；原 D04 静态 grader 报告依然保持其真实结论。这是复用有限子证明，不是降低门槛或新建评测平台。

### 4.3 负例：必要写入被拒绝时必须如实未完成

重新使用一个未修复的独立 D04 副本和独立会话，仍共用本轮总预算计数。任务仍是实现并验证修复，不改成“只分析即可完成”。在必要写入审批时明确拒绝且不授权替代写入路径。

通过条件：目标修改未发生、无未授权替代效果、没有 VERIFIED_DONE/成功验证伪报；用户清楚看到拒绝/阻塞及下一步。不能通过回显“测试通过”或更换任务为只写解释来判成功。负例不要求循环到预算耗尽；观察一次必要权限拒绝后的可信结局即可安全退出。

### 4.4 成功与限制的写法

- 正例业务通过 + 交互证明 + 独立验证 + 清理闭合，才标该场景 PASS。
- HTTP 200、模型有输出、模型说完成、fake 测试通过都不是上述 PASS。
- 401/余额不足/网络错误/超时保留准确非秘密错误码与尝试次数；不得声称必然是 Key 失效，不要自动换 Key 或供应商。
- 达到授权上限立即停受影响操作，保留可恢复状态；对所有未完成项分别写原因。
- 一个场景成功只证明该场景与候选版本，不推广成“所有通用 Agent 能力正常”。

## 5. 最终 gates 与成本纪律

修复阶段按模块 focused；所有目标文件稳定之后串行执行一次项目要求：

```bash
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

记录完整 exit code、通过/失败/skip 数、时长、依赖版本和每个 skip 原因。真实 launchd 等项目原有显式 host gate 未打开的 skip 不是通过，但不要求为了本包安装登录项。新引入的或与本包有关的 skip 不能直接接受。

全量失败先区分本轮导致、确有证据的旧失败与外部阻塞；没有证据不能说 pre-existing。修复后重跑受影响 checks；若最终候选全量仍失败，保留未完成状态，不借旧全绿替代。

最终候选如不同于工作树，全量证据必须来自候选或经 manifest 证明其产品、测试和配置输入完全一致；不能以“主要文件一样”偷换输入身份。

不要并行跑多个全库 pytest 或多组真实浏览器测试。一次 timeout/截断先获得完整进程结果，再决定是否重跑；不看到最后一行就猜通过。

## 6. 最终回复给用户必须包含

1. 13 项逐项结论，具体修复与测试位置；Q1/Q2/Q3 各自证据和限制。
2. 精确候选身份、与当前 HEAD 的关系、有哪些 Git 动作没有发生。
3. focused/full/installed/real 四层结果分别呈现，不合成一个模糊 PASS。
4. 实际新增与复用的能力；明确本轮没有能力扩张。
5. 无秘密的费用/调用统计、剩余阻塞和正确启动方法。
6. 尚未解决的历史 CheckpointSecurityError 如果仍未复现，继续写 NOT_REPRODUCED，而非 FIXED。

用户不应再被要求自己重新拼接资料包；入口和 RESULTS 必须足以接着执行或复核。
