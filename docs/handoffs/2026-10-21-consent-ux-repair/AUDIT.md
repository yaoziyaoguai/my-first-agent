# 确认疲劳审计：Codex 本地事实

日期：2026-10-21。基线 `main @ 97f5c584e9e266930fbcf283aa3199b3609e8178`。
这是本轮本地事实快照，不是第二份可变进度。最终执行合同见本目录 `SPEC.md` 和
`WORK-PACKAGES.md`；Oracle 原答只作审查意见。唯一可变记录继续使用
`docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md`。

## 结论与证据限制

用户反馈“太多需要我来 yes yes 的操作”有当前生产路径的可复现依据。主要是
**数据外发同意粒度随内部上下文变化、默认输入只批单笔、复用选项发现成本高**。
不能把它归结为用户不会输入高级命令；也不能用全局自动同意代替修复。

本次未读取用户的试用会话、终端历史或私人配置，因此不声称知道其每一条确认的具体来源、
总数或分布。所有下列观测来自公共源码和内存合成夹具，真实网络请求数为零。
现有 `result.phase.json` 未读取、未删除。没有修改产品代码、权限策略或用户安装。

## 1. 必须解决的用户问题

### L1 / P1 体验：外发确认绑定的是精确类别集合，不是已经同意的可理解范围

- 位置：`agent/runtime/loop.py::_required_disclosure`、普通发送和 compaction 的两处门禁；
  `agent/runtime/contracts.py::ProviderDisclosureRequest._expected_digest`。
- 实测：同一个远端 descriptor，三轮普通问答，**两次确认**；第2次只比第1次多
  `conversation_history`。3次 ScriptedProvider 调用，零 HTTP。
- 当前只有最后一份 request/receipt。生产 builder 对类别 A→B→A→B→B 的摘要变化为
  `[true,true,true,true,false]`。已见过的集合和收缩后的子集也可能再次不匹配。
  这条是 builder 层证明，不能冒称已经跑过完整生产 compaction 往返。
- 正常构造和 compaction 的实际 `ContextPack.data_classes` 都有精确来源语义。
  **不能删掉分类、扩大成假的“实际发送类别”，或让工具自报“低风险”来绕过确认。**

### L2 / P1 体验：文件确认的主路径引导用户反复单笔批准

- 位置：`agent/cli/render.py::_approval_message`、`agent/cli/app.py::_parse_action`。
- 主提示是 `Execute this operation? [y/N]`；`yes` 的 `authorize_goal_target` 与
  `authorize_goal_directory` 都是 False。复用选项在后面用较长 slash command 展示。
- 同一 pending fixture 下，`/approve-goal-target` 正确生成精确文件 opt-in；
  现有真实 Runtime 测试证明两次同目标写入只需一次该选择。
- 所以不是“权限复用完全没实现”，而是默认交互把用户留在最繁琐路径。
  只加 README 教用户记命令不算本轮完成。

### L3 / P2 体验：恢复和内部控制回执带来二次、三次确认

- 位置：`state.py::acknowledge_provider_disclosure`、`context.py` 的 history/control 类别。
- 合成前缀：暂停前类别为 `goal/system_policy/user_messages`；恢复后第一次 ack 后
  新增 `conversation_history`，第二次 ack 后新增 `control_receipts`，仍待确认。
- 这是有界恢复前缀，不是已经完成的真实用户任务；具体 JSON 记录了每次 provider 调用数。
- 旧 pending 可以恢复是已修复行为，不能通过丢弃 pending/清空会话来消除新提示。

## 2. 应保留的能力与边界

- **文件授权已经有限且可撤销。** 同一 Goal/revision/workspace/操作/目标，16 次、60 分钟；
  目录必须是 Goal 明确列出的范围，不从任意文件推导父目录。`write_file` 的授权不等于
  `edit_file` 授权；这不是本轮可以悄悄合并的权限。
- **本机命令已经有 exact lease。** 最多8次、60分钟；命令、argv、cwd、执行体、环境、
  profile 等身份绑定。它是同 UID 进程，不能因为叫 pytest/python 就自动认为隔离安全。
- 普通文件 `y/yes` 是单笔效果同意；**外发 `y/yes` 则是确认当前声明类别的精确 request**，
  当前相同 request 可重复使用，不应在新 UI 误写成“只允许一个网络请求”。
- 新界面不得把普通 `yes` 静默升级为任务/会话范围授权。空回车/EOF 的拒绝边界保留；
  unknown outcome 的 success/failed/stop 不能改成普通 yes。
- 结果与检查点仍是权威，不靠 renderer 缓存、自动回答、REPL 内第二套权限表降确认数。

## 3. 最容易做错的修复

1. **只隐藏提示但 Runtime 仍停住**，或者用测试 operator 自动按 yes；这不减少用户决策。
2. 用 `data_classes` 的 subset 比较配旧 receipt，但 receipt 根本没持久化可信授权集合；
   不能从当前新 request 或模型文本反推出旧用户曾同意的范围。
3. 新授权到期/撤销后，又通过同一次操作留下的旧 exact receipt 回落放行。
4. 只改正常 provider 路径，遗漏 compaction、恢复和已持久化的待发送意图。
5. `tool_results` 是无细粒度 receipt 的通用桶，不保证只有普通文件/命令结果；
   Memory/MCP/Skill/SubAgent 或未知工具不能靠它被误归入常规工作区范围。
6. 为图省事自动批准工作区全部命令、任意目录，或恢复时自动重放未知效果。
7. 新增可持久化权限却让旧 v10 checkpoint 获得更大的默认权限；严格解码和迁移必须显式。
8. 只修源码，却让用户继续从旧固定预览 wheel 启动。必须交付一个新安装身份与新启动入口，
   不覆盖旧安装/会话，不把源码测试当成用户安装版已经生效。

## 4. 已执行的可复核检查

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  docs/handoffs/2026-10-21-consent-ux-repair/baseline_probe.py

PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 \
  .venv/bin/python -m pytest -q -rx --color=no -p no:cacheprovider \
  tests/cli/test_contextual_decisions.py tests/cli/test_render.py \
  tests/provider/test_remote_disclosure.py \
  tests/cli/test_process_authority_parity.py \
  tests/kernel/test_runtime_process_authority.py \
  tests/kernel/test_runtime_compaction.py
```

- 探针：exit 0，输出见 `BASELINE.json`。它是基线观察器，不是修复成功判定器；
  未来实现后应新增针对明确 opt-in 路径的 Red→Green 测试，不能把旧 exact 路径的
  正常保守行为改标为错误。此前内存诊断使用“普通三轮最多一次确认”的 UX 目标产生
  `AssertionError: 2 remote confirmations`，只是体验差距的负控，不是旧合同违约证明。
- 相关现有检查：**153 passed / 0.89s / exit 0**。
- 上一交付的全库4054/1skip、安装76、真实E1等属于其冻结身份；本轮不重复全库，不冒称
  新授权设计已有实现或真实模型证据。
- 当前源码身份清单见 `oracle-input/SOURCE-IDENTITY.json`；Graphify 只读定位后以当前源码
  和上述执行结果核实，未重建索引、未摄入 ignored/private 输入。

## 5. 本轮修复包的完成标准

新设计必须同时改善“能否一眼选到正确授权”和“完成同一任务时真正要回答多少次”。
冻结合成工作流、明确输入选择和允许的数据/文件范围，分开计数外发、文件、命令、恢复决定；
所有减少次数的正例都要达到相同任务效果/结果。拒绝、越界、到期、撤销与漂移的负例仍须
在 provider/tool 副作用前拦住。真实用户是否感觉更顺，留给新安装版的一次短试用，不靠
单元测试或 Oracle 文字判定代替。

## 6. 制定实现包时补查的易错细节

- `checkpoint.py::_encode_state` 不总写当前schema：无特定状态时会选legacy v2。
  新许可存在但active run已结束时，不能因此漏存或错用旧编码；这是新增持久化字段的必要验收，
  不是声称当前版本已有“丢失新许可”的缺陷。
- `AcknowledgeProviderDisclosure.acknowledged_at` 当前允许 `operator-confirmed` 这类标记。
  新有期限许可不能把这个字段直接当可信RFC3339时钟；必须给期限明确的可信产生和校验路径。
- `run_repl` 先读snapshot、显示pending、再解析输入并把同一个snapshot传给Runtime。
  保留这条所见即所批的链，不要在解析短选项时重读并改批新请求。
- 文件与进程授权不是同一语义：现有进程批准已铸造8次/60分钟exact lease；现有测试
  `test_015_pause_and_cancel_clear_process_leases` 明确暂停/取消清除进程租约。
  本包不能借外发恢复体验改掉这些规则，也不能把所有工具的y都写成“仅一笔”。
- `ConversationSummaryV1` 是不可信摘要正文，不是授权来源。不得让模型输出一个summary字段
  就扩大许可；压缩发送仍须检查其实际输入来源，旧摘要不拿来重建权威权限。
- 来源分类尚未细化是本轮边界，不意味着应顺手把全部MCP/Skill/SubAgent工具改造一遍。
  使用保守、明确披露的范围，并如实保留未覆盖来源的必要确认。

## 7. 归档与交接核验

Oracle原答与已发送源码摘录保留逐字SHA身份；其中原答有2行、源码行号摘录有若干行原有
尾部空白。沿用仓库既有规则，只给这两个精确归档路径补.gitattributes空白声明，不修改
外部输入/原答，不放松产品代码检查。最终文件身份、引用和扫描结果见PACKAGE-CHECK.json。
