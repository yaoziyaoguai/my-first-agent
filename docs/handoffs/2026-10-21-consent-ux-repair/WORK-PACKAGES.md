# 实施顺序与工作包

最终顺序：**W1 合同/来源/持久化 → W2 发送门 → W3 CLI → G 交付**。
每包先Red后最小Green，不反复全库。Oracle意见与本地补查已合成SPEC，不再让执行者重新选方案。
接手代码若已部分实现，核对后保留正确工作，只补缺口。

## W0：接手检查，不另开设计轮

- 核对HEAD、`git status --short`、AGENTS和SOURCE-IDENTITY；保留用户改动。
  不读取未知 `result.phase.json`，不reset/clean，不创建worktree或改变Git历史。
- 当前项目默认main工作；本包只授权本地修复和下述测试/新安装，不授权commit/push。
- 运行冻结baseline探针，保留原BASELINE。使用相同合成数据冻结U8旧版完整基线；
  旧输入只用旧y/slash，新版固定s→f→y，不用自动yes循环。
- 当前进度只写既有RESULTS顶部，引用本包；不创建第二个CURRENT/RESULTS。
- 一次定点补读即可：`AgentRuntime.run_turn/_run_locked/_tool_result_fact/_perform_compaction`、
  `KernelToolRuntime.invoke/_make_intent`、`record_tool_result/apply_compaction_summary`、
  checkpoint编解码、source投影、旧action入口。不得把缺失的未知符号当已实现。

## W1：有限许可、可信文件来源、schema11

解决新授权的可解释范围。此包先建立类型/严格编解码，不提前接通更宽发送。

### 允许修改面

- `agent/runtime/contracts.py`：grant、typed grant/revoke action、Action union、
  版本化披露请求、许可来源证明及必要的state/ToolResult/ContextPack字段。
- `agent/runtime/checkpoint.py`：schema11与2–10兼容、严格codec、writer版本选择。
- `agent/runtime/context.py`、`context_source.py`：由真实上下文构造只读许可投影；
  actual data_classes不改名、不扩成固定大集合。
- `agent/runtime/tools.py`、`agent/tools/file_ops.py`：仅内置write_file/edit_file
  registrations和成功结果的可信来源证明。可使用一个闭合registration标记绑定受信任厂商代码，
  但默认不具备来源能力，不按工具名字符串授信。
- `agent/runtime/loop.py::_tool_result_fact`、`state.py::record_tool_result/
  apply_compaction_summary`：保存Kernel证明/压缩输入来源；这里不新增循环或模型控制。
- 对应contracts/checkpoint/source/tool/compaction测试；最多一个窄共享纯函数模块
  收纳被多个生产路径复用的许可投影，不增加服务注册中心、第三方依赖。

### Red → Green顺序

1. 新grant严格字段和digest、旧schema不升级、无active run也能roundtrip。
2. 常规闭合集合包含goal_bootstrap/runtime_progress；schema定义身份增减/改变的区别。
3. 成功内置文件实际执行→Kernel证明→fact→ContextPack的可信链；工具自报同名metadata
   被拒/忽略为不可信，不能只测试手工构造好的证明。
4. 同工具同文件三次执行：执行真实性digest不同，稳定来源边界相同；换operation/target/
   Goal revision/工具定义/工作区则边界不同。
5. 常规summary与带文件/未知来源summary分别保留范围；旧summary不升级。
   模型summary正文仍是untrusted，不能增加可授权字段。
6. 新request显示真实类别，例外scope digest独立于常规类别涨落；严格区分legacy/new版本。

### 停止边界

本轮稳定例外只覆盖write_file/edit_file成功结果，不扩到全部read/search/process/MCP工具。
如果必须重写ContextManager或建立通用来源平台才可达成，提交具体缺失点和最小选择，
不要降低信任边界、假设metadata可信或以每次确认抵消预算目标。

## W2：统一发送门、32次/60分钟、失效与恢复

依赖W1；解决L1/L3及Oracle指出的例外回执生命周期问题。

### 允许修改面

- `agent/runtime/state.py`：action合法性、铸造/撤销/失效、次数、恢复点火。
- `agent/runtime/loop.py`：正常/compaction共享判定、发送前durable扣次、scope使用与结果恢复。
- 现有checkpoint/owner接口仅必要修正；优先复用当前整轮mutation lease，不新增撤销线程/服务。
- 对应provider/checkpoint/recovery/compaction/Runtime测试；不改provider HTTP adapter和业务grader。

### Red → Green顺序

1. U1真实Runtime三轮对话：显式grant后1次外发决定，3轮均完成。
2. 常规A、文件来源B的A→B→A→B：保留最后B例外，只有相同可信范围才能复用。
3. 第32次可发送，第33次不能自动发送；失败不退款、重启不续期、不补次数。
4. 正常与压缩两条发送路径实际走通；未覆盖来源先拦；结果恢复不重复调用/扣次。
5. 身份A→B→A持久化失效；撤销/到期/耗尽无旧receipt兜底，手动一次批准不恢复grant。
6. 按SPEC S6验证真实锁顺序：忙时revoke不能报成功；已接受revoke后后续发送为0。
   不要求新增“发送途中从另进程强插撤销”的机制。
7. 旧pending→pause→重开→resume→回答可点火；unknown effect仍走原消歧、不自动重放。

### 停止边界

不能只把digest相等换成集合包含；不能只修正常发送；不能把新许可存在当永久同意。
不得因过期单次y实现困难而自动回到legacy模式。不得改变后台caller的授权权威。
保持旧adapter动作含义，不给所有调用方新默认权限。

## W3：把选择放到当前提示中，完成真实交互链

依赖W1/W2；解决L2并把新许可交给用户，不要求其记住长命令。

### 允许修改面

- `agent/cli/render.py`：当前pending中的s/f/d、边界/期限/必要警告、状态与撤销说明。
- `agent/cli/app.py`：`_parse_action`、`_HELP_TEXT`、必要REPL拒绝/错误处理。
- `agent/cli/actions.py`：只构造typed action；f/d复用现有scope构造。
- `agent/runtime/views.py`及必要events：共享只读选择投影，不建立UI缓存权限表。
- 对应CLI/render/parity tests；README、daily-use相关短段；不重做全TUI/全指南。

### Red → Green顺序

1. 当前代码新短选项与提示缺失→Red；补最小显示/解析。
2. f/d与既有slash完整action等价，覆盖artifact/rebind差异；不适用选项明确拒绝不降级。
3. 同一snapshot显示/解析/执行；输入中revision漂移→CAS conflict且零provider/tool效果。
4. 普通聊天s/f/d不被抢占；旧y/n/a/slash/空回车/EOF语义保持。
5. 文件“单笔”与进程“exact lease”文案区分；unknown恢复/独立artifact确认不被快捷键吞掉。
6. prompt→固定回答→typed action→durable状态→provider/真实工具效果完整链；
   不用monkeypatch授权或直接塞grant代替这项。
7. 旧headless/TUI入口不扩权；新headless明确typed action才可进入同一校验。

## G：固定确认预算、一次完整门、新安装和交接

### 顺序

1. U1–U9与负控按VALIDATION完成；记录分项和总确认数、实际效果、业务完成分母。
2. 最终源码稳定后集中ruff/diff/full；不每小改动全库。失败如实归因、最小修复和必要复验。
3. 既有safe candidate builder使用fresh唯一输出；冻结源码/manifest/wheel身份。
   避免build/lib旧源码；新非editable venv、checkout外运行、安装origin验证。
4. 本轮新 `test_consent_ux_*` 节点集在源码与安装态collect==execute，不能漏跑或导入旧安装。
5. 新独立preview/state/launcher，保留旧预览和用户状态。只用进程环境引用凭据，不写key、
   shell profile、PATH配置或登录项。无依赖时报告，不擅自联网安装。
6. 一页交付说明给精确新启动命令、首次选择、必要再问场景、撤销办法；不能让用户继续旧wheel。
7. 没有本轮真实API授权记NOT_RUN_AUTHORIZATION；不捞历史key、用旧预算或清ledger续跑。
8. 更新既有RESULTS并检查diff范围，完成本包即停止，不另开优化轮。

### 失败与回退

- 授权/迁移/来源负控不通过不能交付“已降低确认且安全”；不隐藏提示或放宽fallback。
- 一旦生成v11状态，回退代码也须保留其解码/撤销能力；不要让旧二进制写新checkpoint。
- 旧preview留给旧会话。新preview使用新state；不恢复到效果前checkpoint，不丢失unknown记录。
- 不相关用户文件冲突时保留，只询问真正需要取舍的项。遵守停止请求，记录可恢复位置。
- 不commit/push/merge/tag/publish；本包执行授权不等于Git或付费授权。
