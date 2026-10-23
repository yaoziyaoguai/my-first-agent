# 复制给接手 coding agent 的 Prompt

以下整段可直接发送；发送本段表示授权其中明确的本地实现、离线验证和专用新预览交付，
不表示授权Git远端操作或真实API费用。

---

请在 `/Users/jinkun.wang/work_space/my-first-agent` 执行“确认疲劳修复包”，不要另开优化轮次。
主要问题是用户试用中反复回答yes，交互负担太重。不是加新能力，更不是关闭安全围栏。

先完整读取：

1. 项目AGENTS.md。
2. `docs/handoffs/2026-10-21-consent-ux-repair/START-HERE.md`。
3. 同目录 `AUDIT.md`、`SPEC.md`、`WORK-PACKAGES.md`、`VALIDATION.md`、`RECONCILIATION.md`。
4. 既有唯一进度记录 `docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md` 的当前摘要。

最终合同以SPEC/WORK-PACKAGES/VALIDATION为准，Oracle原答只作理由来源，不重新让用户选
已经冻结的工程方案。不要重新调用Oracle、另起多Agent评审或重新审计整个项目。

授权范围：本地代码/测试/相关使用说明修复，离线合成测试，fresh候选与wheel、隔离venv，
在 `/Users/jinkun.wang/.local/share/first-agent/previews/` 下创建一个唯一的新专用预览及新state。
不覆盖旧预览/状态，不更改系统设置、PATH、shell profile、登录项或后台服务。
没有授权commit/push/merge/tag/release、外部依赖安装、真实provider/MCP网络或读取凭据文件。
不要使用历史对话中的key、历史付费额度或私人会话；未知 `result.phase.json` 不读不动。

基线是 `97f5c584e9e266930fbcf283aa3199b3609e8178`。先核对HEAD/status和包内SOURCE-IDENTITY，
保留已有用户改动；已经正确完成的部分不要重做。仓库规则默认main，不创建worktree、不reset
或clean。当前包本身未提交是正常状态，不要以“清理仓库”为名删除或提交用户文件。

按 W1 → W2 → W3 → G 执行，每包先最小Red再Green；中途只跑focused，最终集中一次全库门。
不需要每写一个函数停下来问；遇到真正的权限/范围变更、不可恢复冲突才询问。

冻结目标：

- 文件审批直接显示 `f`（本任务同文件同操作）、`d`（Goal明确目录同操作），完整复用现有
  slash动作；16次/60分钟不变，不跨write/edit、不猜父目录。y含义不变。
- provider首次合适提示显示显式 `s`：同conversation/workspace/provider/model的常规会话
  内容最多32次派发、60分钟，另有 `/revoke-provider-consent`。与效果许可分开。
- actual data_classes仍真实。新增有界grant、工具/control定义身份、必要的来源证明；
  仅write_file/edit_file成功结果支持稳定文件例外。通用tool_results、Memory/MCP/Skill/
  SubAgent等不因标签相同而自动获许可。summary不得抹掉原来源边界。
- 新模式常规许可和最后一个精确例外共用TTL/额度/撤销；禁止旧receipt OR grant兜底。
  无法稳定证明的来源只明确批准当前待发内容；不升级为未来任意结果授权。
- schema11，保留旧2–10/pending/request/receipt语义；新范围不从旧同意推导。
  无active run时也不能丢grant/fence。旧安装不读写新schema来回退。
- 正常/compaction发送共用判断及durable扣次；失败不退款、重启不续期，结果恢复不重复派发。
  撤销复用既有mutation lease；忙时不能假报成功，不建设新的异步撤销系统。
- 唯一AgentRuntime循环、ContextManager/ToolRuntime所有权、policy/CAS/执行/结果checkpoint
  和unknown恢复全部保留。不要为了少问改变业务完成门、grader或历史报告。

验收必须从真实CLI提示、固定输入、typed action、durable state走到实际效果，不能只测文案。
新增测试统一 `test_consent_ux_` 前缀。U1三轮普通对话1次外发；U2同文件三写1次文件决定；
U3明确目录复用；U4精确命令三次1次命令决定；U5/U6恢复/压缩无额外常规确认；U7旧语义；
U8完整3写+read-back+合法claim，3次外发+1次文件决定=4，typed VERIFIED_DONE；U9常规A和
同来源B五次交替发送共2次外发决定。前置、分母、全部20组负控以VALIDATION为准。

注意：Oracle的“四响应合计3次”例子已被本地审计修正，不能删read-back或用文本done来凑数。
不要循环自动yes、多余提示算失败；分别统计外发/文件/进程/恢复/业务救场，不能把受阻任务
计为“完成且少打断”。任何实现困难都不能成为扩大默认权限的理由。

完成前运行项目要求的git diff --check、ruff与完整pytest，失败/超时/截断不算通过。
使用fresh candidate/wheel及非editable新venv，在checkout外验证导入origin与本轮冻结节点；
保留旧安装。交付精确的新启动命令，不只告诉我源码已改，因为旧预览不会自动更新。

进度与证据只更新既有RESULTS顶部本轮章节；不要改包内BASELINE、Oracle输入/原答/身份文件。
记录全部失败尝试、修后证据、未验证项。真实API没有本轮新授权就标NOT_RUN_AUTHORIZATION，
继续完成可离线完成的工作，不去找旧key；用户体验验收留给交付后的短试用。

最后给我：改了什么、每包Red→Green、U1–U9与20组负控结果、确认次数前后表、完整门和
安装身份、新启动命令、仍会询问的场景和未验证项。当前包完成即停，不再发散新功能。

---
