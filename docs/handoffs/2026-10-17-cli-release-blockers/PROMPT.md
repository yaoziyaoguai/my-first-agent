# 发给执行 coding agent 的 Prompt

执行包已于 2026-10-18 合并 Codex 与 Oracle Web 5/5 建议定稿。复制下面全文即可；不必附历史聊天或任何密钥。

```text
请在 /Users/jinkun.wang/work_space/my-first-agent 执行这个修复包：
docs/handoffs/2026-10-17-cli-release-blockers/START-HERE.md

先完整阅读当前 AGENTS.md、该入口、WORK-PACKAGES.md、VALIDATION.md，以及唯一当前记录 docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md 的当前摘要。Oracle 原答和送审草案仅供理解理由，实施以最终执行包为准，不再自行开启新一轮审计/功能发散。

目标是先做出可靠可用的 macOS 单用户 CLI 候选，只按 A→B→C 完成：
A：修复明确交付文件的识别与完成下界，既防中文紧邻路径时漏做却 VERIFIED_DONE，也防规格输入/引文/日志/版本号被误判成输出；保留已正确文件 confirm-only、correction/reopen/freshness。
B：修复活跃和 pause/resume 后的 provider 外发确认。否定或默认空回车安全退出并保留任务，不得变成业务纠正、产生 receipt 或新增外发/工具效果；肯定仍走 exact typed action/CAS。首发 CLI-only，TUI 仅同步实验限制，不扩展 UI。
C：让 staged 验收严格绑定同一 Goal/会话/checkpoint 的真实 revision 增长和同一条新增 injected/consumed correction；完成当前候选的 full、non-editable 安装态增量证明。复用现有 driver 和安装 import guard 做最小装配，授权后的 normal/staged/already-correct 三个样本直接在同一 wheel 上验证，不用 source-real 冒充安装版通过。

基线不是干净 HEAD：main@0cc0db1 上有上一执行者尚未提交的实现与文档。先核对当前 HEAD、dirty 清单与审计身份，保留用户全部工作，不 reset/checkout 回旧版本，不 git clean，不读取/处理未知 result.phase.json。不要重新实现旧轮次已经完成的工作。区分用于构建产品的源码 candidate 和模型要修改的合成任务 workspace。

每包先留下可区分修前/修后的 Red，再做最小 Green 和 focused；不得删完成门、放宽权限、改 frozen SPEC/grader、提高预算或让 operator 催促/解释失败来制造通过。AgentRuntime.run_turn 仍为唯一 production loop；CLI 只翻译和渲染。禁止新增 schema/第二裁判/通用 NLP 引擎/第二 runner 平台。代码稳定后集中一次 full，再绑定同一源码身份做 installed-focused，不每改一行就全库回归；后来有相关改动须刷新失效证据。

本次允许该包范围的本地代码/测试/文档修改、专用合成测试目录和隔离候选/安装验证。不授权 commit/push/merge/tag/release、系统登录项、个人设置或新功能模块。不要读 .env、secret/credential、旧私人日志/会话、Pi/Claude 私有配置或历史 key；不得把凭据写进文档、命令字面量或日志。

真实 API 层按 VALIDATION 的明确授权清单执行。若当前对话尚未授权精确 provider/model/endpoint/thinking、凭据注入来源、合成数据范围与累计成本上限，先把所有安全的本地/安装工作完成，再一次性汇总请求这些信息；真实层标 BLOCKED_AUTHORIZATION，不擅自找 key，也不宣布 release-ready。预算建议为每样本最多40物理请求，三样本及全部重试合计最多80、60分钟；实际以当前用户批准为准，不循环重试挑成功。

持续更新唯一 RESULTS 的当前摘要与本轮证据，明确区分 LOCAL_VERIFIED、INSTALLED_VERIFIED、REAL_VERIFIED、未授权、失败、未验证。已有正确工作区的真实失败必须先定位，不凭猜测删“强制写入”逻辑。只修本包因果范围；范围外发现记录不顺手改。

完成时交付：每包修前证据/修改/具体测试节点和结果；最终源码与 wheel 身份；安装导入来源；真实样本的 typed 终态、业务结果、请求/审批/催促分类计数；剩余缺口和 Git 状态。局部绿不能代替完整验收，未执行不能写通过。三包完成或到需新授权的真实阻塞边界后停止，不自动开启第四轮。
```

如需授权真实 API，请在执行对话另行明确提供所需字段；不要把 key 粘贴进这个文件。
