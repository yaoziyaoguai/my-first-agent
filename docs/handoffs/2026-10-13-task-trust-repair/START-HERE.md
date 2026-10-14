# 任务结果可信修复包：唯一入口

日期：2026-10-13。状态：**执行包已准备，产品修复尚未开始**。

工作目录：`/Users/jinkun.wang/work_space/my-first-agent`。
审计基线：`main`，`ff686bd14642e8ec5041cced6a21daf7c03f8d17`（PR #4 已合并）。

## 1. 本包到底修什么

只解决本次审计的四个实际问题，不把体验愿望、证据门或历史优化混成新的功能目标。

| 上一轮审计问题 | 本包 ID | 必须改变的用户可见结果 | 主要验收 |
| --- | --- | --- | --- |
| P1：已执行、结果保存失败，后来被记为未执行 | R1 UNKNOWN | 不丢失不确定执行状态，不伪造未执行，不自动重放 | 真实 callable 计数 + 连续保存失败 + 重开/恢复 + wire 投影 |
| P1：D04 漏做 CLI 别名却宣布 VERIFIED_DONE | R2 COMPLETION | 漏做/未验证不能报完整成功；真正做完仍能正常闭合 | 不完整候选反例 + 完整候选正例 + 独立业务 grader + 有界真实模型旅程 |
| P1：中文换一种表达就漏记必做校验 | R3 INTENT | 明确要求运行测试的等义输入建立相同义务；禁止执行仍受尊重 | 用户事实→Goal admission→completion gate 的正反例 |
| P2：CLI 任务范围授权需要界面不显示的 ID | R4 CONSENT | 普通用户可从当前审批提示完成已有范围授权，不必查内部状态 | renderer→parser→typed action→Runtime 的交互链路 |

**ID 与审计顺序一一对应。实施顺序为 R1 → R3 → R2 → R4 → 最终交付门。** R2 依赖 R3 的义务识别；这只是调整顺序，没有遗漏审计问题。

以下只是四项修复的证明，不是第五、第六个功能：

- 当前最终代码的安装态证明：旧 wheel 的 `state.py`、`loop.py` 不等于合并版，不能沿用旧通过。
- 既有 P2-2：writer 关闭后重验与 provider wire 的组合回归。
- 既有 P2-3：安全闭合的 tool facts 经真实 OpenAI/Anthropic 投影配对。
- 本轮受影响帮助/状态说明的最小同步。

## 2. 明确不做

- 不新增自然语言“完成后继续修改”的新任务机制；保持现有 `/new` 边界。
- 不新增 CLI 运行中抢占、后台 daemon、登录项、跨平台 host、桌面接管。
- 不扩展 Memory/MCP/Skill/SubAgent，不换模型，不增加模型预算默认值。
- 不重构整个 Agent，不按文件行数拆分，不重绑所有历史 capability seals。
- 不新建评测平台、第二套模型循环、自动外部审计服务或通用自然语言权限引擎。
- 不全面改写 README 历史资料；只同步本轮改变的具体命令/语义。
- 不把本包写成“所有功能/所有语义任务已经可靠”的承诺。

## 3. 阅读顺序和唯一记录

1. 当前用户指令与仓库 `AGENTS.md`。
2. 本文件。
3. [WORK-PACKAGES.md](WORK-PACKAGES.md)：每项边界、修复步骤、通过/失败条件。
4. [REPRODUCERS.md](REPRODUCERS.md)：公开证据与可执行离线探针。
5. [VALIDATION.md](VALIDATION.md)：focused、安装、full、真实层及交付格式。
6. 既有 [RESULTS.md](../2026-10-11-product-reliability-closure/RESULTS.md)：**继续作为唯一可变执行记录**。本包不创建另一份 RESULTS。

旧包 W1–W4/V1/V2 是历史工作，不重新执行其整套计划。本包对相同问题的范围/验收以本包为准；项目安全与架构约束仍有效。

## 4. 架构与权限

- `AgentRuntime.run_turn` 保持唯一 production model/tool loop；ContextManager 选上下文，ToolRuntime 调工具。
- CLI/TUI 只翻译 action、显示 result，不能直接改 checkpoint 或铸造完成/批准事实。
- 权限、执行事实、业务验收分开：用户同意一次写入，不代表他确认内容正确；模型提出要验证，不等于取得执行权限。
- 不确定结果不能被清理/压缩/恢复改写成已执行成功或确定未执行。
- 收到用户的本包执行指令后，可做公开代码/测试的必要局部修改、合成 fixture、只属于本次测试的本地进程、离线候选构建与安装；按项目默认在 `main` 工作，不回退用户修改。
- **不授予 commit/push/tag/merge/publish 权限。** 已合并 PR #4 不构成这次 Git 写权限。
- 不读取旧私人日志/会话、`.env`、secret/credential、`.local` 历史运行、未跟踪根 `tui/` 或私人扩展目录；不从过去聊天取 key。
- 真实 API 另按 VALIDATION 的当前授权清单执行；本包本身没有批准费用或凭据读取。历史 manifest 的 `real_dispatch_authorized=true` 不是当前人类授权。
- 新建的合成测试产物放本次唯一临时目录；不能删除旧候选来腾名字，不清空用户目录。

## 5. 接手和完成定义

接手先核对 HEAD、分支、dirty 清单及相关源码；基线变化先检查差异，不 checkout/reset 到旧提交。先复现 R1、R3，不先跑全库。产品改动先 Red，再最小 Green；R2 按工作包先建立可区分反例，不能预设真实历史失败一定由某一个函数造成。

四项都必须有独立结果行。`LOCAL_VERIFIED`、`INSTALLED_VERIFIED`、`REAL_VERIFIED`、`BLOCKED_AUTHORIZATION`、`UNRESOLVED` 分层记录，不用总测试数替代。

- 四项本地行为 + 必需组合回归 + 最终安装 + full 全通过，才能称“本地修复闭合”。
- R2 真实任务未执行/失败，只能称“R2 离线修复已验证，真实任务可靠性未闭合”，不能整体宣告本包完成。
- 真实调用授权缺失只阻塞对应真实层，其余可继续；不要假称没 key 就不能修确定性 bug。
- 局部测试绿、命令结束、token 剩余都不是完成条件；也不允许无限付费重试直到挑出成功样本。

## 6. 可以复制给执行 Agent 的 Prompt

```text
在 /Users/jinkun.wang/work_space/my-first-agent 执行
docs/handoffs/2026-10-13-task-trust-repair/START-HERE.md 指向的完整修复包。
先完整阅读 AGENTS.md、START-HERE、WORK-PACKAGES、REPRODUCERS、VALIDATION，以及既有 RESULTS 的当前摘要。
只修 R1 UNKNOWN、R2 假完成、R3 明确校验义务漏记、R4 CLI 已有范围授权入口。
按 R1→R3→R2→R4 顺序；逐项先 Red 后最小 Green，每项 focused，最终代码一次增量 installed，再一次 full。
R1 不得把未知结果补成 executed=False；R2 不得只改文案或只证明自写测试通过；R3 不得靠放宽权限解决识别问题；R4 不得新增或扩大授权。
不改 frozen grader，不新增能力、第二套 loop、评测平台或历史 checkpoint 通用迁移。
唯一进度写 docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md 的本轮小节。
未获得我在本次对话中的明确授权，不读取凭据/旧私人运行，不进行付费API，也不 commit/push/merge。
本地可安全推进的工作先做完；真实模型只在核对当前 provider/model/credential source/合成数据/预算授权后运行。
报告按 R1/R2/R3/R4 和 source/installed/real 分层，写出精确命令、版本、失败与限制。
不要把本地通过写成真实任务已成功，也不要为制造clean删除任何用户文件。
```
