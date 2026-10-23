# Oracle意见与最终裁决

Oracle会话 `mfa-consent-ux-20261021-a7b29e` 已完整完成；上传前和发送前均有5/5 ARIA证据。
提交到新conversation，答案完整捕获，所拥有Chrome PID已退出、临时profile已移除。
详见ORACLE-RECEIPT。原答逐字归档，不冒充Oracle运行过本仓库或见过真实私人试用。

## 采纳

- 不是用户“不会用”：文件scope已有能力但选择藏得深，provider精确集合又把内部变化当成
  新决定。两条必须一起修，只改文案或教长命令不够。
- 显式s：一个会话级provider grant，32次/60分钟；不把它绑Goal revision重新制造打断。
- f/d严格映射现有scope动作；不跨write/edit、不猜父目录、不放宽进程exact lease。
- 实际data_classes、许可profile和可信来源边界分离；未知generic不能等于常规工作区数据。
- 新schema11、独立grant/revoke动作；旧2–10/pending/ack语义不自动扩大。
- 新模式常规许可与最后一个精确例外共用TTL/额度/撤销；A→B→A不能丢B，身份A→B→A
  不能复活旧许可。保留一个例外，不建授权历史数据库。
- 对内置文件成功结果补最小Kernel来源证明；summary继承输入来源，禁止洗成常规数据。
  这是组合确认预算所需的必要支持，不开展全系统来源治理。
- 固定完整交互计数；普通聊天通过不代表编码交互闭合。新wheel与真实启动入口必交。

## Codex补查后收紧/修正

### 1. 闭合常规集合补齐真实生产类别

Oracle表格遗漏 `goal_bootstrap`、`runtime_progress`。当前ContextManager确实生产这两类；
若不明确加入，任务刚开始/进度投影就可能再次打断。SPEC将二者纳入常规结构数据，未纳入
workspace_memory/owner_preferences/recalled_context或generic tool_results。

### 2. 撤销不新建异步控制通道

完整源码显示 `AgentRuntime.run_turn` 从try_acquire到finally release持有conversation
mutation lease；LocalCheckpointStore使用flock，忙时明确返回conversation_busy。
所以不能要求一个不持锁的第二进程在任意机器指令间隙“成功撤销”，再为满足测试建新线程。
最终合同是：已接受撤销后后续发送为0；忙时不能伪报成功；已发请求无法收回。用真实锁顺序
验证，而非绕锁写state。这保留Oracle的安全目标并避免多余基础设施。

### 3. 精确显示摘要与复用范围摘要不混用

如果新例外继续只比较完整request digest，常规类别涨落仍会破坏B的复用。SPEC明确：
receipt绑定当时确实显示的request，稳定例外scope独立于已许可常规部分；使用时验证两者
的覆盖关系，不伪称当前实际request与旧request完全相同。

### 4. 内置来源支持只做写/编辑，不一口气推广全部工具

完整生产链为：prepared ExecutionIntent→KernelToolRuntime.invoke严格核验registration/
arguments/policy/binding→Runtime._tool_result_fact→record_tool_result对照EXECUTING。
这些位置有足够的可信输入构造窄证明；当前fact没有完整证明，不能声称已经安全可复用。
实现只覆盖write_file/edit_file成功结果；read/search/process和其它集成先保持保守披露。
不更改SourceReceiptV1原有证据/引用含义，不将写成功伪装成读回验证。

### 5. 组合预算必须包含真实收尾，不能为漂亮数字省掉验证

Oracle提出“3次写入、4次模型响应、合计3次确认”。本地完整源码显示文件完成oracle需要
read_file/confirm_file的持久事实，普通文本done不能完成Goal。因此最终U8冻结为已有Goal
后3写+1读回+1合法claim：5模型响应，3外发+1文件决定=4，typed VERIFIED_DONE与独立
文件SHA同时通过。比原建议多一次必要的新来源披露，避免把阶段性工具效果说成任务完成。
这些仍是待实现验收目标；本次没有声称新预算已实测通过。

### 6. 兼容与默认安全按各入口原义，不统一“y仅一次”

文件y单笔；进程y按已披露8次exact lease；legacy provider y按精确类别可重复匹配。
旧文件空回车在REPL是忽略，不伪写为已拒绝；外发空回车则安全拒绝退出。
新快捷键不得改变artifact/rebind差异或unknown恢复语义。

## 明确拒绝/推迟

- 不做全局信任、自动yes、前缀命令白名单或新的权限管理控制台。
- 不把全部工具的来源改造列为前置；若出现实现阻塞，报告具体位置，不展开平台工程。
- 不把Oracle推荐的任意真实API预算当作授权；本轮无真实provider调用。
- 不宣称32次/60分钟已经适合用户：这是固定工程起点，交付后做一次短试用判断。
- 不动E2/E3、业务grader、登录项、后台调度、模型/key配置、Git远端。

最终可执行文本是SPEC/WORK-PACKAGES/VALIDATION/PROMPT，不要求接手者重新判断采纳哪份意见。
