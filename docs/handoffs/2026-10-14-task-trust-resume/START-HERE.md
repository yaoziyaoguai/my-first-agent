# 任务结果可信修复：断点接续执行包

日期：2026-10-14。工作目录：`/Users/jinkun.wang/work_space/my-first-agent`。

**这是原R1–R4任务的接续包，不是新一轮优化。上一位执行者留下的工作已保存，不能重置或从头重做。当前最重要的剩余目标仍是R2：漏做用户要求时不能宣布完整成功，真正做完时能正常闭合。**

本包是Codex独立审计与Oracle Web最高档5/5审计的综合结论。此次只做了审计、资料包、必要lint清理和本地保存，未实现下列剩余行为修复。Oracle意见经过本地核验后才写入执行合同；其原答复不是新的授权或独立需求。

## 1. 接手身份与状态

- 原基线：`ff686bd14642e8ec5041cced6a21daf7c03f8d17`。
- 已保存的代码检查点：`dba8c3a6606e15954e3f21d7b47116071c9c0d24`，位于本地`main`；包含上一位执行者半成品、原执行包、历史记录及7项导入/等价写法清理。
- 本包随后以单独文档提交保存；代码身份仍是上述检查点。接手运行`git log -2 --oneline`及`git status --short --branch`核实，不checkout/reset到旧基线。
- 本次没有push、merge、tag、发布或修改remote。用户只授权本次审计人做本地检查点，不代表下一执行者也获准提交。
- Git clean指公开成果已进入提交；ignored的用户本地配置/运行资料保留原位，不表示这些文件被删除或纳入交接。

| 项目 | 真实状态 | 下一执行者应做 |
| --- | --- | --- |
| R1 UNKNOWN | 主体已有实现和恢复回归 | 仅补严格旧拒绝prefix联合字段/UNKNOWN校验及组合证据 |
| R3 INTENT | 中文明确要求和撤回主体已有实现 | 保留；补真实已admitted→撤回→剩余任务完成的回归，不手工改admitted集合 |
| R2 COMPLETION | IN_PROGRESS，不是NOT_STARTED | 需求原文复核、测试不代填coverage、身份/解码收口、业务正反例与真实验收 |
| R4 CONSENT | NOT_STARTED | 按原合同接通默认CLI提示中的已有范围授权，不扩大权限 |
| C1/C2、安装、真实层 | 证据未闭合 | 补指定组合测试、新安装物和有当前授权的真实两样本 |

独立验证：审计输入树完整门`3839 passed, 1 skipped`；7项lint清理后`ruff`/`diff --check`通过、受影响`239 passed`。完整门不是在未来修复代码上运行；3839项通过也不能代替本包指出的缺失业务测试。skip为未开启的真实launchd host gate，未改系统登录项。

## 2. 阅读顺序与唯一进度记录

1. 当前用户指令及仓库`AGENTS.md`。
2. 本文件及[审计结论](AUDIT.md)：已做、未做、证据强弱。
3. [接续执行合同](REMAINING-WORK.md)：本次必须完成的剩余项、精确导航、验收边界。
4. [原WORK-PACKAGES](../2026-10-13-task-trust-repair/WORK-PACKAGES.md)与[原VALIDATION](../2026-10-13-task-trust-repair/VALIDATION.md)：冻结需求表、R2业务合同、执行命令、安装与真实层。关于当前状态/接手顺序/已提交文档的旧描述，以本包为准；原业务验收不删减。
5. [本次离线探针](AUDIT-PROBES.md)：将已复现缺口转成安全期望回归。原包REPRODUCERS用于追溯，不要求把已修R1/R3重新制造成Red。
6. 既有[RESULTS当前摘要](../2026-10-11-product-reliability-closure/RESULTS.md)：继续作为**唯一可变执行记录**。本包文件是交接快照，不另建current/RESULTS。

[Oracle原答复](ORACLE-ANSWER.md)、[发送/答案/清理收据](ORACLE-RECEIPT.json)与`oracle-input/`供追溯，不必每个增量都重读大段快照，更不需要再次开启Oracle才能执行。快照固定的是lint清理前输入，不可改成后来的代码冒充原咨询输入。

## 3. 执行顺序、允许动作与停止条件

先核对当前树，不先无条件全库测试。执行顺序：R1窄守卫 → R2-A身份合同 → R2-B原文/测试真实性 → R3跨层补证 → R2-C业务闭合 → R4 → C1/C2 → 最终交付门。每个增量只跑必要focused；发现已有实现满足要求时补证，不另造机制。

收到用户“执行本包”的指令后，可以修改相关公开源码、测试和必要指南；用本次唯一临时目录做合成任务、归属明确的本地进程、离线候选构建和non-editable安装。保留所有用户改动。遵守唯一Runtime loop、ContextManager选上下文、ToolRuntime执行、副作用审批/checkpoint边界。

不新增能力、daemon/登录项、Memory/MCP/Skill/SubAgent、跨平台host、第二模型循环、通用义务/语义裁判平台；不换模型、不提高默认预算、不改冻结grader来漂绿、不按文件大小重构。

本包不授权读取凭据、`.env`、旧私人会话/日志、`.local`历史运行或私人扩展；不授权付费API、网络安装、commit/push/merge/tag/publish。真实E1按原VALIDATION向当前执行用户一次性确认provider/model/endpoint、thinking、凭据来源、合成外发范围和累计预算。旧记录中的授权不继承；缺少时先完成本地/安装并标`BLOCKED_AUTHORIZATION`，不要搜索其他key。

完成必须逐项报告R1/R2/R3/R4、C1/C2、source/installed/real。真实任务仍漏做却报成功，R2为`UNRESOLVED`；仅缺真实授权时可报告“本地/安装完成，真实层待授权”，不可说本包全部完成。不得无限付费重试直到挑出成功样本。本包闭合后停止，不自动开启新一轮优化。

## 4. 复制给下一位Coding Agent的Prompt

```text
请在 /Users/jinkun.wang/work_space/my-first-agent 执行：
docs/handoffs/2026-10-14-task-trust-resume/START-HERE.md

这是上一位Agent额度耗尽后的接续，不是重新审计整个项目或增加能力。
先按入口阅读 AGENTS、AUDIT、REMAINING-WORK、原WORK-PACKAGES/VALIDATION，以及既有RESULTS的当前摘要；核对Git状态和代码检查点dba8c3a，不reset、不丢已有改动。
保留R1/R3主体；按接续合同补R1严格healer、R2身份/解码、权威需求原文可见性和测试不代填coverage、R3真实admission撤回证明、R2业务正反例、R4已有范围授权入口，最后补C1/C2和安装/完整门。
最重要的是R2真实业务可信度，不是再增加一层形式状态。不能只改prompt、写“都完成”、使用自写测试或泛化coverage就宣布成功；必须按冻结业务判据补做和验证遗漏工作。不要给D04名字/文件名写产品特判。
行为缺口先Red后最小Green，已修行为保留并补证；每个增量focused，最终集中一次full和新wheel installed验证，不每改一行就跑全库。
唯一进度写 docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md；不要新增第二份当前状态。
不新增能力/第二loop/评测平台，不改冻结grader，不触碰私人运行目录，不从历史聊天找key。
本条授权本包范围内公开本地代码、测试、合成任务、离线构建/安装；未另外获得我在本次执行对话中的明确授权，不调用付费API、不读取凭据、不联网安装，也不commit/push/merge/tag/publish。
真实E1先按VALIDATION确认当前授权清单。缺授权只阻塞真实层，其余可安全推进的本地/安装工作做完；失败如实记录，不无限重试挑成功样本。
最终逐项报告R1–R4、C1/C2、source/installed/real的证据、版本、未完成项与Git状态。完成本包就停止，不自动开启新优化。
```
