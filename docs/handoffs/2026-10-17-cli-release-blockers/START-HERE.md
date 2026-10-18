# CLI 首发阻断修复包：唯一执行入口

状态：**2026-10-18 已定稿。Codex 独立方案 + Oracle Web Power 5/5 已交叉核对并合并。可交给执行者；不是产品修复完成声明。**

工作目录：`/Users/jinkun.wang/work_space/my-first-agent`。
目标：收掉已证实的日用可靠性缺口，交出可供知情用户尝试的 macOS 单用户 CLI 候选。
不是把所有历史能力升级成 production-ready，也不开始第四个功能包。

## 1. 只执行这三包

| 包 | 原审计问题 | 用户可见变化 | 结束证据 |
| --- | --- | --- | --- |
| A：可信且不过度的完成下界 | F1 漏做文件仍完成；F2 把输入/引文/版本当输出 | 同义写法不漏验；无关示例不让任务卡住；正确文件不必凑改动 | 有区分度的 Red→Green、两个 Runtime 反例、正常/confirm-only/correction/reopen 正反对照 |
| B：恢复后的同意/拒绝 | F3 no 被写成业务纠正；Enter 与 [y/N] 不一致 | 拒绝和默认拒绝真的退出，保留任务、零新外发、零意图污染 | 活跃与恢复 pending 的输入矩阵、新进程恢复、stale 与数据范围变化保护 |
| C：严谨验收与同一候选交付 | F4 state revision/别的 fact 可冒充消费证据；新版本未独立交付 | 严格绑定同一 Goal/纠正；准确说明安装与真实可用程度 | driver 伪证据负对照、最终 full、当前 wheel installed-focused、有界真实样本与诚实记录 |

顺序 **A → B → C**。C 的 driver 修补在任何新的 staged 真实验收之前完成。
每包 focused；产品/driver 稳定后集中一次 full。不要每改一处就跑约 4000 项。

## 2. 接手顺序与依据

1. 当前用户指令、仓库 `AGENTS.md`、本入口。
2. [WORK-PACKAGES.md](WORK-PACKAGES.md)：精确行为、代码范围与反例。
3. [VALIDATION.md](VALIDATION.md)：测试命令、安装身份、真实授权与停止条件。
4. [上一轮独立审计](../../audits/2026-10-17-post-closeout-product-audit/AUDIT.md) 与其中 F1–F4；必要时读同目录 probes.py、PROBE-RESULTS.json。
5. [唯一当前记录](../2026-10-11-product-reliability-closure/RESULTS.md) 的当前摘要；只沿本次相关段落追溯，不扫描旧私有日志。
6. [Oracle 原答](ORACLE-ANSWER.md)和[合并裁决](RECONCILIATION.md)只作理由来源；**接手时执行本入口、WORK-PACKAGES、VALIDATION、PROMPT 的最终版本**，不要并行执行顾问草案。

旧 `2026-10-17-daily-agent-closeout` 包已经大部实施。本包只替代其未闭合部分，不重跑旧轮次、不重建已实现能力。
`oracle-input/CODEX-DRAFT.md` 是送审前冻结快照；后续 Oracle 原答也不是第二份可变计划。

## 3. 重要基线：不是干净的 HEAD

- HEAD：`0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`，分支 `main`。基线是 **HEAD + 现有未提交工作树**，不是只取 HEAD。
- 17 个 tracked dirty 文件包含上一执行者实现；精确身份参考审计目录 IDENTITY.json。接手核对 HEAD、status、相关源文件 SHA，变化先检查差异，不能 reset/checkout 覆盖。
- 旧审计独立验证为 285 focused、3947 passed/1 skipped、ruff/diffcheck PASS；四个缺口仍成立。它们只能作基线，不能冒充本包修复后的验收。
- 已有旧包、审计目录和未知未跟踪 `result.phase.json` 原样保留；未知文件不读取、不删除、不提交。
- 不 commit/push/merge/tag/publish，不 git clean，不清理旧 `.local` 或构建目录。要新候选就用独占新目录。

本包不额外建 RESULTS。执行者持续更新旧唯一 RESULTS 的当前摘要与本轮证据行；历史结论标日期/身份，不能仍与“当前结论”并列生效。

## 4. 已确定的支持面与不做

首发 **macOS / 单用户 / CLI / 当前 workspace / 有界文件与编码任务**。
TUI、Browser、Scheduler、Memory、MCP、Skill、SubAgent 保留现有实现，但本包不补功能、不作全能力晋级。
TUI 的恢复 disclosure 缺口作为实验功能已知限制明示，日用默认路径不再推荐 `[tui]`；不删除 TUI、不拆 UI。

不做：通用 NLP 需求引擎、第二模型裁判/循环、全局 authority registry、schema 迁移、新 provider、跨平台 host、登录项、后台 daemon、桌面接管、并发写入 Agent、按行数拆文件或无关架构整理。
已有唯一 Runtime、ContextManager、ToolRuntime、policy/approval、EXECUTING/result checkpoint、UNKNOWN 不重放、CAS、精确租约与 freshness 都必须保留。

## 5. 权限与交付分级

用户在新执行对话明确让你执行本包后，可以做本范围的代码/测试/文档修改、离线测试、专用合成临时资源、隔离候选和安装检查。**生成本包本身不等于这些修复已经执行，也不授予真实 API 或 Git 发布权限。**

不要读 `.env`、secret/credential、历史私有日志/会话、私人 Memory/MCP/Skill/SubAgent 内容；产品公开源码不受这些私有目录禁读的误判影响。不要从 Pi、Claude、旧聊天找 key，不抄历史 key。

缺当前真实 API 授权时，先完成本地与安装层，再汇总一次所需授权；真实层记 `BLOCKED_AUTHORIZATION`。不得因此停掉所有离线工作，也不能把未验证写成“可发布”。
全部本地和安装 PASS ≠ 真实模型 PASS ≠ 发布/用户接受。交付必须分列。正式本包真实门为同一 wheel 上的 normal/staged/already-correct 三样本，不以 source-real + installed-offline 拼成 installed-real。完成三包或遇到需用户新授权/真实外部阻塞时结束，不自动再开优化轮。

可复制任务见 [PROMPT.md](PROMPT.md)。
