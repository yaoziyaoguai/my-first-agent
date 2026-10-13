# 实施合同与定向验收

本文件按执行顺序排列。每项先读现有文件再写 Red。以下新参数/工具名是要实现的接口，不是假称当前已存在。

## D0：在请求发出前强制预算

目的：解决上轮纸面 50 次预算被突破到 78 次的问题。保留 `EVERYDAY_INVOCATION_LIMITS.max_model_calls=8`，新增整个验证窗口可持续计数的上限。

最小接口：`first-agent --transport-audit-ledger PATH --max-model-attempts N`。N 是该 ledger 从创建起累计允许的 model 请求数量，不是每次启动额外赠送的额度；提供 N 必须同时提供 ledger，N 为正整数且本包执行不得超过 40。

首选修改：`agent/transport_audit.py`、`main.py`、`agent/provider/protocol.py`、必要的 `agent/runtime/ports.py` / `agent/runtime/loop.py`、`tests/provider/test_transport_audit.py`、CLI/provider/limits 相关测试。直接复用两个 adapter 已有的发送前 attempt_recorder，禁止复制 provider.generate 或另写任务 loop。

行为：

1. 为 TransportAttemptLedger 增加可选 model 上限。在同一个排他锁内，有界加载并严格校验 ledger、计数、检查上限、持久化本次占位，再允许 HTTP dispatch。跨进程必须共享这个锁。已有秘密-free record schema 尽量不变。
2. 只统计 model；本轮真实任务不开 Web/child。HTTP 失败或占位后崩溃不退额度，防止重启后重复消费。不能发送成功才记账。
3. 到界用明确的 typed budget error 返回，经现有 Runtime 暂停/非成功结果交还用户；不可当成 provider wire 错误让模型再尝试，不可 traceback，不可报 task completed。
4. 同一 ledger 的 `/ack`、`/approve`、`/resume`、进程重启不会清空计数。普通回答和 compaction 的实际请求都走同一 recorder。
5. 文件、父目录、锁文件保持 owner-only/no-follow、有界读取；损坏、权限不符、锁失败时零 dispatch。ledger 不包含 key、payload、conversation 原文或 response body。
6. 没配置 N 时保留现有行为。max_model_calls=8 仍有独立意义，不调高它掩盖模型效率问题。

Red/Green：上限 2 时两个发出、第三个 transport spy 次数不增加；多个进程抢最后一个名额最多一人成功；重启不重置；发送失败不退款；web 不消耗 model 额度；损坏/超容量/symlink/权限错误零请求；Runtime 显示预算暂停可取消；compaction 不能绕过。

执行实测前完善本包配套 launcher：复用前一包的安全 key 注入逻辑，把冻结的 N 传给安装包。若修改旧 launcher，应保持旧调用者兼容；更适合在本包新增只做注入/argv 的小 wrapper。它不能 monkeypatch 产品、代替模型选工具或自动批准。D0 未通过时本包所有真实用例为 NOT RUN。

## D1：操作者可以开放普通项目路径

接口：重复的 `--project-path RELATIVE_PATH`。只在本次启动生效，不写用户配置。例：`--project-path config --project-path pytest.ini`。

固定边界：

- 只允许为这些现有普通保留根提供例外：`config`、`workspace`、`memory`、`skills`、`pytest.ini`、`CLAUDE.md`。其他 private roots 仍保留；不用用户目录名猜真实秘密。
- 例外可指定一个具体文件或目录前缀；按路径组件匹配，`config/app.yaml` 不能开放 config/other.yaml，`config` 不能匹配 config-backup。拒绝空值、`.`、绝对路径、`..`、通配符和控制字符。
- 它只越过 DEFAULT_PRIVATE_ROOTS 的该普通名字检查；不能越过 `_SENSITIVE_EXACT/_SENSITIVE_COMPONENTS`、`.env*`、key 后缀、config.local、protected_paths、symlink、硬链接和 I/O 限额。`--project-path config` 也不能读 config/.env。
- 本进程显式配置的实际私有位置（state root、Memory store/create、MCP catalog/safety state、Skill 私有根等）必须独立保留为 protected paths；按启动参数绑定位置，不扫描内容猜秘密。若这些位置与例外重叠，私有位置优先拒绝。例如业务 memory/ 可按用户选择开放，但其中已配置为实际 Memory store 的文件仍拒读；覆盖这一冲突的合成测试不可省略。
- 新例外只接入 workspace 文件工具及其搜索/分段读取的一致 boundary。不要改 sandbox、local_process、Memory、Skill loader 的权限，不通过命令工具绕过拒读。
- 开放读取后，内容仍为 untrusted workspace data；写/改仍经精确审批。CLAUDE.md 的文本不会自动成为系统指令。
- 启动显示有界例外摘要；未开放而遇普通保留路径时给可执行的重启提示。模型参数、文件或 Skill 的 allowed-tools 不能修改这一例外。

首选文件：`main.py`、`agent/composition.py`、`agent/tools/file_ops.py`、`agent/tools/path_safety.py`、对应 CLI/file/search tests。直接在现有 boundary 添加小的显式输入，不建立另一套 policy engine。

Red/Green：默认 config/pytest.ini 仍拒绝；显式开放后的 list/search/read/chunk 可用；准确写预览 y 可写、n 不写；prefix 邻接/大小写/绝对路径/路径逃逸/symlink/.env/受保护状态/hardlink 反例；实际私有位置与例外重叠时仍零读取；重启不带 flag 重新拒绝；敏感 fixture 不能出现在可见错误或来源结果里。

## D2：受治理地创建缺失父目录

本包选择小工具 `make_directory`，参数仅 `path`：一次创建一个目录，父目录必须存在。不增加 recursive/force/chmod/shell 参数。多级目录按现有同一 Runtime 逐层调用，目录审批和文件审批分别展示。这样部分目录成功的事实可以使用现有逐工具 durable result 记录。

首选文件：`agent/tools/file_ops.py`、`agent/tools/path_safety.py`；必要时新增一个小的 `agent/tools/directory.py`；`main.py`/工具说明的最小路由提示；file/path/kernel/reference tests。复用 RegisteredTool、ToolSpec、DefaultToolPolicy 和 WorkspaceBoundary。

行为与证据：

1. 只在 durable Goal 的 effectful 工具阶段可见，answer-only 不暴露。目录是请求产物的辅助准备，不得凭目录创建就把文件 Goal 标为完成。
2. prepare 只检查和形成 preview，零 mkdir；绑定 workspace/现有父目录 identity、准确 path、目标缺失状态。preview 明确“创建目录”，不伪称写入最终报告。
3. approval 拒绝后零创建、零后续自动模型调用，沿用已修复的拒绝交还控制语义。
4. invoke 经既有 binding 重验，用 descriptor-relative `mkdir` 和 no-follow；固定最小权限。批准后父目录被替换、目标变成文件/symlink/已出现其他对象，都使旧 approval 作废，不直接继续。
5. 已存在的安全真实目录可以形成明确的“已存在，无创建”结果；只有身份验证成立才可继续后续 write，不能把异常吞掉当存在。不要生成虚假的 created receipt。
6. 成功后记录结果再允许后续调用；创建后落盘/结果 checkpoint 失败按现有 unknown effect 恢复，不能自动重建或递归删除“回滚”。仅清理本次确知身份的临时资源。
7. ordinary write_file 继续保留缺父目录拒绝。给模型的反馈应指向先用 make_directory 建立缺失层级，再 write_file；不用 local_process 的宽权限做 mkdir。

Red/Green：reports/daily.md（一个缺失父级）和 reports/2026/daily.md（两个父级）的单 Goal 完整离线旅程；目录及文件各自 exact approval；每一步拒绝均无后续 effect；stale parent、symlink、protected path、权限失败、mkdir 后异常/重启；最终准确文件 bytes/read-back/完成结果；无关路径不变。

不要把旧 `test_write_to_missing_parent_explains_the_safe_next_step` 删掉改成 write_file 自动 mkdir。它仍然是底层合同；新增测试证明 Runtime 能经新工具完成上层任务。

## D3：会话列表有界分页

首选文件：`agent/continuity/sessions.py`、`main.py`、`tests/continuity/test_state_root.py`、`test_restart_selection.py`、`tests/cli/test_entrypoint.py`。

固定界面：每页最多 16，输入 `n` 下一页、`p` 上一页、页内编号选择；显示页码、总候选数。16 条以内保持现有数字选择。没有下一页时给提示且仍可选择，不 exit。

- 复用一次 startup discovery 的有界 candidate inventory（总容量仍 256）和稳定顺序；不要靠 mtime 猜最近会话，不增加新 schema。
- continuity 层提供窄的“取这一页候选”投影；CLI 不自己扫描或加载任意路径。当前页实际选择仍复用 `select_workspace_candidate` 的 fresh-load 校验。
- 换页不推进 Runtime、不取 provider、不改 checkpoint。显示后目标 revision/action_seq/Goal/workspace binding 漂移必须拒绝，不能刷新后把同一数字悄悄指向另一项。
- inventory 的变更可明确要求刷新/重启；不能从用户输入拼 checkpoint 路径。坏文件、越界数值、symlink 等维持 fail closed。
- CLI 和 `--tui` 的启动前选择共用这一套路径。`--status` 继续纯只读，无须新增第二套交互列表。

Red/Green：1/16/17/33 个无 Goal 会话、混合 Goal/无 Goal、终态过滤；末页可选、前后换页、无下一页/非法值；选择第 17 个确实得到对应 conversation；完整 checkpoint manifest 不变；stale/错 workspace/损坏/未知 outcome 仍安全拒绝或准确进入恢复。

## D4：切换模型时显式不加载旧 owner preferences

接口：`--without-owner-preferences`。这是当前进程有效的明确选择；不是自动降级，不持久化开关。

首选文件：`main.py`、必要的 `agent/composition.py`、`tests/cli/test_entrypoint.py`、`tests/cli/test_everyday_entrypoint.py`、`tests/memory/test_owner_preferences.py`、`tests/provider/test_remote_disclosure.py`。

- 未提供参数时，原 trust binding 严格匹配；mismatch 错误新增这个可用指引。不得把任意 MemoryStoreError 都当作可忽略的 mismatch。
- 提供参数时，不读/建/写 owner-preferences.json，不注册该 source 或 confirm/correct/forget 工具；不使用空 fake preference store。启动明确提示“本次未加载 owner preferences”。
- workspace conversation、history、审批和 unknown effect 都保留；当前 snapshot 可以打开不等于自动给新模型外发许可。新 descriptor 的实际上下文仍必须重新 disclosure，并包含正确的数据类别。
- 不绕过 workspace identity、旧 pending approval 或 provider 绑定；凡已有跨 provider continuation 合同拒绝的行为，保持拒绝并记录具体原因，不能直接重放旧 effect。用无 pending 决策的会话证明最小切换成功。
- 显式配置的 workspace Memory 仍按它自己的 trust 校验，不能跟着悄悄禁用。切回原模型且不带参数时，原偏好 bytes/digest 和召回功能恢复。

Red/Green：同 endpoint model-a→model-b，空/非空合成偏好库均可用新参数启动；无参数仍拒绝；spy 证明 skip 下零 preference store I/O；缺 key 时 --status 不受影响；新模型零请求直到新 disclosure；拒绝 disclosure 零外发；旧 pending approval 不执行；回到原模型原文件不变；workspace Memory 行为不变。

## D5：日常任务端到端复验与有证据的窄修复

先对照 VERIFICATION 的自然用户输入测试当前实现。特别是 U5 不能先靠想象重构。没有失败则只记录 PASS；有失败则保存脱敏模型控制/工具选择和结果，在现有 ScriptedProvider/MockTransport 中稳定复现最近原因，再修代码。

优先检查：bootstrap 是否误把只读回答建立成文件 Goal、配置提示是否与实际工具阶段不一致、只读工具结果是否被 context 正确保留、model response 是否走了错误 normalize 分支、精确 executable 是否能被现有 preparation 接纳、成功结果是否正确到达 parent final。

允许的修复范围：上述现有 entry routing/context/provider/tool preparation 及对应 focused tests。不得关键词硬编码“TODO 就返回固定答案”、伪造成功 process receipt、静默换 provider、仅关闭证据门禁，或让测试 wrapper 替模型选工具。System policy 可以精简纠正，但不能只用字符串断言宣告模型可靠。

完成：K1–K5 必测案例见 VERIFICATION。一次稳定成功即可，不为刷连续 Green 重跑付费案例。若真实失败仍未解决，结果写 FAIL；若成本/外部环境阻塞则写 BLOCKED，不能把问题转换成“8 次后正常暂停，所以测试通过”。
