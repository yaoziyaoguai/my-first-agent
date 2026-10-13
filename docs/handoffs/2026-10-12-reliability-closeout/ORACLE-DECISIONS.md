# Oracle 审计收据与 Codex 合成裁决

本文件是固定咨询记录，不是第二份进度。实际执行合同见 [START-HERE](START-HERE.md)；唯一当前状态仍在旧包 RESULTS。

## 1. 本次确实完成的 Oracle 会话

| 项 | 证据 |
| --- | --- |
| 日期 | 2026-10-12；选档记录 UTC 03:42:53.541，完成/清理核对 UTC 04:03:41 |
| 独立新 session | `fa-closeout-max-20261012-5ab2d4f8`；未 followup、未复用旧失败会话 |
| 本次强度 | `max`，两次发送前检查为 **5/5**；可见标签原样为 `Power, item 5 of 5 (slider ARIA)` |
| 模型证据边界 | wrapper 使用 current 策略，verified=true；CLI 的 `requestedModel=GPT-5.6 Sol` 不用来证明实际网页模型 |
| 提交 | promptSubmitted=true，并形成新 conversation `6acc5732-cf54-83e8-a04f-acc468954c4c`，随后捕获完整 assistant 答案；不是只凭发送尝试认成功 |
| 输入 | 独立 Prompt + 两个附件：公开事实摘要、20个源码/测试/合同文件的明确范围摘录；约63,035输入token |
| 结果 | session status=completed；wrapper exit0；约20分21秒；[完整答复](oracle/RESPONSE.md) 42,106字节、528行 |
| 清理 | 本次记录的 Chrome PID 20841 已不存在，临时 profile `oracle-browser-ph1yfc` 已不存在；未对其他 Chrome或controller发信号 |
| 工具身份 | doctor核对已安装 wrapper `/Users/jinkun.wang/.local/bin/oracle-web`、upstream `/opt/homebrew/bin/oracle`，既定 source profile `chrome-source/Default`；未切profile、未升级CLI |

本次只发送公开/合成项目材料，没有 key、.env、私人会话、旧 .local/q3、个人浏览器内容。Prompt禁止并行委派，Oracle最终 `optional_subagents: []`。本地也没有启动其他 coding agent。

运行附记：dry-run 按 wrapper 默认过期策略报告回收了7条旧 Oracle session记录；正式咨询使用 `--retain-hours 0` 避免进一步过期回收。没有删除仓库文件或产品私人运行资料；未检查这些旧记录，也不承诺其可恢复。本次输入/答复已保存在本包，不依赖临时浏览器继续存在。

## 2. 输入与答案身份

以下文件保持咨询时原字节；`INPUT_MANIFEST` 是审计抽样，不是完整产品候选。

| 文件 | SHA-256 |
| --- | --- |
| [PROMPT.md](oracle/PROMPT.md) | `b39c689dbf38d2c6af93b733b9e7bb6eed6c90f6e04fcf48382e9149f02a67c2` |
| [AUDIT_CONTEXT.md](oracle/AUDIT_CONTEXT.md) | `386101f3400642a74e8ffefb449987787087ec2ad42781a2e5b8642e99e27891` |
| [CODE_CONTEXT.txt](oracle/CODE_CONTEXT.txt) | `cc18a0ac32bececf40f91e8c3add7287eddb7b6614e2e58cffdaab66216d4e4e` |
| [INPUT_MANIFEST.json](oracle/INPUT_MANIFEST.json) | `981548bfc7659cb76c15e6ddb9651217d2e50c360b32f4386821be1a76fb3b23` |
| [RESPONSE.md](oracle/RESPONSE.md) | `2a0bb5c0e709aa60e447c226654d9f87291122a89320eb07a0b183c51830d520` |

## 3. 采纳、修正与拒绝扩张

| Oracle建议 | Codex裁决及落包位置 |
| --- | --- |
| A2先做，误删风险优先级最高 | 采纳。P0是防误操作优先级，不表示已经发生数据损失或已证实远程漏洞。固定顺序先W2，修好前不用旧脚本导出。 |
| A1看验证取得时是否有writer，而不是一律让stop失效 | 采纳。已补读两个evidence入口与资源投影，当前均缺取得时资格检查；loop的ordinary回落陷阱也与源码一致。W1明确共享纯资格判断和幂等stop对照。 |
| start未ready时清理未知可能不受资源投影保护 | 采纳为必须核验分支，不预报泄漏。已补读ToolRuntime的非只读异常上抛及KnownNotExecuted分类，但尚未执行该分支；W1要求沿现有UNKNOWN/owner合同做真实区分测试。 |
| A2固定新out与同级manifest、完整预检、排他发布，失败不递归回滚 | 采纳。收窄的是仓库开发取证脚本，不是产品文件工具；代码引用检索未发现其他Python调用方。允许物理父目录规范化，拒绝危险叶子/包含关系；不引入通用安全构建框架。 |
| A3的125可能来自清组，也可能来自输出管道收束 | 采纳。已直接核对`_run`两个异常合并分支；先分阶段诊断和fixture finally，再决定共享层是否要改。采用8次/10分钟/单次60秒诊断上限，替换早期草稿的3次/15分钟。 |
| A4显式disabled优先，None保留现有兼容合同 | 采纳。P1因为公开选择的合法模式确定失败；不改默认、identity、容量、provider，不自动支持会话中途模式转换。 |
| E1增量installed即可，父进程guard不能证明child来自wheel | 采纳。V2核对实际spawn脚本及摘要；复用原guard和pytest原生选择，不新造runner框架，不额外跑installed全库。 |
| E2同时验证物理计数、账本、新进程，并允许合法新意图 | 采纳。本地fixture加X/Y可继续推进、真实EXECUTING崩溃/UNKNOWN、相同参数合法新任务、不同call ID仍能发现重复的负对照。 |
| E2-02新call ID重提已完成X必须不能自动执行 | **有条件采纳**。先核对当前已有意图/授权/抑制合同；测试标签不是产品的语义识别机制。既有授权允许的模型新请求不能无证据改称内核重放；若需新的跨run语义去重，记录限制并请求产品决定，不纳入隐含修复。 |
| 每次增量focused，安装检查后再最终全量 | 采纳。缺陷Red与证据负对照分开；清除installed筛选后完整门，失败不得重跑到绿；不调用015总E3入口越过真实调用权限。 |
| HEAD或SHA任何变化立即停全部 | 收窄为停止相冲突的产品修改并报告；只有本包文档变化、且产品SHA一致时可继续。不能因资料包本身造成dirty就删文档，也不能自动reset。 |
| 只保留一个执行主载体与RESULTS | 保留本仓库惯例的入口/工作项/验收三个阅读文件，分别只写一类信息；不再新增current状态、评测系统或分叉完成表。唯一可变进度仍复用旧RESULTS。 |

### Codex额外核实的一个证明漏洞

`agent/cli/app.py` 的 `/resume` 在没有 active_run 且goal paused/blocked时走 `ResumeGoal`。现有 `test_resume_goal_uses_exact_goal_and_revision` 明确断言provider不调用。因此只做 `/resume` 后观察“0次工具调用”会是空洞证明。

V1已要求分别记录恢复控制与正常推进，再经过一次不重述任务的“继续当前任务”生产loop；另有Y正常执行证明工具未被全局阻断。不改变 `/resume` 产品语义。

## 4. 最小产品收尾与明确延期

不因历史12次审批、18次外发提示就删审批。执行者只核对本轮错误出口是否已经说明下一步：冲突路径用新名称；资源未关闭先关闭再验证；清理失败明确哪阶段及是否未知；disabled正常响应直接可用；UNKNOWN需用户决定。已有足够提示就不改，缺失时只补该现有出口的短错误文案及测试，不新增UI流程。

延期：审批合并/外发体验重做、跨模式会话迁移、其他供应商/平台、全网站承诺、Memory/MCP/SubAgent新能力、持续监控、长期调度、永久语义去重、自动清理历史产物、按文件长度重构。产品状态仍为implemented-candidate，不自动promotion。

## 5. 核对过的外部依据

Oracle捕获文本中的引用只留下来源标签，不能当作完整可追溯链接。Codex另行核对了以下primary sources，仅用于接口语义，不用它们替代本机回归或定位根因：

- `lstat`不跟随叶子符号链接，`os.link`为创建硬链接接口：[Python 3.12 os](https://docs.python.org/3.12/library/os.html#os.lstat)、[os.link](https://docs.python.org/3.12/library/os.html#os.link)。
- POSIX link的目标已有目录项或符号链接时失败，适用于同一文件系统的不覆盖发布：[The Open Group link](https://pubs.opengroup.org/onlinepubs/9699919799/functions/link.html)。不是跨平台发布保证。
- `communicate()`包含读到EOF与等待进程的阶段，超时不自动杀死子进程：[Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html#subprocess.Popen.communicate)。
- `PYTEST_ADDOPTS`将参数交给pytest，现有runner因此可用`-k`做有界选择：[pytest环境变量](https://docs.pytest.org/en/stable/reference/reference.html#envvar-PYTEST_ADDOPTS)。实际节点集合仍须核验。

本轮没有重新验证DeepSeek线上协议；None/disabled/enabled的资料包合同来自当前代码与回归约定，线上canary需要当前授权。
