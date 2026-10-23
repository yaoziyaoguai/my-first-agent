# 确认疲劳修复包

日期：2026-10-21。目标：让用户完成一个普通工作区任务时，不必因相同范围的操作、
历史消息或内部控制回执反复回答 `yes`。本包不新增 Agent 能力，不把安全围栏关掉。

**这是待执行的修复合同，不是已经完成的修复报告。**

## 1. 从哪里开始

1. 读本文件与项目 `AGENTS.md`。
2. 读 [审计](AUDIT.md)，了解已证实的问题与证据限制。
3. 完整读 [冻结行为合同](SPEC.md)、[工作包](WORK-PACKAGES.md)、[验收](VALIDATION.md)。
4. 执行顺序以 WORK-PACKAGES 为准。最小 Red → Green → focused；全部完成后才集中跑完整门。
5. 最终顺序是 W1合同/来源/持久化 → W2发送门 → W3 CLI → G新安装交付；执行进度只写到既有
   [RESULTS.md](../2026-10-11-product-reliability-closure/RESULTS.md) 顶部的本轮章节。
   本目录是冻结合同与审计输入，不再创建第二个 CURRENT/RESULTS。

给其他 coding agent 的入口：[PROMPT.md](PROMPT.md)。
外部审查与本地裁决：[Oracle 原答](ORACLE-ANSWER.md)、[采纳说明](RECONCILIATION.md)、
[调用凭证](ORACLE-RECEIPT.json)。Oracle 只提供建议，不授予权限；最终实现服从本包 SPEC。

## 2. 为什么是这轮，而不是再加功能

- 三轮普通对话实测需要两次外发确认，第二次仅新增 `conversation_history`。
- 恢复时 `conversation_history`、`control_receipts` 的加入也会再次打断。
- 文件重复修改已经有范围授权，但主提示是 `[y/N]`，`yes` 只批一笔；用户必须发现并记住
  `/approve-goal-target` 等命令才能使用已有能力。
- 真实历史普通编码样本虽曾完成，仍用了12次正常治理确认；这不是本轮的准确前后对照，
  也不是用户本次私人试用的统计。本轮必须使用固定离线旅程重新计数。

因此本轮做两件用户可见的事：**把可复用选择直接放在确认处；明确同意一个有界范围后，
同范围内继续工作。** 新会话许可固定32次/60分钟；文件f/d沿用16次/60分钟。
同时补齐必要的内置文件来源证明、持久化、撤销、恢复和新安装证据。仅修改README不算完成。

## 3. 基线与已有工作

- 审计基线：`main @ 97f5c584e9e266930fbcf283aa3199b3609e8178`。
- [SOURCE-IDENTITY.json](oracle-input/SOURCE-IDENTITY.json) 记录13个关键公开文件的完整 SHA。
  接手时检查漂移；非冲突的用户改动保留。不要 reset/clean 或覆盖整棵工作树。
- [BASELINE.json](BASELINE.json) 来自 [baseline_probe.py](baseline_probe.py)：零网络、
  内存合成状态、真实生产 Runtime + ScriptedProvider。它是旧行为观测器，不是新验收 oracle。
- 本轮已有相关检查：153 passed；未实现任何新产品行为，未运行本轮全库或真实 API。
- 未知 `result.phase.json` 属用户内容：不读、不删、不提交。
- 旧安装预览不会随源码自动更新。本轮交付必须提供新的 non-editable wheel 安装身份、
  独立状态目录和真实可用的启动命令，保留旧安装。

## 4. 明确不做

- 不增加全局 trust/allow-all、自动 yes、命令前缀白名单或第二套权限引擎。
- 不改变现有文件/进程租约边界，不把 `local_process` 说成 sandbox。
- 不扩大 Memory/MCP/Skill/SubAgent/browser/scheduler 能力，不动登录项、后台服务和系统设置。
- 不改任务完成语义、业务 grader 或以前的失败记录，不重开 E2/E3 等未闭合真实验收。
- 不全面重做 TUI，不重构巨石文件，不追加新优化轮次。
- 不读凭据、私人会话或未知未跟踪文件；不继承历史 API key/费用授权。
- 不 commit、push、merge、tag、发布、改 remote。收到用户另一次明确指令再做 Git 交付。

## 5. 完成分层

- **实现完成：** SPEC 的行为和安全负控闭合，Red→Green 与 focused 有证据。
- **本地/安装验证完成：** 固定确认预算旅程成功；全库门完成；同一最终源码的新 wheel
  安装态重跑指定旅程，排除导入旧源码/旧 build/lib。
- **真实模型验证：** 没有本轮授权则记 `NOT_RUN_AUTHORIZATION`，不得伪写 PASS。
- **用户体验验收：** 新安装交付后由用户试用确认。自动测试能证明次数与效果，不能代替
  用户判断“顺不顺手”。不因这项尚未发生而自行启动新一轮开发。

执行者最后交付：具体改动、逐项验证、确认次数前后表、新安装/启动命令、剩余限制。
不得把“测试很多”或“Oracle 同意方案”当成用户已经接受产品。
