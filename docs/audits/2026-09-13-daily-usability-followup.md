# 日常可用性复审

## 结论与证据范围

当前版本可以完成部分有人监督的聊天、读取已有文件和审批写入任务，但还不能据此认定一般日常工作能够稳定闭合。上轮 R1–R6 的离线合同通过，不等于真实任务完成率已经达标。

本次为评估，没有修改产品代码、重新调用真实模型、读取用户凭据或重新运行全量。使用已有 Graphify 索引定位后核对当前源码；当前 HEAD 为 `838cb2b66fbba674311d4d86fc7c4f4322fd8612`，工作树包含既有未提交改动。上轮全量 `3449 passed, 3 skipped` 是回归基线，不是本次新增测试结论。

本轮执行合成离线探针 `/private/tmp/first-agent-usability-audit.LIYwSY/probe.py`，exit 0；另外三个既有行为测试 `3 passed in 0.55s`。探针只创建并清除自己的临时 fixture，没有使用用户会话或真实服务。

## 优先闭合的问题

### P1-01：普通任务的真实完成率仍未闭合

证据：`docs/handoffs/2026-09-13-qa-repair-v2/RESULTS.md` 的 G2/G5。

- G2 要求只读 TODO，却申请另写一个用户没有要求的文件；拒绝阻止了写入。
- G5 在给出精确解释器路径后仍反复探索，58 次模型请求后没有执行目标进程。
- 上轮随后增加了 system policy 文案与每个 action 最多 8 次模型调用，但没有对最终候选重新跑这两个真实案例。

因此当前结论应为“止损机制已验证，任务完成质量待复验”。不能把尚未复验写成最终代码仍必然失败，也不能把提示词存在断言当成模型遵循证据。

最近原因与取舍：`main.py:203` 的上限只约束一次 Runtime invocation；`agent/runtime/loop.py:758` 每次进入 `_drive` 将本地计数置零。它不等于整个 Goal 的总成本预算，且正常进展的任务也会在第 8 次请求后暂停。`tests/reference/test_016_first_agent_1_0.py:383` 已证明暂停/恢复，但不证明真实模型效率。

最小完成标准：对最终候选分别验证只读 TODO 不提出写入、精确命令执行并返回真实结果；记录请求数、审批次数、耗时与产物。任何追加真实验证应先有执行层强制的本轮总预算，避免再次突破操作者纸面预算。

### P1-02：常见项目文件被默认当作私有路径屏蔽

代码：`agent/tools/file_ops.py:46`、`main.py:1190`。

默认私有根包含 `config`、`skills`、`memory`、`workspace`、`pytest.ini`、`CLAUDE.md` 等名称。无论这些文件实际是否包含秘密，文件工具都会隐藏/拒绝其中路径。读取普通项目配置、测试入口或同名业务模块时会缺少必要信息。

本轮合成复现：`config/app.yaml` 和 `pytest.ini` 都只有 `public synthetic fixture` 文本，读取仍被拒绝；同样内容的 `normal.txt` 可以准备执行。现有 `test_default_private_roots_are_hidden_and_unreadable` 将这种行为固定为当前策略。

最小修复方向：区别产品真实私有存储位置与用户 workspace 中的同名普通项目路径，设计明确的授权入口。保留真实敏感文件、no-follow 和外发保护；不能简单删除整个拒绝集合。

### P1-03：无 Goal 会话超过 16 个后，部分会话没有恢复入口

代码：`agent/continuity/sessions.py:33`、`:255`、`:334`；`main.py:1120`。

启动只展示前 16 个 active candidates；无 Goal conversation 一直算 active。界面会告诉用户只显示一部分，但没有下一页、搜索或按 ID 选择的入口；选择函数也只允许已经展示的 candidates。

本轮使用确定性 UUID 创建 17 个合法、相同 workspace binding 的无 Goal 会话：保存 17、展示 16、第 17 个不在列表；直接选择被拒绝，CLI 输入 17 返回 exit 2。真实随机 UUID 下不必然是最新会话被隐藏，但必然有一部分无法经当前选择界面到达。数据仍在磁盘，不能称为数据丢失。

最小完成标准：保持有界展示和 fresh-load identity 校验，同时让第 17 个及后续会话可通过分页或明确 ID 到达。另一个后续边界是 256 条历史容量，目前没有普通用户可操作的归档/容量管理流程。

### P1-04：仅更换模型名也会被偏好库绑定挡住启动

代码：`main.py:1249`；`agent/composition.py:533`；`agent/runtime/contracts.py:1153`。

全局 owner preference store 在启动时自动加载，其 trust digest 使用完整 ProviderDescriptor，包含模型名。模型名变化后，加载偏好库失败会让整个启动退出；上轮只改善了错误提示，建议换 state root。

本轮离线复现：同一个合成 HTTPS endpoint，先用 model-a 建立空偏好库，再改 model-b；没有保存任何个人偏好，也没有发网络请求，仍然抛出 MemoryStoreError。替换同一模型的 API key 不属于这个问题，因为 credential 不在 descriptor 中。

影响：用户无法在原状态目录里平滑切换同一服务的模型；换 state root 又使原会话/历史不在默认入口可见。

最小完成标准：提供显式的 trust 变更确认或暂不载入旧偏好的受控启动路径，保留已有会话，确保确认前不会向新 destination 外发旧数据。不能静默重绑。

### P2-01：新建嵌套文件只给提示，缺少直接完成路径

代码：`agent/tools/file_ops.py:99`、`:220`；`tests/tools/test_file_tools.py:192`。

请求创建 `reports/daily.md`，若 reports 不存在，write_file 返回 `workspace_parent_missing`，父目录仍不存在。上轮修复了错误分类，没有提供文件写入路径内的受治理目录创建。

本轮直接复现并通过现有测试确认。不能扩大表述为整个 Agent 绝对不能创建目录：另一条已批准的命令执行路径可能做到；问题是普通“把报告保存到新目录”的文件任务仍需额外人工准备或切换执行能力。

最小完成标准：目录创建进入准确的 effect preview 和 no-follow 验证，普通嵌套保存可以经一次清楚的用户决策完成；不自动创建未批准路径。

## 影响体验，但不应先扩成新架构的问题

- 外发确认负担：历史实测中一次简单读文件出现多次 disclosure，极小写入出现多次 disclosure 加一次写入审批。它们涉及数据类别变化，现有证据不能称为同 digest 重复审批。需要以真实用户任务的总确认次数和解释清晰度评估。
- DeepSeek 当前走 `agent/provider/openai_http.py:75` 的非流式 adapter，只有 Anthropic-compatible 路径有文本增量。长请求期间可见反馈有限；8 次请求上限不等于单次请求的总等待时限。
- 缺凭据时 `--status` 可以看状态，但取消/处理未知结果仍需进入正常启动路径。这是上轮明确保留的功能边界。
- 已配置 Skill/MCP/Memory/SubAgent 不等于最终候选真实任务成功；G6–G10 未跑，旧失败不能直接算作最终代码仍失败，离线修复也不能替代复验。
- Scheduler 当前 installed entrypoint 确实不可运行；若日常使用不要求定时任务，可继续 deferred。它不是修好文件和命令任务的前提。
- 最终 wheel 尚只验证了 system-site-packages 环境；另一台机器的纯净依赖安装仍缺证据。GLM 工具协议兼容也仍缺真实复验证据。

## 本轮检查与建议顺序

执行的离线检查：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python /private/tmp/first-agent-usability-audit.LIYwSY/probe.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --color=no \
  tests/tools/test_file_tools.py::test_write_to_missing_parent_explains_the_safe_next_step \
  tests/tools/test_file_tools.py::test_default_private_roots_are_hidden_and_unreadable \
  tests/reference/test_016_first_agent_1_0.py::test_everyday_path_hard_stops_after_8_model_calls_and_can_resume
```

建议先处理普通文件的误拦与新目录保存，再闭合两个真实日常任务；会话分页和切换模型是接下来最值得修的使用阻塞。随后补齐已配置扩展能力的代表性任务。暂不把新增 Scheduler、并发 Agent、更多架构拆分作为“达到能正常使用”的前提。
