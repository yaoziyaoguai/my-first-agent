# v3 日常修复包执行后审计

日期：2026-09-13。审计对象：`docs/handoffs/2026-09-13-daily-use-repair-v3/` 与当前工作树。
HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`，含既有未提交改动。

## 处理结果（2026-09-13）

- P1-01 / P1-02 已修复：普通项目路径例外不能开放任何 `.env*`、`config.local`，也不能把
  授权文件的上级普通文件误当作可读对象；read/list/search/chunk/write-preview 反例均通过。
- P1-03 已修复：HTTP child 收到 parent 的同一 ledger 路径与同一累计上限；真实 child 进程在
  预先耗尽额度时返回 `LIMIT_REACHED`，没有 HTTP dispatch，也没有追加计数。
- P1-04 已闭合：全新 installed wheel 上的真实 DeepSeek K4 用 5 次 model dispatch 完成
  `local_process → confirm_file → verified done`；旧窗口 8 次 FAIL 原样保留，补证使用单独的显式
  上限 8 ledger，不改写或借用旧额度。
- P2-01 已修复：只有真实 provider profile mismatch 显示换模型指引；损坏 JSON 继续 fail closed，
  并准确报告 `memory store is malformed`，旧 bytes 不变；字段缺失、未知或非字符串的 profile 也先
  判为 malformed，不会伪装成 trust mismatch。
- P2-02 已补证：目录 effect 后 result checkpoint 失败进入 unknown recovery；后续 `Resume` 被拒绝，
  provider/tool 均不重放。目录批次第一步拒绝时，后续目录和文件 effect 均为零。
- P2-03 暂缓且已公开限制：每 workspace 256 个会话；到界拒绝新建但既有历史仍可恢复。当前冻结
  里程碑不引入归档/删除产品面，README 已明确这一长期高频使用限制。

本次没有新增 Runtime、自动授权、后台设施或兼容旁路。修复只收紧既有边界、贯穿已有预算 port、
细分既有错误类型并补组合证据。

最终源码门禁：`git diff --check` PASS，Ruff PASS，pytest
`3502 passed, 3 skipped in 403.02s`。当前源码构建的 non-editable wheel SHA-256 为
`ebe1326fa66c5a30fb4aceecf58f5cbaa7c5a607023d4e584c45e59ddb52c972`，全新 venv installed probe
7/7 PASS。

## 原始结论（修复前）

主要功能已实现，但资料包尚未完整验收。原 RESULTS 明确将 D5 标为 FAIL；本次又在 D1 路径例外中
复现两个边界缺陷，并确认启用 SubAgent 时累计模型预算不覆盖 child。先前“D0–D4 均通过”的总结
应收窄为“原有用例通过，以下新反例与合同缺口仍待处理”。

当前代码可以支持有人监督的部分日常文件任务。下一步应收紧路径例外、闭合请求预算组合，再补齐
精确命令的真实交付证据。此次检查没有提供重写 Runtime、添加更多后台设施或按文件行数拆分的理由。

## 优先处理

### P1-01：开放普通配置目录也会开放合同要求继续拒绝的文件名

位置：`agent/tools/path_safety.py:81`、`:853`。

合成复现：创建 `config/`，其中所有文件仅含同一段 synthetic marker；使用
`build_file_tool_runtime(workspace, project_paths=("config",))` 经真实 prepare/invoke 读取。

| 合成路径 | 当前结果 |
|---|---|
| `config/.env` | 拒绝 |
| `config/.env.local` | 拒绝 |
| `config/.envrc` | 执行读取并返回 marker |
| `config/.env-production` | 执行读取并返回 marker |
| `config/config.local` | 执行读取并返回 marker |
| `config/app.yaml` | 正常读取 |

原因：两处判定只覆盖 `.env` 的精确名字、`.env.` 前缀与 `config.local.` 前缀，未落实 D1
合同写出的 `.env*` 与 `config.local`。这不是已经发生真实秘密外泄的证据；但一旦普通目录获准，
这些内容可以进入工具结果，文件边界没有按声明阻止读取。

最小修复：让路径参数校验和实际文件边界共享同一套约定的敏感名称判断；保留公开配置正例。
用 read/list/search/chunk 和写入预览反例证明敏感 fixture 不可见，不通过增加提示词补偿权限判断。

### P1-02：只授权一个子路径，也能读取它的同名上级普通文件

位置：`agent/tools/path_safety.py:872`。

合成复现：workspace 中 `config` 是普通文件，含 synthetic marker；只设置
`project_paths=("config/public.yaml",)`。随后 `read_file(path="config")` 实际成功返回 marker。

原因：`_is_project_path_visible` 同时允许“授权前缀之下”和“授权路径的祖先”，而祖先通行规则
也被用于普通文件读取。允许穿过上级目录不等于允许读取上级同名文件。

最小修复：将目录遍历需要的祖先可达性与目标文件授权区分开。具体文件授权应只放行该文件；
上级仅在安全真实目录的遍历/必要目录准备语义下可达。补充 ancestor 为普通文件、目录、symlink
及显示后类型变化的反例，保留准确文件授权下的 list/search 能力。

### P1-03：启用 SubAgent 时，“累计模型请求上限”不包含子请求

位置：`main.py:1430`、`agent/subagent/contracts.py:60`、`agent/subagent/runner.py:128`。

父 provider 通过 `TransportAttemptLedger.record` 发送前占位；child spec 不携带该预算信息，
`build_child_provider` 重建 provider 时也没有传入 attempt recorder。CLI 未拒绝
`--subagent` 与 `--max-model-attempts` 的组合。

合成验证：同一 ledger 上限 1，预先占满；父 provider 被阻止，MockTransport 请求数为 0。
然后调用当前 child provider 构造路径（只注入 MockTransport、合成 key），child 仍发出 1 次
mock HTTP 请求，而 ledger 仍只有 1 行。这里验证的是实际父/子 provider seam，未调用真实服务、
未把它冒充完整子进程 E3。

影响条件：启用了 HTTP SubAgent；本轮 K1–K5 未开启 child，因此不推翻原 24 次计数。
资料包曾明确把 child 补证留待以后，但产品公开参数组合缺少保护，不能因此声称其预算覆盖完整任务。

最小修复：为 child 传递同一非秘密预算配置，在子进程发送前复用同一个 ledger 锁与计数；
若本次不实现预算贯穿，至少在零派生请求前明确拒绝这一不支持的组合。不能为 child 新建计数器、
事后补账或改大父预算。验收覆盖父子争抢最后额度、child 重启、预算损坏零 dispatch。

### P1-04：精确命令的真实模型验收仍未闭合

依据：`docs/handoffs/2026-09-13-daily-use-repair-v3/RESULTS.md:30`、`:63`。

K1/K2/K3/K5 已记录真实通过。K4 的 venv symlink 误判已修复，安装包直接执行进程也已通过，
但“自然输入 → 模型选准确命令 → 审批 → 运行 → confirm_file → 最终交付”没有修复后的真实 PASS。
这是证据缺口，不能断言当前实现仍必然失败。

最小补证：保留旧 FAIL，明确登记修复后的有限复验窗口和候选身份；成功一次并核对真实产物即可。
上轮每条 8 次的冻结额度已经用完，本轮是审计，未改变预算或追加付费请求。下一次执行需要明确
记录本次补证额度，不能偷偷重置旧 ledger。其余已成功案例仅在相关源代码改变时定向复验。

## 次优先级

### P2-01：偏好文件损坏被误报为“更换模型导致绑定不匹配”

位置：`main.py:1363`；合同：`WORK-PACKAGES.md` 的 D4。

合成复现：以 fake provider 创建合法 owner preferences，在同一个 provider 下把合成文件写成
损坏 JSON `{`，然后再次启动。exit 2，旧 bytes 保持；界面却声称绑定不同 provider，并建议原模型、
跳过偏好或换 state root。外层把所有 `MemoryStoreError` 都改写成同一种错误。

最小修复：区分 trust mismatch 与损坏/权限/格式错误；只在真实 mismatch 时显示模型切换指引。
文件损坏继续拒绝启动并给准确诊断，不能自动重建、删除或迁移偏好。跳过参数仍由操作者明确选择。

### P2-02：目录创建的自动化验收尚未覆盖合同中的中断/恢复路径

当前 `make_directory` 的新增测试主要在 `tests/tools/test_file_tools.py:253` 至对应嵌套写入
用例中直接调用 ToolRuntime。它们证明审批、父 identity 漂移和目录/文件实际 bytes；不等于
同一 durable Goal 经过 AgentRuntime 的完整拒绝与恢复验证。

补两类窄测试即可：目录创建后 result checkpoint 失败/重启必须进入未知结果处理且不自动重放；
两层目录的单 Goal 旅程逐步拒绝均零后续 effect，最后准确文件回读才允许完成。
现有通用 checkpoint 测试有价值，本项是新工具接入的组合证据缺口，不是已经观察到重复创建。

### P2-03：会话容量到界后仍缺用户可操作的收拾入口

位置：`agent/continuity/sessions.py:34`、`:278`，`main.py:1198`。

分页解决 16 条显示上限，workspace 总容量仍为 256。合成探针用同一实现将容量缩小到 2，
验证装满后新建返回 `history_capacity_exceeded`，现有会话仍可选择；没有数据丢失。
当前 CLI 没有普通用户的会话归档/容量管理命令。连续使用前应增加明确容量说明与可恢复的管理方式；
不必为此立即设计数据库或自动删除历史。

## 产品体验与可延后范围

- 外发确认：已记录的 K1/K2 各出现 3 次 disclosure，日常短任务的交互成本偏高。应先量化每次
  确认的原因，改善说明；任何作用域级授权调整需要单独明确边界，不能静默自动同意。
- 等待体验：`agent/provider/openai_http.py:75` 的 OpenAI-compatible 路径仍为非流式，
  DeepSeek 长请求缺少文本增量。可以先完善可见进度与取消体验，再评估流式适配，保留唯一 Runtime。
- Memory/Skill/MCP/SubAgent 的当前候选代表性真实任务尚未补证；不是据此断言能力没有实现。
  按实际使用需要各补一个任务，child 先解决 P1-03。
- Browser、Scheduler 实机验收、跨平台、更多并行 Agent 与新的架构拆分可以继续延后；
  它们不是先把文件与命令任务稳定用起来的前提。

## 原始审计验证与范围（修复前）

本次只审计并新增本报告，未修改产品源码、提交或推送；没有读真实 key/会话/Memory/Skill/MCP
私有目录，也没有访问根未跟踪 `tui/`。Graphify 已有图只给出历史 capability 关系，本轮新缺陷
以当前源码和合成复现为准，未重建索引。

- 合成探针：`/private/tmp/first-agent-v3-review.fGQpgd/probe.py`，最终 exit 0，5 组观察完成。
  前两次探针因复用 tool-call ID、缩小容量未同步候选上限而退出；修正审计探针后完整重跑成功，
  不把这两次脚手架错误归为产品缺陷。临时 fixture 已由探针清理。
- 相关现有测试：`81 passed in 2.41s`，exit 0。
- `git diff --check`、`.venv/bin/ruff check .`：PASS。
- 未重复全量、未重建 wheel、未做真实 provider/MCP/browser 调用。上轮
  `3492 passed, 3 skipped` 仅引用为既有交付事实。

本轮相关测试命令：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --color=no \
  tests/provider/test_transport_audit.py tests/kernel/test_runtime_limits.py \
  tests/tools/test_file_tools.py tests/cli/test_entrypoint.py tests/process/test_admission.py
```

建议执行顺序：P1-01/P1-02 共用一次路径修复 → P1-03 预算组合 → P2-01 与必要中断测试 →
最终候选 K4 补证。达到这些有限目标后即可交付个人监督使用版本；体验与扩展验证按真实需求推进。
