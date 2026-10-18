# 日用 Agent 收口执行包

日期：2026-10-17。审计基线：`main @ 0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`（PR #5 合并后）。

## 一句话目标

**不增加能力菜单，把已有本地 Agent 做到：不漏掉明确交付对象、授权能实际复用、普通任务不用额外催促就正确收尾，并且安装物与验收版本一致。**

本包已经完成本地审计、最高档 Oracle 交叉审计、离线反例与执行合同准备，**尚未实施 W1–W3**。代码基线全量 3897 passed / 1 skipped，不代表新发现已经修复；skip 为需要单独授权的真实 launchd host gate，未改登录项。

## 阅读顺序

1. 适用的 `AGENTS.md`，以及唯一当前记录 [RESULTS](../2026-10-11-product-reliability-closure/RESULTS.md) 开头。
2. [AUDIT.md](AUDIT.md)：哪些已做、哪些还没做、证据和未验证边界。
3. [WORK-PACKAGES.md](WORK-PACKAGES.md)：W1 → W2 → W3 → G 的冻结范围、设计边界与验收。
4. [PROBES.md](PROBES.md)：可以在当前公开源码上直接执行的三个离线探针。
5. [VALIDATION.md](VALIDATION.md)：focused、有限真实旅程、最终安装/完整门、授权与停止条件。

Oracle 原始意见与审计回执分别在 [ORACLE-ANSWER.md](ORACLE-ANSWER.md)、[ORACLE-RECEIPT.json](ORACLE-RECEIPT.json)。`oracle-input/` 是不可改写的发送快照，不是另一份当前方案；实现时只在需要追溯时查它。若顾问意见与 WORK-PACKAGES 的本地裁决不同，以后者为本包实施边界。

## 三个修复包，只做这些

| 包 | 用户会得到什么 | 当前关键反例 |
| --- | --- | --- |
| W1 完成可信 | 明确要求的文件不会被模型缩小后的草稿排除在完成判断之外 | 只写 service、CLI 未动，非空声明仍 `VERIFIED_DONE` |
| W2 授权可用 | 对已由 Runtime 绑定且经人批准的当前文件，能显式选择有界复用 | 散文 targets 下每次都只能逐笔批准 |
| W3 正常闭环 | 正常旅程不被 driver 催促/额外纠正，完成与失败按实际判定 | E1-A 40 请求未收尾；driver 还误要求 normal 必须被纠正 |
| G 交付门 | 装上的就是验过的版本，日用入口与证据准确 | 旧 wheel/旧全量身份不覆盖最后源码变动 |

R1/R3/C1/C2、身份校验、原文 pin、证据刷新等已做的修复保留，不重开。新工具、Browser/Scheduler、跨平台、Memory/MCP/Skill/SubAgent、巨石拆分都不在本包内。

## 接手与权限

- 当前已跟踪产品树没有本轮产品改动。预期新增内容是本包与 RESULTS 摘要；接手时仍须以实际 Git 状态为准。
- 未知 `result.phase.json` 是原先的未跟踪内容：不读、不删、不纳入，不用 `git clean` 清场。
- 默认 main；不需要新 worktree、不 reset/stash 用户改动，不自行 commit/push/tag/merge/publish。此前其它轮的 Git 授权不继承。
- 没有当前真实 API 授权时继续本地/安装工作，真实层写 `BLOCKED_AUTHORIZATION`。本包没有密钥，不得从其它 Agent 或旧会话搜索 key。
- 首版支持面：macOS、单用户、CLI、一个经过本轮实际验证的 provider/model 配置、本地项目的有界任务。不能由此声称“所有功能/所有平台 production-ready”。

## 可直接复制给 Coding Agent 的 Prompt

```text
请在 /Users/jinkun.wang/work_space/my-first-agent 执行这份日用收口包，不重新开启发散审计：
docs/handoffs/2026-10-17-daily-agent-closeout/START-HERE.md

先完整阅读适用 AGENTS.md，以及该目录的 AUDIT.md、WORK-PACKAGES.md、PROBES.md、VALIDATION.md。唯一可变进度仍是 docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md。Oracle 的原始意见是顾问材料，具体实施边界以本包 WORK-PACKAGES 为准。

你获得的任务是实施 W1→W2→W3→G：挡住非空泛化完成声明掩盖明确交付对象遗漏；让已有批准来源的精确文件复用授权实际可用；修正 normal/staged driver 和无额外催促的收尾；最后验证当前候选安装及日用路径。不要新增其它能力、第二模型/工具 loop、通用义务或评测平台，不提高默认预算，不弱化审批/UNKNOWN/freshness，不重做已完成的 R1/R3/C1/C2。

基线是 0cc0db1，但请先核对当前树；不能 reset 用户修改。先运行包里的离线反例，再写能区分修前/修后的 Red，做最小 Green。原始 D04 输入、grader、补充业务检查不能放宽；不能用 helper 预填正确义务、让脚本固定补 CLI、把非空反例换回空数组，或只改文案来宣告完成。W1 只做已规定的明确交付对象约束，不承诺任意自然语言的机械证明。若确实需要改变完成合同或引入新持久协议，明确报告具体缺口，不私自扩张。

每包跑 touched-area checks，全部稳定后集中跑一次完整项目门和最终候选安装门；不要每改一处就全量重测。真实 E1 必须零额外业务提示/催促，normal 不注入 correction、不自动救场 resume，staged 只执行冻结的计划内纠正与跨进程恢复。业务通过但未终结仍是 incomplete；产品完整成功但业务失败仍是未解决，不能归咎模型后结案。

本次允许本包内的本地修复、离线测试、新的隔离候选/安装验证和文档更新；不授权 commit、push、tag、merge、发布、登录项或个人系统设置变更。不要读取/修改 .env、密钥、旧私人日志/会话或未知 result.phase.json，不得 git clean。需要真实 API 时，先一次性确认本次精确 provider/model/endpoint/thinking mode、凭据注入来源、合成数据范围、累计物理请求和墙钟预算；旧权限不继承。未授权就继续本地与安装，将真实层标 BLOCKED_AUTHORIZATION，不自行找 key。

持续完成所有当前授权内的工作，不因一次命令结束或局部 Green 就停下；到明确权限/预算/产品边界才停并说明。更新唯一 RESULTS，逐包交代修前证据、改动、source/installed/real、代码/构建物身份、真实干预次数、剩余问题和 Git dirty 清单。完成本包后停止，不开启新一轮优化。
```

## 什么时候才算完成

W1/W2/W3 的负例、完整正例与安全回归通过，最终候选来源明确，全量/安装门通过；有授权的两个真实旅程业务完整且产品自行终结。仅缺真实授权可交付“本地与安装完成，真实待授权”，不能宣传日用 beta 已放行。不要用测试数量代替这几个用户结果。
