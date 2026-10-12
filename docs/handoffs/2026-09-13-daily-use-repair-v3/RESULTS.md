# 执行与交付记录

## 当前状态：D0–D5 已完成；K4 的历史失败已在独立补证窗口真实闭合

本文件记录 2026-09-13 的实际执行证据。原 K4 没有在耗尽本行冻结预算后借用其他案例额度；该
FAIL 记录继续保留。后续审计明确建立一个独立、上限 8 次的补证 ledger，新候选以 5 次 dispatch
完成同一自然输入旅程，因此当前 D5 可以写为 PASS，而不是覆盖历史失败。

- 准备日期：2026-09-13。
- 起始 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`；main ahead 7，已有大量未提交改动。
- 本轮实现：累计模型请求预算、显式普通项目路径、单层目录工具、会话分页、owner preference
  显式跳过，以及 dogfood 发现的多跳 executable symlink 误判修复。
- 真实 provider 请求共 24 次；只由 owner-only launcher 从已授权文件注入，未输出或写入 key。
- 本包 probe_baseline.py：exit 0，U1–U4 合成复现完成；报告的 product_acceptance 为 not_evaluated。
- 观察结果：config/app.yaml 与 pytest.ini 拒读，normal.txt 可准备读取；reports 父目录未创建；stored=17/visible=16，第 17 项选择 exit 2；同 endpoint 换模型拒绝，旧偏好 bytes 不变。
- 指纹：BASELINE.sha256 中 53 个明确列出的源码/测试/参考文档全部匹配，exit 0。
- 资料包 Ruff：PASS，exit 0；首次发现探针 import 排序问题，已修正后重测通过。
- 8 个资料包文件的本地链接、代码围栏、whitespace 和明文 key 格式检查：PASS，6 个本地链接可解析，未发现问题；git diff --check：PASS。
- 没有新增 Agent loop、权限旁路、登录项、daemon、schema migration 或自动 fallback。
- 未 commit、push、tag、stash、reset，也未读取根未跟踪 `tui/`。

## 修复合同

| 项目 | 状态 | Red 证据 | 最小改动/文件 | Green 与反例 | 限制 |
|---|---|---|---|---|---|
| D0 累计预算 | PASS | 第三次请求、重启、并发抢最后额度、损坏 ledger；child 预耗尽 | 复用 transport recorder，发送前原子占位；Runtime typed pause；HTTP child 贯穿同一 ledger/上限 | 失败不退款；web 不计数；并发只有一个成功；损坏/权限/symlink/child 耗尽均零 dispatch | 原窗口总上限 40，实际 24；补证另记 5/8 |
| D1 显式项目路径 | PASS | `config/`、`pytest.ini` 默认拒绝；`.env*`、`config.local` 与 ancestor-file 反例 | `--project-path` 只传入既有 boundary；目录遍历祖先与可读取目标分权 | 具体文件/list/search/chunk 可见；敏感名在 read/list/search/chunk/write-preview 均拒绝；相邻项、symlink、hardlink、实际私有输入仍拒绝 | 只在本次启动生效 |
| D2 目录工具 | PASS | write 缺父目录返回 `workspace_parent_missing` | 单层 `make_directory` governed tool | 目录/文件分别审批；0700/0600；stale parent、缺上级和 symlink 拒绝 | 不做自动 `mkdir -p` |
| D3 会话分页 | PASS | 第 17 个候选不可见/不可选 | startup inventory 的无 schema `n` / `p` 投影 | 17/33 项、越界页、前后翻页、目标 identity、checkpoint bytes 不变 | 历史容量仍 256 |
| D4 跳过 owner preferences | PASS | 同 endpoint 的 model-a→model-b trust mismatch | composition root 的 `--without-owner-preferences` 省略 store/source/tools | 无参数仍拒绝；skip 零偏好 I/O，旧 bytes 不变 | workspace Memory 不受影响 |
| D5 日常真实复验 | PASS | 原 K4 三次正确 `local_process` 均因 venv 两跳 symlink 被误判成环而 binding_failure | 环检测由 final `realpath` 改为当前链接节点检测 | K1/K2/K3/K5 原窗口真实 PASS；K4 新 installed 候选真实 5/8 PASS；真实环仍拒绝 | 原 FAIL 和新补证分账保留 |

状态只用 NOT STARTED / IN PROGRESS / PASS / FAIL / BLOCKED / NOT RUN / DEFERRED。外部阻塞写清原因和解除条件，不把 BLOCKED 改成 PASS。

## 原始候选与当时门禁

- 工作树身份：起始 HEAD 未变；本包列出的相关源码/测试因本轮实现发生预期漂移，未覆盖用户原有 dirty 改动。
- 最终改动：见上表；另有 `agent/process/admission.py` 的 K4 最近原因修复及对应回归。
- wheel：`/private/tmp/first-agent-v3-build.MtvNPc/wheels/first_agent-1.0.0-py3-none-any.whl`；
  SHA-256 `b0c76f32893fdcac9ee060ef2ed1803e55774fab4628b74e4e1559d9407afdb0`。
- 构建：`pip wheel . --no-deps --no-build-isolation`；全新 venv 从 PyPI 安装 `httpx 0.28.1`
  及其依赖。非 editable、非 system-site-packages。
- 环境：macOS 15.5（24F74），Python 3.12.2。
- 仓库外核验：`agent.__file__` 与 `main.__file__` 都来自候选 venv 的 `site-packages`。
- installed probe：7 个 case 全 PASS；额外证明多跳 venv Python 经真实 `local_process`
  approval/receipt 执行并产生 exact 输出。
- focused：294 项交叉测试 PASS；分页/launcher 新边界 5 项 PASS；process/symlink 81 项 PASS。
- 最终 git diff --check：PASS，exit 0。
- 最终 Ruff：PASS，exit 0。
- 最终 pytest -q -rx：PASS，`3492 passed, 3 skipped in 402.91s`，exit 0。
- 最终 diff review：PASS；没有新增第二套 loop，项目路径只扩展文件边界，目录与进程副作用仍经过
  policy/approval、执行 checkpoint 与 result checkpoint，owner preference skip 不触及 workspace Memory。

## 真实窗口：先冻结预算，再启动

- 新 ledger：`/private/tmp/first-agent-v3-dogfood-20260913/audit/attempts.jsonl`（只含调用计数事实）。
- 本轮累计上限：40 model attempts，包含失败及修复后的复测。
- budget-aware launcher 离线验证：PASS；合成 key 不泄漏、无关环境不继承、权限不安全 key fail closed。
- 所有真实调用串行；执行顺序 K1 → K4 → K2 → K3 → K5。

| 案例 | 首次 B | 冻结 ceiling=min(B+8,40) | 本行累计 attempts | 状态 | 产物/拒绝/交付证据 | exit/清理 |
|---|---|---|---|---|---|---|
| K1 只读 TODO | 0 | 8 | 3 | PASS | 返回 `add CSV export`；只读来源；workspace 清单和目标 hash 不变 | 0；无残留 |
| K4 精确命令 | 3 | 11 | 8 | FAIL | 3 次 exact process 均在审批前 binding_failure；未生成文件；修复后 installed 离线执行 exact | 0；无残留；未借额度 |
| K2 普通配置读取 | 11 | 19 | 3 | PASS | 读取 `csv` / `tests`；零写入；installed 反例证明 `.env` 仍拒绝 | 0；无残留 |
| K3 新目录报告 | 14 | 22 | 5 | PASS | `make_directory` y、`write_file` y；0700/0600；26 bytes exact，SHA-256 `90986d…a2a1a` | 0；无残留 |
| K5 stale 编辑 | 19 | 27 | 5 | PASS | 首次 y 后旧写入未执行并重预览；第二次 y 只改标点且保留合成并发注释 | 0；无残留 |

每行另记候选 wheel/fixture hash、用户自然输入、disclosure 次数、effect approval 次数及 y/n、工具请求/实际执行、parent final、实际 bytes/hash、主动耗时/人工等待时间。不要粘贴真实用户数据、完整 raw trace、认证 header 或 key。

K1、K2 各出现 3 次按 data-class 变化触发的 disclosure；这是正确的安全行为，但对低延迟只读任务
显得偏重。当前没有证据支持绕过或合并 disclosure，因此本轮只记录产品体验成本，不改安全合同。

### K4 独立审计补证

- 候选根：`/private/tmp/first-agent-v3-remediation-20260913.RvYuKP`；全新 non-editable wheel
  SHA-256 `f1614ed2a2b3f3a34a41f5ee569584f02c27ee7ec7bd53439da352def92daa7d`。
- installed probe：7/7 PASS，模块均来自候选 venv `site-packages`；其中多跳 venv 进程离线
  installed case PASS。
- 新 ledger：`audit/k4-attempts.jsonl`，owner-only，冻结上限 8，实际 5 次 model dispatch。
- 自然输入保持 K4 原合同；模型请求的 `local_process` 预览含准确候选 Python、唯一参数
  `generate_report.py`、`cwd="."`，批准后真实 exit 0。
- 随后 `confirm_file` 预览并回读 exact `bounded process output\n`；产物 SHA-256
  `9b5413237fe1f2c8843547d8498440d7aa2de2adbcd7244765a438075ad41e70`，Runtime 最终为
  `Goal completion verified`，进程退出后无候选路径残留进程。
- 该窗口不读取旧 ledger、不修改旧 8 次 FAIL 数字，也没有复测已通过的 K1/K2/K3/K5。

### 审计修复后的最终交付候选

- K4 补证后只新增了与进程路径无关的 Memory profile 结构校验及文档；没有修改 Runtime、provider、
  process admission/tool 或 K4 fixture。按“相关源码改变才复测”的冻结合同，不再消耗剩余 3 次
  DeepSeek 请求。
- 当前源码重新构建 non-editable wheel：
  `/private/tmp/first-agent-v3-remediation-20260913.RvYuKP/wheels-final/first_agent-1.0.0-py3-none-any.whl`，
  SHA-256 `ebe1326fa66c5a30fb4aceecf58f5cbaa7c5a607023d4e584c45e59ddb52c972`。
- 全新 `candidate-final` venv 的 installed probe 7/7 PASS；`agent` 与 `main` 均从该 venv 的
  `site-packages` 加载。没有 editable install 或 `PYTHONPATH` 冒充。
- 最终源码门禁：`git diff --check` PASS；Ruff PASS；pytest
  `3502 passed, 3 skipped in 403.02s`，exit 0。

失败记录：第一次现象 → 脱敏原因证据 → 离线 Red → 最小修复 → focused Green → 剩余原预算下复验。相同故障没有新证据时不再发送请求。耗尽当前 journey 预算便停止该行，不能在后续 journey 借额度重跑。

## 可选证据与明确未做

| 范围 | 状态 | 说明 |
|---|---|---|
| Memory / Skill / MCP | NOT RUN | 本轮只闭合审计必需项；不因 K4 成功自动扩展真实付费范围 |
| 单 SubAgent | NOT RUN | 离线真实 child 进程已证明共享额度；未再做付费 child 产品任务 |
| Browser 真实任务 | DEFERRED | 不安装、不登录、不测试真实网站 |
| Scheduler host | DEFERRED | 不新增登录项/daemon，不执行 019 实机测试 |
| 跨平台与 promotion | DEFERRED | 不将日常小修升级为平台重构或能力晋级 |

## 给用户的最终结论

日常只读、显式项目配置读取、缺目录写文件和并发修改保护已由当前候选真实验证。精确本机命令在
旧候选真实暴露过 venv symlink 误判；修复后的全新安装候选已在独立有界窗口完成同一自然输入、
准确命令、审批、真实进程、产物确认和最终交付。D0–D5 因此闭合；会话归档入口与可选能力的新版
代表性真实任务仍是明确延后项，不影响当前个人监督下的普通日常任务结论。
